import asyncio, json, os
from pathlib import Path
from types import SimpleNamespace
from playwright.async_api import async_playwright
from app import main

class Log:
    async def update_one(self, query, update):
        print(json.dumps(update, default=str), flush=True)

async def run():
    main.settings.MEET_BOT_HEADLESS = True
    async with async_playwright() as pw:
        context = await main._launch_browser(pw)
        page = await context.new_page()
        try:
            await page.goto('https://meet.google.com/jzy-brvd-bbj', wait_until='domcontentloaded', timeout=60000)
            await page.wait_for_timeout(5000)
            await main._click_if_visible(page, ['Turn off camera'])
            await main._click_if_visible(page, ['Turn off microphone', 'Mute microphone'])
            print('PREJOIN ' + (await page.locator('body').inner_text())[:5000], flush=True)
            if not await main._join_when_ready(page):
                raise RuntimeError('Join control unavailable after waiting')
            print('ADMISSION_REQUESTED', flush=True)
            await page.get_by_role('button', name='Leave call', exact=False).first.wait_for(state='visible', timeout=180000)
            print('JOINED', flush=True)
            await page.wait_for_timeout(3000)
            await main._click_if_visible(page, ['Turn off microphone', 'Mute microphone'])
            spoken = await main._speak_welcome(page, {'client_name':'Test participant', 'trainer_name':'Test participant'}, SimpleNamespace(email_logs=Log()), 'LIVE-VOICE-TEST')
            print('VOICE_RESULT ' + str(spoken), flush=True)
            await page.wait_for_timeout(15000)
        except Exception:
            print('PAGE ' + (await page.locator('body').inner_text())[:5000], flush=True)
            raise
        finally:
            await main._click_if_visible(page, ['Leave call'])
            await context.close()

asyncio.run(run())
