import asyncio, json, re
from playwright.async_api import async_playwright

async def run_spike():
    with open('fb_cookies.json') as f:
        cookies = json.load(f)

    formatted = []
    for c in cookies:
        obj = {
            'name': c['name'],
            'value': c['value'],
            'domain': c.get('domain', '.facebook.com'),
            'path': c.get('path', '/'),
        }
        if 'secure' in c: obj['secure'] = c['secure']
        if 'httpOnly' in c: obj['httpOnly'] = c['httpOnly']
        if 'sameSite' in c and c['sameSite'] in ['Strict', 'Lax', 'None']:
            obj['sameSite'] = c['sameSite']
        formatted.append(obj)

    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        ctx = await browser.new_context(
            viewport={'width': 1280, 'height': 850},
            user_agent='Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/128.0.0.0 Safari/537.36',
            locale='vi-VN',
        )
        await ctx.add_cookies(formatted)
        page = await ctx.new_page()

        test_group = 'https://www.facebook.com/groups/1325003928108317/'
        print(f"Spike: Navigating to {test_group}...")
        await page.goto(test_group, wait_until='domcontentloaded')
        await asyncio.sleep(3.5)
        for _ in range(2):
            await page.evaluate('window.scrollBy(0, 1000)')
            await asyncio.sleep(1.2)

        posts = page.locator('div[role="feed"] > div, div[role="article"]')
        count = await posts.count()
        print(f"Spike: Found {count} post candidate elements.")

        total_comments = 0
        total_reactions = 0
        valid_posts = 0

        for i in range(min(count, 10)):
            text = await posts.nth(i).evaluate('el => el.innerText || ""')
            if len(text.strip()) < 30: continue
            valid_posts += 1
            # Check comment matches
            c_matches = re.findall(r'(\d+)\s*(?:bình luận|phản hồi)', text, re.I)
            r_matches = re.findall(r'(\d+)\s*(?:người khác|lượt bày tỏ)', text, re.I)
            if c_matches:
                total_comments += sum(int(m) for m in c_matches)
            if r_matches:
                total_reactions += sum(int(m) for m in r_matches)

        print(f"Spike Results: Valid Posts: {valid_posts}, Total Comments: {total_comments}, Total Reactions: {total_reactions}")
        assert valid_posts > 0, "No valid posts found in spike"
        print("Spike SUCCESS!")
        await browser.close()

if __name__ == '__main__':
    asyncio.run(run_spike())
