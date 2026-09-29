import asyncio
import json
import os
import sys
import re
import datetime
from playwright.async_api import async_playwright

ASSETS_DIR = os.path.dirname(os.path.abspath(__file__))
COOKIES_FILE = os.path.join(ASSETS_DIR, "fb_cookies.json")
OUTPUT_FILE = os.path.join(ASSETS_DIR, "inspected_top_20_posts.json")

def log(msg: str):
    print(msg, flush=True)

async def inspect_group(group_url: str, target_count: int = 20):
    log(f"==================================================")
    log(f"🔍 BẮT ĐẦU SOI DOM NHÓM FACEBOOK: {group_url}")
    log(f"🎯 Mục tiêu: Trích xuất {target_count} bài viết mới nhất + toàn bộ comments")
    log(f"==================================================")

    # 1. Đọc cookies
    if not os.path.exists(COOKIES_FILE):
        log(f"❌ Không tìm thấy file {COOKIES_FILE}")
        return

    with open(COOKIES_FILE, "r", encoding="utf-8") as f:
        cookies = json.load(f)

    formatted_cookies = []
    for c in cookies:
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
        if "sameSite" in c and c["sameSite"] in ["Strict", "Lax", "None"]:
            cookie_obj["sameSite"] = c["sameSite"]
        formatted_cookies.append(cookie_obj)

    async with async_playwright() as p:
        browser = await p.chromium.launch(
            headless=True,
            args=[
                "--disable-blink-features=AutomationControlled",
                "--no-sandbox",
                "--disable-setuid-sandbox",
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

        # Đảm bảo vào nhóm với chế độ bài viết mới nhất (CHRONOLOGICAL)
        target_group_url = group_url
        if "?" in target_group_url:
            target_group_url = f"{target_group_url}&sorting_setting=CHRONOLOGICAL"
        else:
            target_group_url = f"{target_group_url}?sorting_setting=CHRONOLOGICAL"

        log(f"🌐 Điều hướng đến URL nhóm: {target_group_url}")
        await page.goto(target_group_url, wait_until="domcontentloaded", timeout=60000)
        await asyncio.sleep(5.0)

        # Chụp ảnh trạng thái ban đầu
        await page.screenshot(path=os.path.join(ASSETS_DIR, "dom_inspection_initial.png"))

        # Kiểm tra xem có bị redirect sang login không
        current_url = page.url
        if "login" in current_url:
            log("⚠️ Bị chuyển hướng sang trang đăng nhập, cookies có thể cần cập nhật lại.")
            await browser.close()
            return

        log("✅ Đã vào nhóm thành công. Bắt đầu cuộn nạp dữ liệu và soi cấu trúc DOM...")

        # Mở rộng các nút "Xem thêm" (See more) để lấy đầy đủ văn bản bài viết
        async def expand_see_more_buttons():
            try:
                see_more_btns = page.locator('div[role="button"]:has-text("Xem thêm"), div[role="button"]:has-text("See more")')
                c = await see_more_btns.count()
                for i in range(min(c, 10)):
                    try:
                        if await see_more_btns.nth(i).is_visible():
                            await see_more_btns.nth(i).click(timeout=1000)
                            await asyncio.sleep(0.3)
                    except Exception:
                        pass
            except Exception:
                pass

        # Quá trình cuộn và trích xuất DOM lặp lại cho đến khi đủ 20 bài
        extracted_posts = []
        seen_ids = set()

        scroll_attempts = 0
        max_scroll_attempts = 15

        while len(extracted_posts) < target_count and scroll_attempts < max_scroll_attempts:
            scroll_attempts += 1
            log(f"📜 [Lần cuộn {scroll_attempts}/{max_scroll_attempts}] Đang quét các khối bài viết trên DOM...")

            await expand_see_more_buttons()

            # Trích xuất dữ liệu trực tiếp bằng JavaScript trong ngữ cảnh trang (chính xác và không bị lag)
            dom_posts_data = await page.evaluate(r'''() => {
                const results = [];
                // Tìm vùng feed
                const feed = document.querySelector('div[role="feed"]');
                const postElements = feed ? Array.from(feed.children) : Array.from(document.querySelectorAll('div[role="article"]'));

                for (const el of postElements) {
                    // Kiểm tra xem có phải khối bài viết không (bỏ qua header nhóm, khung đăng bài)
                    const text = el.innerText || '';
                    if (text.length < 20) continue;

                    // 1. Tìm tác giả
                    let author = "Thành viên";
                    const authorEl = el.querySelector('h2 strong, h3 strong, a strong, h2 a, h3 a');
                    if (authorEl) {
                        author = authorEl.innerText.trim();
                    }

                    // 2. Tìm liên kết bài viết / permalink
                    let postUrl = "";
                    let postId = "";
                    const linkEl = el.querySelector('a[href*="/posts/"], a[href*="/permalink/"], a[href*="story_fbid"]');
                    if (linkEl) {
                        postUrl = linkEl.getAttribute('href') || '';
                        if (postUrl.startsWith('/')) {
                            postUrl = 'https://www.facebook.com' + postUrl;
                        }
                    }

                    // Trích xuất ID số
                    if (postUrl) {
                        const m = postUrl.match(/(?:posts|permalink|multi_permalinks)\/([0-9]+)/);
                        if (m) postId = m[1];
                        const m2 = postUrl.match(/story_fbid=([0-9]+)/);
                        if (m2) postId = m2[1];
                    }
                    if (!postId) {
                        // Tạo hash từ author + 40 ký tự đầu
                        postId = author + '_' + text.substring(0, 40).replace(/\s+/g, '_');
                    }

                    // 3. Trích xuất nội dung bài viết (Caption / Body)
                    const dirNodes = Array.from(el.querySelectorAll('div[dir="auto"]'));
                    let bodyTexts = [];
                    for (const d of dirNodes) {
                        // Bỏ qua nếu node này nằm trong phần bình luận
                        if (d.closest('ul') || d.closest('div[aria-label*="Bình luận"]') || d.closest('div[aria-label*="Comment"]')) {
                            continue;
                        }
                        const t = d.innerText ? d.innerText.trim() : '';
                        if (t.length > 5 && !bodyTexts.includes(t)) {
                            bodyTexts.push(t);
                        }
                    }
                    const postContent = bodyTexts.join('\n');

                    // 4. Trích xuất các bình luận đã có trong bài viết
                    const comments = [];
                    // Tìm các khối comment
                    const commentNodes = el.querySelectorAll('div[role="article"], ul > li, div[aria-label*="Bình luận của"]');
                    for (const cNode of commentNodes) {
                        const cText = cNode.innerText ? cNode.innerText.trim() : '';
                        if (cText.length < 3) continue;

                        let cAuthor = "Người bình luận";
                        const cAuthorEl = cNode.querySelector('span[dir="auto"] strong, a[role="link"] strong, a[role="link"]');
                        if (cAuthorEl) {
                            cAuthor = cAuthorEl.innerText.trim();
                        }

                        // Lấy nội dung comment
                        const cContentEls = cNode.querySelectorAll('div[dir="auto"], span[dir="auto"]');
                        let cBody = "";
                        for (const cb of cContentEls) {
                            const ct = cb.innerText ? cb.innerText.trim() : '';
                            if (ct && ct !== cAuthor && ct.length > cBody.length) {
                                cBody = ct;
                            }
                        }

                        if (!cBody) cBody = cText;

                        comments.push({
                            "comment_author": cAuthor,
                            "comment_text": cBody
                        });
                    }

                    // 5. Kiểm tra thời gian đăng bài
                    let timeText = "";
                    const timeEl = el.querySelector('a[href*="/posts/"] span, a[href*="/permalink/"] span, span[id*="jsc_"]');
                    if (timeEl) {
                        timeText = timeEl.innerText ? timeEl.innerText.trim() : '';
                    }

                    results.push({
                        "post_id": postId,
                        "post_url": postUrl,
                        "author": author,
                        "time_text": timeText,
                        "post_content": postContent || text.substring(0, 300),
                        "comments_count": comments.length,
                        "comments": comments.slice(0, 10),
                        "raw_text_snippet": text.substring(0, 400)
                    });
                }
                return results;
            }''')

            for p_data in dom_posts_data:
                pid = p_data["post_id"]
                if pid not in seen_ids and len(p_data["post_content"].strip()) > 10:
                    seen_ids.add(pid)
                    extracted_posts.append(p_data)
                    log(f"  [{len(extracted_posts)}/{target_count}] Đã bắt được bài của '{p_data['author']}' (ID: {pid}) - {len(p_data['comments'])} comments")

                if len(extracted_posts) >= target_count:
                    break

            if len(extracted_posts) < target_count:
                # Cuộn trang mượt mà để nạp bài tiếp theo
                await page.evaluate("window.scrollBy(0, 1200)")
                await asyncio.sleep(2.5)

        # Chụp ảnh sau khi trích xuất xong
        await page.screenshot(path=os.path.join(ASSETS_DIR, "dom_inspection_final.png"))

        # Lưu toàn bộ dữ liệu ra file JSON
        output_data = {
            "group_url": group_url,
            "inspected_at": datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "total_posts_extracted": len(extracted_posts),
            "posts": extracted_posts
        }

        with open(OUTPUT_FILE, "w", encoding="utf-8") as f:
            json.dump(output_data, f, indent=2, ensure_ascii=False)

        log(f"\n==================================================")
        log(f"🎉 HOÀN THÀNH SOI DOM: Đã trích xuất {len(extracted_posts)} bài viết mới nhất!")
        log(f"💾 File dữ liệu chi tiết đã lưu tại: {OUTPUT_FILE}")
        log(f"==================================================")

        # In mẫu 3 bài đầu tiên ra console để xem ngay lập tức
        print("\n--- MẪU 3 BÀI VIẾT ĐẦU TIÊN TRÍCH XUẤT TỪ LIVE DOM ---")
        for idx, p_sample in enumerate(extracted_posts[:3], 1):
            print(f"\n[BÀI #{idx}] Tác giả: {p_sample['author']} | URL: {p_sample['post_url']}")
            print(f"📝 Nội dung bài viết:\n{p_sample['post_content'][:200]}...")
            print(f"💬 Số bình luận bắt được: {len(p_sample['comments'])}")
            for c_idx, c in enumerate(p_sample['comments'][:3], 1):
                print(f"   └─ [{c_idx}] {c['comment_author']}: {c['comment_text']}")
            print("-" * 60)

        await browser.close()

if __name__ == "__main__":
    test_group = sys.argv[1] if len(sys.argv) > 1 else "https://www.facebook.com/groups/howcues.vn/"
    asyncio.run(inspect_group(test_group, target_count=20))
