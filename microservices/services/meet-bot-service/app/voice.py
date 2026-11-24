"""Natural female speech routed into a separate WebRTC microphone in each meeting tab."""
import asyncio
import base64
from pathlib import Path


MICROPHONE_SCRIPT = Path(__file__).with_name("voice_microphone.js").read_text(encoding="utf-8")


async def synthesize_voice(message: str) -> bytes:
    import edge_tts
    from app.config import get_settings
    settings = get_settings()
    speech = edge_tts.Communicate(
        message, voice=settings.MEET_BOT_VOICE,
        rate=settings.MEET_BOT_VOICE_RATE,
        volume=settings.MEET_BOT_VOICE_VOLUME,
    )
    async def collect():
        chunks = []
        async for chunk in speech.stream():
            if chunk["type"] == "audio":
                chunks.append(chunk["data"])
        return b"".join(chunks)
    audio = await asyncio.wait_for(collect(), timeout=45)
    if not audio:
        raise RuntimeError("Natural voice service returned no audio")
    return audio


async def speak_into_meeting(page, message: str) -> bool:
    audio = await synthesize_voice(message)
    return bool(await asyncio.wait_for(page.evaluate(
        "async audio => Boolean(window.clahanMicrophone && await window.clahanMicrophone.speak(audio))",
        base64.b64encode(audio).decode("ascii"),
    ), timeout=90))
