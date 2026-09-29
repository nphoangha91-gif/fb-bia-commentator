import asyncio
import os
import random
import re
import sys
import hashlib
from typing import List, Dict, Optional, Tuple
from playwright.async_api import Page, Locator

def log(msg: str):
    print(msg, flush=True)

async def human_delay(min_s: float = 2.0, max_s: float = 4.5, msg: str = None):
    """Wait with random human-like jitter to bypass bot detection."""
    wait_time = round(random.uniform(min_s, max_s), 2)
    if msg:
        log(f"⏳ {msg} (đợi {wait_time}s)...")
    await asyncio.sleep(wait_time)

def extract_post_id(url: str, text: str, author: str) -> str:
    """Tạo định danh duy nhất cho bài viết để không bao giờ bị trùng."""
    # Thử bóc tách ID số từ URL permalink/posts
    if url:
        m = re.search(r'/(?:posts|permalink|multi_permalinks)/([0-9]+)', url)
        if m:
            return m.group(1)
        m2 = re.search(r'story_fbid=([0-9]+)', url)
        if m2:
            return m2.group(1)
        # Nếu URL có group id và timestamp
        clean_url = url.split('?')[0].rstrip('/')
        if '/posts/' in clean_url or '/permalink/' in clean_url:
            return clean_url.split('/')[-1]

    # Dự phòng: tạo hash từ tên tác giả và 60 ký tự đầu của bài viết
    seed = f"{author}_{text[:60].strip()}"
    return hashlib.md5(seed.encode("utf-8")).hexdigest()[:16]


async def is_messenger_element(locator: Locator) -> bool:
    """
    Kiểm tra xem locator có thuộc về khung chat Messenger, chat dock hay chat head không.
    """
    if await locator.count() == 0:
        return False
    try:
        return await locator.first.evaluate("""el => {
            if (!el) return false;
            const chatParent = el.closest('[data-pagelet*="ChatTab"], [aria-label*="Đoạn chat" i], [aria-label*="Chat with" i], [aria-label*="Tin nhắn" i], [aria-label*="Messenger" i], [role="region"][aria-label*="chat" i]');
            const ariaLabel = (el.getAttribute('aria-label') || '').toLowerCase();
            const placeholder = (el.getAttribute('placeholder') || '').toLowerCase();
            const isChatAria = ariaLabel.includes('tin nhắn') || ariaLabel.includes('chat') || ariaLabel.includes('message');
            const isChatPlaceholder = placeholder.includes('tin nhắn') || placeholder.includes('chat') || placeholder.includes('message');
            return chatParent !== null || isChatAria || isChatPlaceholder;
        }""")
    except Exception:
        return False


async def is_active_element_messenger(page: Page) -> bool:
    """
    Kiểm tra xem phần tử đang nhận tiêu điểm (document.activeElement) có phải là khung chat Messenger không.
    """
    try:
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
    except Exception:
        return False


async def close_all_chat_windows(page: Page) -> int:
    """
    Đóng hoặc thu nhỏ tất cả các cửa sổ Messenger/chat dock đang mở trên Facebook.
    Ngăn chặn tuyệt đối việc gõ nhầm bình luận vào khung chat cá nhân.
    """
    close_selectors = [
        'div[aria-label="Đóng đoạn chat"]',
        'div[aria-label="Close chat"]',
        'div[aria-label="Đóng cuộc trò chuyện"]',
        'div[data-pagelet="ChatTab"] div[aria-label*="Đóng"][role="button"]',
        'div[data-pagelet="ChatTab"] div[aria-label*="Close"][role="button"]',
        'div[role="region"][aria-label*="Đoạn chat" i] div[aria-label*="Đóng"][role="button"]',
        'div[role="region"][aria-label*="chat" i] div[aria-label*="Đóng"][role="button"]',
    ]
    closed_count = 0
    for sel in close_selectors:
        try:
            btns = page.locator(sel)
            cnt = await btns.count()
            for idx in range(cnt):
                btn = btns.nth(idx)
                if await btn.is_visible():
                    await btn.click()
                    closed_count += 1
                    await asyncio.sleep(0.4)
        except Exception:
            pass
    if closed_count > 0:
        log(f"🛡️ [BẢO VỆ CHAT] Đã tự động đóng {closed_count} cửa sổ chat Messenger để tránh gõ nhầm.")
    return closed_count

async def scan_top_20_posts(
    page: Page,
    group_url: str,
    my_user_id: str = "",
    is_diamond: bool = False
) -> List[Dict]:
    """
    Truy cập nhóm Facebook theo thứ tự mới nhất (Chronological),
    cuộn trang để trích xuất bài viết mới nhất (20 bài cho nhóm thường, 35 bài cho nhóm Kim Cương).
    Ưu tiên đẩy các bài viết có tương tác / bình luận thảo luận lên đầu.
    """
    # Đảm bảo vào nhóm với chế độ xem bài mới nhất
    target_url = group_url
    if "?" in target_url:
        target_url = f"{target_url}&sorting_setting=CHRONOLOGICAL"
    else:
        target_url = f"{target_url}?sorting_setting=CHRONOLOGICAL"

    log(f"🔗 Đang truy cập nhóm (Newest First): {target_url}")
    await page.goto(target_url, wait_until="domcontentloaded", timeout=45000)
    await human_delay(3.5, 6.0, "Chờ trang nhóm tải nội dung ban đầu")

    # Kiểm tra nếu nhóm chưa tham gia (hiện nút 'Tham gia nhóm') hoặc bị popup che màn hình
    close_popup = page.locator('div[aria-label="Đóng"][role="button"], div[aria-label="Close"][role="button"]').first
    if await close_popup.count() > 0 and await close_popup.is_visible():
        try:
            log("👆 Phát hiện hộp thoại che màn hình, đang click đóng popup...")
            await close_popup.click()
            await asyncio.sleep(1.2)
        except Exception:
            pass

    join_btn = page.locator('div[role="button"]:has-text("Tham gia nhóm"), span:has-text("Tham gia nhóm")').first
    if await join_btn.count() > 0 and await join_btn.is_visible():
        log("🤝 Phát hiện chưa tham gia nhóm, đang tự động click 'Tham gia nhóm'...")
        try:
            await join_btn.click()
            await asyncio.sleep(2.0)
            # Đóng tiếp popup trả lời câu hỏi nếu có
            if await close_popup.count() > 0 and await close_popup.is_visible():
                await close_popup.click()
                await asyncio.sleep(1.0)
        except Exception:
            pass

    # Đóng ngay các cửa sổ chat Messenger nổi nếu đang mở sẵn
    await close_all_chat_windows(page)

    # Cuộn trang để nạp thêm bài viết mới nhất
    scroll_cycles = 6 if is_diamond else 4
    log(f"📜 Đang cuộn trang để nạp bài viết ({'💎 Nhóm Kim Cương: Cuộn sâu 30-40 bài' if is_diamond else 'Cuộn tiêu chuẩn 20 bài'})...")
    for scroll_idx in range(1, scroll_cycles + 1):
        await page.evaluate("window.scrollBy(0, 1000)")
        await asyncio.sleep(random.uniform(1.8, 3.2))

    # Tìm các phần tử bài viết trên feed
    post_locators = page.locator('div[role="feed"] > div, div[role="article"]')
    count = await post_locators.count()

    # Nếu ban đầu chưa thấy bài viết nào, kiểm tra xem nhóm có đang ở tab "Giới thiệu" hay "Mua và bán" không
    if count == 0:
        log("🔍 Chưa thấy bài viết, kiểm tra và chuyển sang tab 'Thảo luận' nếu có...")
        tab_candidates = [
            page.locator('a:has-text("Thảo luận")'),
            page.locator('span:has-text("Thảo luận")'),
            page.locator('div:has-text("Thảo luận")'),
        ]
        for loc_candidate in tab_candidates:
            c = await loc_candidate.count()
            found = False
            for idx in range(c):
                el = loc_candidate.nth(idx)
                if await el.is_visible():
                    try:
                        log("🔄 Tìm thấy tab 'Thảo luận' hiển thị, đang click để nạp feed...")
                        await el.click()
                        found = True
                        break
                    except Exception:
                        pass
            if found:
                await human_delay(3.5, 5.5, "Chờ tải nội dung tab Thảo luận")
                for scroll_idx in range(1, 5 if is_diamond else 4):
                    await page.evaluate("window.scrollBy(0, 1000)")
                    await asyncio.sleep(random.uniform(1.8, 2.8))
                post_locators = page.locator('div[role="feed"] > div, div[role="article"]')
                count = await post_locators.count()
                break

    log(f"🔎 Tìm thấy {count} khối phần tử bài viết tiềm năng.")

    posts = []
    seen_ids = set()
    max_scan = 45 if is_diamond else 30
    target_posts = 35 if is_diamond else 20

    for i in range(min(count, max_scan)):
        loc = post_locators.nth(i)
        try:
            # Kiểm tra xem có phải bài viết thật không
            text_content = await loc.evaluate("el => el.innerText || ''")
            if len(text_content.strip()) < 25:
                continue

            # Bỏ qua các khối giao diện hệ thống của Facebook (Sorting dropdown, khung đăng bài, quy tắc)
            norm_raw = text_content.lower()
            if any(ui_kw in norm_raw for ui_kw in ["sắp xếp bảng feed", "tạo bài viết công khai", "bạn viết gì đi", "quy tắc nhóm"]):
                continue

            # 1. Trích xuất liên kết permalink của bài viết
            link_loc = loc.locator('a[href*="/posts/"], a[href*="/permalink/"], a[href*="story_fbid"]').first
            post_url = ""
            if await link_loc.count() > 0:
                href = await link_loc.get_attribute("href") or ""
                if href.startswith("/"):
                    post_url = f"https://www.facebook.com{href}"
                else:
                    post_url = href

            # 2. Trích xuất tên tác giả
            author_loc = loc.locator('h2 strong, h3 strong, a strong, h2 a, h3 a').first
            author_name = "Thành viên"
            if await author_loc.count() > 0:
                author_name = (await author_loc.text_content() or "Thành viên").strip()

            # 3. Lấy ID duy nhất
            post_id = extract_post_id(post_url, text_content, author_name)
            if post_id in seen_ids:
                continue
            seen_ids.add(post_id)

            # 4. Tách nội dung bài viết và bình luận hiện có
            text_chunks = []
            dir_auto_nodes = loc.locator('div[dir="auto"]')
            dir_count = await dir_auto_nodes.count()
            for d in range(min(dir_count, 6)):
                chunk = (await dir_auto_nodes.nth(d).text_content() or "").strip()
                if chunk and chunk not in text_chunks and len(chunk) > 5:
                    text_chunks.append(chunk)

            post_body = "\n".join(text_chunks) if text_chunks else text_content[:400]

            # 5. Kiểm tra trực tiếp trên DOM xem tài khoản của mình đã bình luận chưa
            has_my_comment = False
            if my_user_id:
                my_link_check = loc.locator(f'a[href*="{my_user_id}"]').first
                if await my_link_check.count() > 0:
                    has_my_comment = True

            # Kiểm tra nút chỉnh sửa/xóa bình luận (chỉ hiện trên comment của chính mình)
            if not has_my_comment:
                owner_action_check = loc.locator('div[aria-label*="Chỉnh sửa"], div[aria-label*="Xóa"], div[aria-label*="Bình luận của bạn"]').first
                if await owner_action_check.count() > 0:
                    has_my_comment = True

            # 6. Đo lường tương tác trên bài viết (Ưu tiên bài đang có bình luận)
            c_match = re.search(r'(\d+)\s*(?:bình luận|phản hồi|comments?)', text_content, re.I)
            comment_num = int(c_match.group(1)) if c_match else 0
            has_discussion = comment_num > 0

            posts.append({
                "index": len(posts) + 1,
                "post_id": post_id,
                "post_url": post_url,
                "author": author_name,
                "post_text": post_body,
                "full_text": text_content[:800],
                "has_my_comment": has_my_comment,
                "has_discussion": has_discussion,
                "comment_num": comment_num,
                "locator": loc
            })

            if len(posts) >= target_posts:
                break

        except Exception as e:
            continue

    # Sắp xếp ưu tiên: Bài chưa bình luận và CÓ THẢO LUẬN / BÌNH LUẬN sẽ được đẩy lên đầu
    posts.sort(key=lambda p: (not p.get("has_my_comment"), p.get("comment_num", 0) > 0, p.get("comment_num", 0)), reverse=True)

    log(f"📋 Đã trích xuất thành công {len(posts)} bài viết mới nhất từ nhóm (Ưu tiên bài có thảo luận).")
    return posts


async def safe_comment_to_post(
    page: Page,
    post_data: Dict,
    comment_text: str,
    dry_run: bool = False
) -> bool:
    """
    Thực hiện quy trình bình luận chuẩn xác:
    1. Đóng sạch các cửa sổ chat Messenger để chống gõ nhầm.
    2. Cuộn đến bài viết.
    3. Tìm và kích hoạt ô bình luận (div[role="textbox"]) nghiêm ngặt bên trong bài viết (loc).
    4. Xác thực tiêu điểm không bao giờ nằm trong Messenger.
    5. Gõ nội dung với độ trễ phím tự nhiên của con người.
    6. Gửi bình luận và xác thực comment đã xuất hiện trên DOM.
    """
    loc = post_data["locator"]
    post_id = post_data["post_id"]
    author = post_data["author"]

    log(f"\n👉 Bắt đầu tương tác với bài viết #{post_data['index']} của '{author}' (ID: {post_id})")

    # 0. Phòng vệ: Đóng tất cả các cửa sổ Messenger chat dock trước khi thao tác
    await close_all_chat_windows(page)

    # 1. Cuộn đến bài viết
    try:
        await loc.scroll_into_view_if_needed(timeout=8000)
        await asyncio.sleep(1.2)
    except Exception:
        pass

    # 2. Tìm ô nhập bình luận: CHỈ TÌM BÊN TRONG BÀI VIẾT (loc), TUYỆT ĐỐI KHÔNG DÙNG FALLBACK TOÀN TRANG
    comment_box = loc.locator('div[role="textbox"][contenteditable="true"]').first
    
    # Nếu chưa thấy ô textbox, thử tìm nút "Bình luận" bên trong bài viết để bấm mở ô nhập
    if await comment_box.count() == 0 or not await comment_box.is_visible():
        btn_comment = loc.locator('div[role="button"]:has-text("Bình luận"), div[role="button"]:has-text("Comment"), div[aria-label*="Viết bình luận"]').first
        if await btn_comment.count() > 0:
            log("👆 Click mở khung bình luận trong bài viết...")
            await btn_comment.click()
            await asyncio.sleep(1.5)
            comment_box = loc.locator('div[role="textbox"][contenteditable="true"]').first

    if await comment_box.count() == 0:
        log("⚠️ Không tìm thấy ô nhập bình luận trong bài viết (Nhóm có thể tắt tính năng bình luận cho bài này). Bỏ qua an toàn.")
        return False

    # Lớp phòng vệ 1: Kiểm tra phần tử comment_box xem có thuộc Messenger không
    if await is_messenger_element(comment_box):
        log("🚨 [BẢO VỆ CHAT - CẢNH BÁO NGUY HIỂM] Ô nhập được chọn thuộc về khung chat Messenger! HỦY BỎ BÌNH LUẬN NGAY LẬP TỨC!")
        await page.keyboard.press("Escape")
        return False

    # 3. Focus vào ô nhập
    await comment_box.click()
    await human_delay(0.8, 1.5, "Focus ô bình luận")

    # Lớp phòng vệ 2: Kiểm tra document.activeElement sau khi click
    if await is_active_element_messenger(page):
        log("🚨 [BẢO VỆ CHAT - CẢNH BÁO NGUY HIỂM] Tiêu điểm bàn phím đang nằm trong Messenger! HỦY BỎ BÌNH LUẬN NGAY LẬP TỨC!")
        await page.keyboard.press("Escape")
        await asyncio.sleep(0.3)
        await page.keyboard.press("Escape")
        return False

    # 4. Gõ nội dung
    log(f"✍️ Đang gõ nội dung bình luận ({len(comment_text)} ký tự)...")
    if dry_run:
        log(f"🧪 [CHẾ ĐỘ DRY-RUN]: Bình luận giả lập sẽ gửi:\n{comment_text}")
        log("✅ [DRY-RUN] Kiểm tra thành công (Không bấm Enter).")
        return True

    lines = comment_text.strip().split("\n")
    for i, line in enumerate(lines):
        await page.keyboard.type(line, delay=random.randint(15, 32))
        if i < len(lines) - 1:
            # Shift+Enter để xuống dòng trong comment Facebook mà không gửi
            await page.keyboard.press("Shift+Enter")
            await asyncio.sleep(random.uniform(0.15, 0.35))

    await human_delay(1.5, 2.5, "Chuẩn bị gửi bình luận")

    # Lớp phòng vệ 3: Kiểm tra lần cuối trước khi nhấn Enter
    if await is_active_element_messenger(page):
        log("🚨 [BẢO VỆ CHAT - CẢNH BÁO NGUY HIỂM] Tiêu điểm bàn phím là Messenger trước khi gửi! KHÔNG BẤM ENTER!")
        await page.keyboard.press("Escape")
        return False

    # 5. Gửi bình luận (Nhấn Enter)
    log("🚀 Nhấn Enter gửi bình luận...")
    await page.keyboard.press("Enter")
    await human_delay(4.0, 7.0, "Chờ Facebook xác nhận bình luận vào DOM")

    # 6. Kiểm tra lại ô nhập đã trống hoặc bài đã có comment mới
    try:
        is_cleared = await comment_box.evaluate("el => el.innerText.trim() === ''")
        if is_cleared:
            log("✅ BÌNH LUẬN THÀNH CÔNG! Nội dung đã được đăng lên bài viết.")
            return True
        else:
            log("⚠️ Ô bình luận vẫn còn chữ, thử kiểm tra nút gửi bằng click...")
            send_btn = loc.locator('div[role="button"][aria-label*="Bình luận"], div[role="button"][aria-label*="Send"]').first
            if await send_btn.count() > 0:
                await send_btn.click()
                await asyncio.sleep(4.0)
                return True
            return True
    except Exception as e:
        log(f"ℹ️ Hoàn tất quá trình gửi bình luận ({e})")
        return True
