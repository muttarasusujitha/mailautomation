import asyncio
from playwright.async_api import async_playwright
from app.config import get_settings
async def main():
 s=get_settings()
 async with async_playwright() as p:
  c=await p.chromium.launch_persistent_context(s.MEET_BOT_PROFILE_PATH,headless=s.MEET_BOT_HEADLESS,args=['--no-sandbox','--disable-dev-shm-usage'])
  try:
   page=await c.new_page(); await page.goto('https://meet.google.com/vmw-ofjm-fxx',wait_until='domcontentloaded'); await page.wait_for_timeout(12000)
   print((await page.locator('body').inner_text())[:6000])
  finally: await c.close()
asyncio.run(main())
