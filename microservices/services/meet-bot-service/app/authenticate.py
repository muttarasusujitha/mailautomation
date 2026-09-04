"""Open a persistent browser profile for one-time manual Google sign-in."""
import asyncio
import os

from playwright.async_api import async_playwright


async def main() -> None:
    profile = os.environ.get("MEET_BOT_PROFILE_PATH", "./meet-bot-profile")
    async with async_playwright() as playwright:
        context = await playwright.chromium.launch_persistent_context(
            profile,
            headless=False,
            viewport={"width": 1280, "height": 800},
        )
        page = context.pages[0] if context.pages else await context.new_page()
        await page.goto("https://meet.google.com/", wait_until="domcontentloaded")
        print("Sign in to the dedicated bot account, verify Meet access, then press Enter here.")
        await asyncio.to_thread(input)
        await context.close()


if __name__ == "__main__":
    asyncio.run(main())
