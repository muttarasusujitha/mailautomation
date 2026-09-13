"""Offline speech routed into a separate WebRTC microphone in each meeting tab."""
import asyncio
import base64
from pathlib import Path


MICROPHONE_SCRIPT = Path(__file__).with_name("voice_microphone.js").read_text(encoding="utf-8")


async def speak_into_meeting(page, message: str) -> bool:
    process = await asyncio.create_subprocess_exec(
        "espeak-ng", "--stdout", "-v", "en", "-s", "155", "--stdin",
        stdin=asyncio.subprocess.PIPE, stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    try:
        audio, error = await asyncio.wait_for(process.communicate(message.encode()), timeout=20)
    except BaseException:
        if process.returncode is None:
            process.kill()
        await process.wait()
        raise
    if process.returncode or not audio.startswith(b"RIFF"):
        raise RuntimeError("Welcome voice synthesis failed")
    return bool(await asyncio.wait_for(page.evaluate(
        "async wav => Boolean(window.clahanMicrophone && await window.clahanMicrophone.speak(wav))",
        base64.b64encode(audio).decode("ascii"),
    ), timeout=90))
