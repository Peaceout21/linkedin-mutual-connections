"""
Run this once to save your LinkedIn session cookies.
A browser window opens. You log in manually. Session saved to linkedin_storage.json.
"""

import asyncio
import json
from playwright.async_api import async_playwright


async def save_linkedin_session():
    print("Opening browser... Log into LinkedIn, then press Enter here.")

    async with async_playwright() as p:
        browser = await p.chromium.launch(
            headless=False,
            args=["--start-maximized"]
        )
        context = await browser.new_context(
            viewport={"width": 1280, "height": 800},
            user_agent=(
                "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/121.0.0.0 Safari/537.36"
            )
        )

        page = await context.new_page()
        await page.goto("https://www.linkedin.com/login")

        input(">>> Log into LinkedIn in the browser window, then press Enter: ")

        # Save full storage state (cookies + localStorage) — browser-use uses this format
        storage = await context.storage_state()
        with open("linkedin_storage.json", "w") as f:
            json.dump(storage, f, indent=2)

        cookie_count = len(storage.get("cookies", []))
        print(f"Saved {cookie_count} cookies to linkedin_storage.json")
        await browser.close()


if __name__ == "__main__":
    asyncio.run(save_linkedin_session())
