"""Exercise speech across two local WebRTC peers; never opens a real meeting.

Run inside the built container: python -m app.verify_voice
"""
import asyncio
import json

from playwright.async_api import async_playwright
from app.voice import MICROPHONE_SCRIPT, speak_into_meeting


async def main():
    async with async_playwright() as playwright:
        browser = await playwright.chromium.launch(headless=True, args=[
            "--no-sandbox", "--autoplay-policy=no-user-gesture-required",
        ])
        try:
            context = await browser.new_context()
            await context.add_init_script(MICROPHONE_SCRIPT)
            await context.route("https://voice-test.invalid/**", lambda route: route.fulfill(
                content_type="text/html", body="<html><body>Local voice transport test</body></html>"))
            page = await context.new_page()
            silent_page = await context.new_page()
            for tab in (page, silent_page):
                await tab.goto("https://voice-test.invalid/")
                await tab.evaluate("""async () => {
                    window.testStream = await navigator.mediaDevices.getUserMedia({audio: true});
                    const meterContext = new AudioContext();
                    window.meter = meterContext.createAnalyser();
                    meterContext.createMediaStreamSource(testStream).connect(meter);
                    await meterContext.resume();
                    window.peak = 0;
                    window.meterTimer = setInterval(() => {
                        const data = new Float32Array(meter.fftSize);
                        meter.getFloatTimeDomainData(data);
                        window.peak = Math.max(window.peak, ...data.map(Math.abs));
                    }, 10);
                }""")
            await page.evaluate("""async () => {
                const sender = new RTCPeerConnection({iceServers: []});
                const receiver = new RTCPeerConnection({iceServers: []});
                window.peers = [sender, receiver];
                sender.onicecandidate = e => e.candidate && receiver.addIceCandidate(e.candidate);
                receiver.onicecandidate = e => e.candidate && sender.addIceCandidate(e.candidate);
                window.remotePeak = 0;
                const ready = new Promise(resolve => {
                    receiver.ontrack = async e => {
                        const audio = new AudioContext();
                        const analyser = audio.createAnalyser();
                        audio.createMediaStreamSource(e.streams[0]).connect(analyser);
                        await audio.resume();
                        window.remoteTimer = setInterval(() => {
                            const data = new Float32Array(analyser.fftSize);
                            analyser.getFloatTimeDomainData(data);
                            window.remotePeak = Math.max(window.remotePeak, ...data.map(Math.abs));
                        }, 10);
                        resolve();
                    };
                });
                sender.addTrack(testStream.getAudioTracks()[0], testStream);
                await sender.setLocalDescription(await sender.createOffer());
                await receiver.setRemoteDescription(sender.localDescription);
                await receiver.setLocalDescription(await receiver.createAnswer());
                await sender.setRemoteDescription(receiver.localDescription);
                await ready;
            }""")
            await page.wait_for_function("peers[0].connectionState === 'connected'", timeout=15000)
            spoken = await speak_into_meeting(page, "Hello. This is the Clahan automated meeting assistant.")
            await page.wait_for_timeout(300)
            remote_peak = await page.evaluate("remotePeak")
            other_peak = await silent_page.evaluate("peak")
            assert spoken and remote_peak > 0.001, "Speech did not reach the remote WebRTC peer"
            assert other_peak == 0, "Speech leaked into another meeting tab"
            print(json.dumps({"voice_played": spoken, "remote_audio_peak": remote_peak,
                              "other_meeting_peak": other_peak, "result": "passed"}))
        finally:
            await browser.close()


if __name__ == "__main__":
    asyncio.run(main())
