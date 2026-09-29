import asyncio
import csv
import json
import os
import re
from playwright.async_api import async_playwright

ASSETS_DIR = os.path.dirname(os.path.abspath(__file__))
COOKIES_FILE = os.path.join(ASSETS_DIR, "fb_cookies.json")
OUTPUT_JSON = os.path.join(ASSETS_DIR, "facebook_joined_groups.json")
OUTPUT_CSV = os.path.join(ASSETS_DIR, "facebook_joined_groups.csv")
JOINS_URL = "https://www.facebook.com/groups/joins/?nav_source=tab"

def log(msg):
    print(msg, flush=True)

async def main():
    log("==================================================")
    log("🚀 TRÍCH XUẤT DANH SÁCH NHÓM CHO TÀI KHOẢN MỚI")
    log("==================================================")

    # 1. Đọc cookies
    with open(COOKIES_FILE, "r", encoding="utf-8") as f:
        cookies_raw = json.load(f)

    formatted_cookies = []
    for c in cookies_raw:
        cookie_obj = {
            "name": c["name"],
            "value": c["value"],
            "domain": c.get("domain", ".facebook.com"),
            "path": c.get("path", "/"),
        }
        if "secure" in c:
            cookie_obj["secure"] = c["secure"]
        if "httpOnly" in c:
            cookie_obj["httpOnly"] = c["httpOnly"]
        if "sameSite" in c and c["sameSite"] in ["Strict", "Lax", "None", "no_restriction"]:
            if c["sameSite"] == "no_restriction":
                cookie_obj["sameSite"] = "None"
            else:
                cookie_obj["sameSite"] = c["sameSite"]
        formatted_cookies.append(cookie_obj)

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
        await context.add_cookies(formatted_cookies)
        page = await context.new_page()

        # Kiểm tra phiên
        log("🔐 Đang kiểm tra tính hợp lệ của cookies mới...")
        await page.goto("https://www.facebook.com/", wait_until="domcontentloaded")
        await asyncio.sleep(4.0)

        profile_sel = page.locator('svg[aria-label="Trang cá nhân của bạn"], div[aria-label="Tài khoản của bạn"], div[aria-label="Menu"], a[href*="/me"]').first
        is_logged_in = await profile_sel.count() > 0

        # Kiểm tra nút Tiếp tục nếu có
        if not is_logged_in:
            btn_tiep_tuc = page.locator('button:has-text("Tiếp tục"), div[role="button"]:has-text("Tiếp tục"), a:has-text("Tiếp tục")').first
            if await btn_tiep_tuc.count() > 0 and await btn_tiep_tuc.is_visible():
                log("👆 Bấm nút Tiếp tục hồ sơ...")
                await btn_tiep_tuc.click()
                await asyncio.sleep(4.0)
                is_logged_in = await profile_sel.count() > 0

        if not is_logged_in:
            log(f"⚠️ Cảnh báo: Chưa nhận diện được avatar profile (URL: {page.url}). Chụp ảnh trạng thái...")
            await page.screenshot(path=os.path.join(ASSETS_DIR, "new_account_cookie_check.png"))
        else:
            log("✅ Cookies tài khoản mới hoàn toàn hợp lệ! Đang điều hướng đến trang nhóm...")

        # 2. Điều hướng đến trang danh sách nhóm đã tham gia
        log(f"🔗 Điều hướng đến: {JOINS_URL}")
        await page.goto(JOINS_URL, wait_until="domcontentloaded")
        await asyncio.sleep(5.0)

        log("📜 Đang cuộn trang xuống tận đáy để trích xuất 100% nhóm...")
        prev_count = 0
        unchanged_count = 0
        extracted_groups = {}

        for scroll_idx in range(1, 100):
            # JavaScript thu thập nhóm liên tục
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
            log(f"📊 [Vòng {scroll_idx}] Đã tìm thấy: {current_count} nhóm...")

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

        await page.screenshot(path=os.path.join(ASSETS_DIR, "groups_extracted_final.png"))

        log(f"\n==================================================")
        log(f"🎉 HOÀN THÀNH XUẤT SẮC! Tổng cộng {len(final_list)} nhóm đã được lưu:")
        log(f"   📄 JSON: {OUTPUT_JSON}")
        log(f"   📄 CSV : {OUTPUT_CSV}")
        log(f"==================================================")

        # In mẫu 5 nhóm đầu tiên
        if final_list:
            print("\n--- MẪU 5 NHÓM ĐẦU TIÊN CỦA TÀI KHOẢN MỚI ---")
            for idx, g in enumerate(final_list[:5], 1):
                print(f"  {idx}. {g['name']} ({g['url']})")

        await browser.close()

if __name__ == "__main__":
    asyncio.run(main())
