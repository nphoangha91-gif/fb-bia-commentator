import asyncio
import json
from playwright.async_api import async_playwright

async def is_messenger_element(locator) -> bool:
    """Checks if a locator is inside a Messenger chat dock, chat head, or message tab."""
    if await locator.count() == 0:
        return False
    return await locator.first.evaluate("""el => {
        if (!el) return false;
        const chatParent = el.closest('[data-pagelet*="ChatTab"], [aria-label*="Đoạn chat" i], [aria-label*="Chat with" i], [aria-label*="Tin nhắn" i], [aria-label*="Messenger" i], [role="region"][aria-label*="chat" i]');
        const ariaLabel = (el.getAttribute('aria-label') || '').toLowerCase();
        const placeholder = (el.getAttribute('placeholder') || '').toLowerCase();
        const isChatAria = ariaLabel.includes('tin nhắn') || ariaLabel.includes('chat') || ariaLabel.includes('message');
        const isChatPlaceholder = placeholder.includes('tin nhắn') || placeholder.includes('chat') || placeholder.includes('message');
        return chatParent !== null || isChatAria || isChatPlaceholder;
    }""")

async def is_active_element_messenger(page) -> bool:
    """Checks if document.activeElement is inside a Messenger chat dock."""
    return await page.evaluate("""() => {
        const active = document.activeElement;
        if (!active || active === document.body) return false;
        const chatParent = active.closest('[data-pagelet*="ChatTab"], [aria-label*="Đoạn chat" i], [aria-label*="Chat with" i], [aria-label*="Tin nhắn" i], [aria-label*="Messenger" i], [role="region"][aria-label*="chat" i]');
        const ariaLabel = (active.getAttribute('aria-label') || '').toLowerCase();
        const placeholder = (active.getAttribute('placeholder') || '').toLowerCase();
        const isChatAria = ariaLabel.includes('tin nhắn') || ariaLabel.includes('chat') || ariaLabel.includes('message');
        const isChatPlaceholder = placeholder.includes('tin nhắn') || placeholder.includes('chat') || placeholder.includes('message');
        return chatParent !== null || isChatAria || isChatPlaceholder;
    }""")

async def close_all_chat_windows(page):
    """Closes or minimizes any open floating Messenger chat docks on Facebook."""
    close_selectors = [
        'div[aria-label="Đóng đoạn chat"]',
        'div[aria-label="Close chat"]',
        'div[aria-label="Đóng cuộc trò chuyện"]',
        'div[data-pagelet="ChatTab"] div[aria-label*="Đóng"][role="button"]',
        'div[data-pagelet="ChatTab"] div[aria-label*="Close"][role="button"]',
        'div[role="region"][aria-label*="Đoạn chat" i] div[aria-label*="Đóng"][role="button"]',
    ]
    closed_count = 0
    for sel in close_selectors:
        btns = page.locator(sel)
        cnt = await btns.count()
        for idx in range(cnt):
            btn = btns.nth(idx)
            if await btn.is_visible():
                try:
                    await btn.click()
                    closed_count += 1
                    await asyncio.sleep(0.5)
                except Exception:
                    pass
    return closed_count

async def test_mock_dom(page):
    """Verifies detection and isolation logic against a synthetic DOM representing Facebook's layout."""
    html = """
    <html>
      <body>
        <div role="feed">
          <div role="article" id="post_1">
            <h2><strong>Tác giả 1</strong></h2>
            <div dir="auto">Nội dung bài viết về cơ bida</div>
            <div role="button">Bình luận</div>
            <div role="textbox" contenteditable="true" aria-label="Viết bình luận công khai..."></div>
          </div>
        </div>
        <!-- Messenger Floating Chat Dock at bottom right of page -->
        <div data-pagelet="ChatTab" role="region" aria-label="Đoạn chat với Khách Hàng">
          <div role="button" aria-label="Đóng đoạn chat">X</div>
          <div role="textbox" contenteditable="true" aria-label="Nhập tin nhắn..."></div>
        </div>
      </body>
    </html>
    """
    await page.set_content(html)
    
    post_box = page.locator('#post_1 div[role="textbox"][contenteditable="true"]')
    chat_box = page.locator('[data-pagelet="ChatTab"] div[role="textbox"][contenteditable="true"]')
    last_box = page.locator('div[role="textbox"][contenteditable="true"]').last

    # 1. Verify that the dangerous .last selects chat_box
    is_last_chat = await is_messenger_element(last_box)
    assert is_last_chat is True, "Error: last_box was expected to be recognized as messenger!"
    print("Test 1 Passed: Recognized that un-scoped .last targets Messenger chat tab.")

    # 2. Verify that scoped post_box is recognized as NOT messenger
    is_post_chat = await is_messenger_element(post_box)
    assert is_post_chat is False, "Error: post_box was falsely flagged as messenger!"
    print("Test 2 Passed: Recognized post comment box is NOT Messenger.")

    # 3. Verify activeElement detection
    await chat_box.focus()
    active_chat = await is_active_element_messenger(page)
    assert active_chat is True, "Error: Active element was not flagged as messenger!"
    print("Test 3 Passed: Active element in chat dock correctly detected as Messenger.")

    await post_box.focus()
    active_post = await is_active_element_messenger(page)
    assert active_post is False, "Error: Active element in post was falsely flagged as messenger!"
    print("Test 4 Passed: Active element in post box correctly detected as NOT Messenger.")

    # 4. Verify close_all_chat_windows
    c = await close_all_chat_windows(page)
    print(f"Test 5 Passed: close_all_chat_windows executed cleanly (closed {c} chats).")

async def test_live_facebook(page):
    with open('fb_cookies.json') as f:
        cookies = json.load(f)
    formatted = []
    for c in cookies:
        formatted.append({
            'name': c['name'],
            'value': c['value'],
            'domain': c.get('domain', '.facebook.com'),
            'path': c.get('path', '/'),
            'secure': c.get('secure', True),
            'httpOnly': c.get('httpOnly', True)
        })
    await page.context.add_cookies(formatted)
    print("Navigating to Facebook group for live DOM defense check...")
    await page.goto('https://www.facebook.com/groups/1325003928108317/?sorting_setting=CHRONOLOGICAL', wait_until='domcontentloaded')
    await asyncio.sleep(4.0)

    # Run close_all_chat_windows
    await close_all_chat_windows(page)
    print("Live Facebook: close_all_chat_windows executed on live DOM without errors.")

    # Check active element
    is_active_chat = await is_active_element_messenger(page)
    assert is_active_chat is False, "Active element on fresh group load should not be chat."
    print("Live Facebook: Active element is clean (not Messenger).")

async def main():
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        page = await browser.new_page()
        print("--- Running Test Mock DOM ---")
        await test_mock_dom(page)
        print("--- Running Test Live Facebook ---")
        await test_live_facebook(page)
        await browser.close()
        print("\nALL SPIKE TESTS PASSED SUCCESSFULLY! ✅")

if __name__ == '__main__':
    asyncio.run(main())
