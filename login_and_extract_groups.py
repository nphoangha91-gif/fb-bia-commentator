import asyncio
import csv
import json
import os
import re
from playwright.async_api import async_playwright

ASSETS_DIR = os.path.dirname(os.path.abspath(__file__))
ENV_FILE = os.path.join(ASSETS_DIR, "env.txt")
COOKIES_FILE = os.path.join(ASSETS_DIR, "fb_cookies.json")
OUTPUT_JSON = os.path.join(ASSETS_DIR, "facebook_joined_groups.json")
OUTPUT_CSV = os.path.join(ASSETS_DIR, "facebook_joined_groups.csv")
JOINS_URL = "https://www.facebook.com/groups/joins/?nav_source=tab"

def log(msg):
    print(msg, flush=True)

async def main():
    log("==================================================")
    log("🔐 ĐĂNG NHẬP TÀI KHOẢN MỚI & TRÍCH XUẤT DANH SÁCH NHÓM")
    log("==================================================")

    # 1. Đọc tài khoản từ env.txt
    if not os.path.exists(ENV_FILE):
        log(f"❌ Không tìm thấy {ENV_FILE}!")
        return

    with open(ENV_FILE, "r", encoding="utf-8") as f:
        lines = [l.strip() for l in f.readlines() if l.strip()]

    if len(lines) < 2:
        log("❌ env.txt phải chứa 2 dòng: Username và Password!")
        return

    username = lines[0]
    password = lines[1]
    log(f"👤 Tài khoản: {username}")

    async with async_playwright() as p:
        browser = await p.chromium.launch(
            headless=True,
            args=[
                "--disable-blink-features=AutomationControlled",
                "--no-sandbox",
                "--disable-setuid-sandbox"
            ]
        )
        context = await browser.new_context(
            viewport={"width": 1280, "height": 900},
            user_agent="Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/128.0.0.0 Safari/537.36",
            locale="vi-VN",
            timezone_id="Asia/Ho_Chi_Minh"
        )
        page = await context.new_page()

        log("🌐 Điều hướng đến trang đăng nhập Facebook...")
        await page.goto("https://www.facebook.com/login/", wait_until="domcontentloaded")
        await asyncio.sleep(3.0)

        # Điền thông tin đăng nhập
        log("✍️ Điền tài khoản và mật khẩu...")
        email_field = page.locator('input#email, input[name="email"]').first
        await email_field.fill(username)
        await asyncio.sleep(1.0)

        pass_field = page.locator('input#pass, input[name="pass"], input[type="password"]').first
        await pass_field.fill(password)
        await asyncio.sleep(1.0)

        log("👆 Bấm Đăng nhập...")
        login_btn = page.locator('button#loginbutton, button[type="submit"], button[name="login"]').first
        await login_btn.click()
        await asyncio.sleep(8.0)

        # Chụp ảnh trạng thái sau khi đăng nhập
        login_proof = os.path.join(ASSETS_DIR, "after_login_state.png")
        await page.screenshot(path=login_proof)
        log(f"📸 Đã lưu ảnh trạng thái: {login_proof}")

        # Kiểm tra đăng nhập thành công
        profile_sel = page.locator('svg[aria-label="Trang cá nhân của bạn"], div[aria-label="Tài khoản của bạn"], div[aria-label="Menu"], a[href*="/me"]').first
        is_logged_in = await profile_sel.count() > 0

        # Kiểm tra nút "Tiếp tục" nếu có
        if not is_logged_in:
            btn_continue = page.locator('button:has-text("Tiếp tục"), div[role="button"]:has-text("Tiếp tục"), a:has-text("Tiếp tục")').first
            if await btn_continue.count() > 0 and await btn_continue.is_visible():
                log("👆 Tìm thấy nút Tiếp tục, đang bấm...")
                await btn_continue.click()
                await asyncio.sleep(5.0)
                is_logged_in = await profile_sel.count() > 0

        if not is_logged_in and "checkpoint" in page.url:
            log(f"⚠️ Tài khoản đang ở màn hình Checkpoint/2FA: {page.url}")
            await browser.close()
            return

        if not is_logged_in and "login" in page.url:
            log(f"❌ Đăng nhập không thành công! URL: {page.url}")
            await browser.close()
            return

        log("🎉 ĐĂNG NHẬP THÀNH CÔNG! Đang trích xuất và cập nhật cookies mới...")
        new_cookies = await context.cookies()
        with open(COOKIES_FILE, "w", encoding="utf-8") as f:
            json.dump(new_cookies, f, indent=2, ensure_ascii=False)
        log(f"🍪 Đã lưu cookies mới vào: {COOKIES_FILE}")

        # 2. Điều hướng đến trang danh sách nhóm đã tham gia
        log(f"🔗 Điều hướng đến: {JOINS_URL}")
        await page.goto(JOINS_URL, wait_until="domcontentloaded")
        await asyncio.sleep(5.0)

        log("📜 Đang cuộn trang xuống tận đáy để nạp hết danh sách nhóm...")
        prev_count = 0
        unchanged_count = 0
        extracted_groups = {}

        while True:
            # Thu thập nhóm đang có trên DOM
            current_batch = await page.evaluate(r"""() => {
                const links = Array.from(document.querySelectorAll('a[href*="/groups/"]'));
                const results = [];
                for (const a of links) {
                    const href = a.href;
                    if (
                        href.includes('/groups/feed/') || 
                        href.includes('/groups/discover/') || 
                        href.includes('/groups/joins/') || 
                        href.includes('/groups/create/') ||
                        href.includes('/search/')
                    ) continue;

                    const match = href.match(/https:\/\/www\.facebook\.com\/groups\/([^\/?#]+)/);
                    if (match) {
                        const groupIdOrVanity = match[1];
                        const cleanUrl = `https://www.facebook.com/groups/${groupIdOrVanity}/`;
                        
                        let name = a.innerText.trim();
                        if (!name) name = a.getAttribute('aria-label') || '';
                        
                        if (!name || name.length < 2) {
                            const parentContainer = a.closest('div[role="listitem"]') || a.parentElement?.parentElement;
                            if (parentContainer) {
                                const textSpans = Array.from(parentContainer.querySelectorAll('span')).map(s => s.innerText.trim()).filter(Boolean);
                                if (textSpans.length > 0) name = textSpans[0];
                            }
                        }

                        if (name && !name.includes('Bài viết mới') && !name.includes('Tham gia') && name.length > 2) {
                            results.push({ name: name, url: cleanUrl });
                        }
                    }
                }
                return results;
            }""")

            for item in current_batch:
                u = item["url"]
                if u not in extracted_groups:
                    extracted_groups[u] = item["name"]

            current_count = len(extracted_groups)
            log(f"📊 Đã tìm thấy: {current_count} nhóm...")

            if current_count == prev_count:
                unchanged_count += 1
                if unchanged_count >= 5:
                    log("🏁 Đã cuộn hết trang, không còn nhóm mới nào xuất hiện.")
                    break
            else:
                unchanged_count = 0
                prev_count = current_count

            await page.evaluate("window.scrollBy(0, 1500)")
            await asyncio.sleep(2.0)

        # Lưu file JSON
        final_list = [{"name": name, "url": url} for url, name in extracted_groups.items()]
        with open(OUTPUT_JSON, "w", encoding="utf-8") as f:
            json.dump(final_list, f, indent=2, ensure_ascii=False)

        # Lưu file CSV
        with open(OUTPUT_CSV, "w", encoding="utf-8-sig", newline="") as f:
            writer = csv.DictWriter(f, fieldnames=["name", "url"])
            writer.writeheader()
            for row in final_list:
                writer.writerow(row)

        log(f"🎉 HOÀN THÀNH XUẤT SẮC! Tổng cộng {len(final_list)} nhóm đã được lưu vào:")
        log(f"   📄 {OUTPUT_JSON}")
        log(f"   📄 {OUTPUT_CSV}")
        await browser.close()

if __name__ == "__main__":
    asyncio.run(main())
