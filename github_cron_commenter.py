import asyncio
import json
import os
import random
import sys
import datetime
from typing import Dict, List, Optional
from playwright.async_api import async_playwright
from comment_workflow_core import scan_top_20_posts, safe_comment_to_post, human_delay, log
from onnx_comment_engine import ONNXCommentEngine

ASSETS_DIR = os.path.dirname(os.path.abspath(__file__))
GROUPS_FILE = os.path.join(ASSETS_DIR, "facebook_joined_groups.json")
PROGRESS_FILE = os.path.join(ASSETS_DIR, "commented_history.json")
COOKIES_FILE = os.path.join(ASSETS_DIR, "fb_cookies.json")
ENV_FILE = os.path.join(ASSETS_DIR, "env.txt")
DIAMOND_GROUPS_FILE = os.path.join(ASSETS_DIR, "diamond_groups.json")

# Đọc cấu hình từ biến môi trường
TOTAL_GROUPS_LIMIT = int(os.environ.get("TOTAL_GROUPS_LIMIT", "10"))
MAX_COMMENTS_PER_GROUP = int(os.environ.get("MAX_COMMENTS_PER_GROUP", "2"))
DIAMOND_COMMENTS_MIN = int(os.environ.get("DIAMOND_COMMENTS_MIN", "10"))
DIAMOND_COMMENTS_MAX = int(os.environ.get("DIAMOND_COMMENTS_MAX", "15"))
NORMAL_COMMENTS_MIN = int(os.environ.get("NORMAL_COMMENTS_MIN", "1"))
NORMAL_COMMENTS_MAX = int(os.environ.get("NORMAL_COMMENTS_MAX", "2"))
DRY_RUN = os.environ.get("DRY_RUN", "false").lower() == "true"
TEST_GROUP_URL = os.environ.get("TEST_GROUP_URL", "").strip()
FB_COOKIES_JSON = os.environ.get("FB_COOKIES_JSON", "")
FB_USERNAME = os.environ.get("FB_USERNAME", "").strip()
FB_PASSWORD = os.environ.get("FB_PASSWORD", "").strip()

def load_diamond_group_urls() -> set:
    urls = set()
    if os.path.exists(DIAMOND_GROUPS_FILE):
        try:
            with open(DIAMOND_GROUPS_FILE, "r", encoding="utf-8") as f:
                d_data = json.load(f)
                urls = {g["url"] for g in d_data if g.get("url")}
        except Exception:
            pass
    return urls

if not FB_USERNAME or not FB_PASSWORD:
    if os.path.exists(ENV_FILE):
        try:
            with open(ENV_FILE, "r", encoding="utf-8") as f:
                lines = [l.strip() for l in f.readlines() if l.strip()]
                if len(lines) >= 2:
                    FB_USERNAME = FB_USERNAME or lines[0]
                    FB_PASSWORD = FB_PASSWORD or lines[1]
        except Exception:
            pass

def load_history() -> Dict:
    if os.path.exists(PROGRESS_FILE):
        try:
            with open(PROGRESS_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            pass
    return {"total_commented": 0, "last_updated": None, "records": {}}

def save_history(history: Dict):
    history["total_commented"] = len(history.get("records", {}))
    history["last_updated"] = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    with open(PROGRESS_FILE, "w", encoding="utf-8") as f:
        json.dump(history, f, indent=2, ensure_ascii=False)

async def main():
    log("==================================================")
    log("🤖 FACEBOOK ONNX CONTEXTUAL COMMENT AGENT (NO-SPAM)")
    log(f"⚙️  Chế độ: {'DRY RUN (Chỉ test, KHÔNG gửi thật)' if DRY_RUN else 'LIVE COMMENT (Bình luận thật)'}")
    log(f"📦 Số nhóm mục tiêu ca này: {TOTAL_GROUPS_LIMIT} nhóm")
    log(f"🎯 Giới hạn bình luận mỗi nhóm: tối đa {MAX_COMMENTS_PER_GROUP} bài")
    log("==================================================")

    # 1. Khởi tạo ONNX Engine
    comment_engine = ONNXCommentEngine()
    history = load_history()
    records = history.setdefault("records", {})
    visited_groups = set(history.setdefault("visited_groups", []))
    diamond_urls = load_diamond_group_urls()
    log(f"🕒 Tổng số bài viết đã bình luận từ trước: {len(records)} bài")
    log(f"📋 Số nhóm đã duyệt qua trong chu kỳ này: {len(visited_groups)} nhóm")
    log(f"💎 Tổng số Nhóm Kim Cương nhận diện được: {len(diamond_urls)} nhóm")

    # 2. Lấy danh sách nhóm theo cơ chế Round-Robin (Quay vòng thông minh)
    if TEST_GROUP_URL:
        target_groups = [{"name": "Nhóm test chỉ định", "url": TEST_GROUP_URL}]
    else:
        if not os.path.exists(GROUPS_FILE):
            log(f"❌ Không tìm thấy file {GROUPS_FILE}!")
            sys.exit(1)
        with open(GROUPS_FILE, "r", encoding="utf-8") as f:
            all_groups = json.load(f)

        pending_groups = [g for g in all_groups if g["url"] not in visited_groups]
        if not pending_groups:
            log(f"🎉 ĐÃ DUYỆT HẾT TOÀN BỘ {len(all_groups)} NHÓM TRONG DANH SÁCH! Tự động reset chu kỳ để quay vòng mới.")
            visited_groups.clear()
            history["visited_groups"] = []
            save_history(history)
            pending_groups = all_groups

        target_groups = pending_groups[:TOTAL_GROUPS_LIMIT]

    log(f"🎯 Danh sách nhóm sẽ quét trong ca này ({len(target_groups)} nhóm):")
    for idx, g in enumerate(target_groups, 1):
        log(f"  {idx}. {g['name']} ({g['url']})")

    # 3. Chuẩn bị Cookies
    cookies = []
    if FB_COOKIES_JSON:
        try:
            cookies = json.loads(FB_COOKIES_JSON)
            log("🍪 Đã nạp cookies từ GitHub Secret.")
        except Exception as e:
            log(f"❌ Lỗi giải mã cookies secret: {e}")
            sys.exit(1)
    elif os.path.exists(COOKIES_FILE):
        with open(COOKIES_FILE, "r", encoding="utf-8") as f:
            cookies = json.load(f)
            log("🍪 Đã nạp cookies từ file fb_cookies.json cục bộ.")
    else:
        log("❌ Không tìm thấy file cookies!")
        sys.exit(1)

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

    # 4. Khởi chạy Playwright Browser
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
            viewport={"width": 1280, "height": 850},
            user_agent="Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/128.0.0.0 Safari/537.36",
            locale="vi-VN",
            timezone_id="Asia/Ho_Chi_Minh"
        )
        await context.add_cookies(formatted_cookies)
        page = await context.new_page()

        # Kiểm tra phiên đăng nhập
        log("🔐 Kiểm tra phiên làm việc Facebook...")
        await page.goto("https://www.facebook.com/", wait_until="domcontentloaded")
        await asyncio.sleep(4.0)

        profile_sel = page.locator('svg[aria-label="Trang cá nhân của bạn"], div[aria-label="Tài khoản của bạn"], div[aria-label="Menu"], a[href*="/me"]').first
        is_logged_in = await profile_sel.count() > 0

        if not is_logged_in:
            log("⚠️ Phiên đăng nhập cần xác thực. Đang kích hoạt cơ chế tự động khôi phục / đăng nhập...")
            # Trường hợp 1: Nhấp vào hồ sơ 'Tran Minh' nếu có danh sách chuyển đổi hồ sơ
            profile_cards = [
                page.locator('div[role="button"]:has-text("Tran Minh"), span:has-text("Tran Minh"), div:has(> div > span:has-text("Tran Minh"))').first,
            ]
            for p_card in profile_cards:
                if await p_card.count() > 0 and await p_card.is_visible():
                    log("👆 Tìm thấy thẻ hồ sơ 'Tran Minh', đang click để mở ô nhập mật khẩu...")
                    try:
                        await p_card.click()
                        await asyncio.sleep(2.0)
                        break
                    except Exception:
                        pass

            # Trường hợp 2: Nút Tiếp tục (One-click login đơn lẻ)
            btn_tiep_tuc = page.locator('button:has-text("Tiếp tục"), div[role="button"]:has-text("Tiếp tục"), a:has-text("Tiếp tục")').first
            if await btn_tiep_tuc.count() > 0 and await btn_tiep_tuc.is_visible():
                log("👆 Tìm thấy nút 'Tiếp tục' hồ sơ cá nhân, đang click...")
                try:
                    await btn_tiep_tuc.click()
                    await asyncio.sleep(2.0)
                except Exception:
                    pass

            # Trường hợp 3: Điền tên đăng nhập nếu có ô email
            email_input = page.locator('input#email, input[name="email"]').first
            if await email_input.count() > 0 and await email_input.is_visible() and FB_USERNAME:
                log("📝 Đang điền tên đăng nhập...")
                await email_input.fill(FB_USERNAME)
                await asyncio.sleep(1.0)

            # Điền mật khẩu
            pass_input = page.locator('input[type="password"]').first
            if await pass_input.count() > 0 and await pass_input.is_visible() and FB_PASSWORD:
                log("🔑 Đang điền mật khẩu đăng nhập...")
                await pass_input.fill(FB_PASSWORD)
                await asyncio.sleep(1.0)
                await page.keyboard.press("Enter")
                log("⏳ Đã gửi mật khẩu (Enter), chờ chuyển vào trang chủ...")
                await asyncio.sleep(8.0)

            # Kiểm tra nút submit nếu chưa đăng nhập
            submit_btn = page.locator('button[type="submit"], div[role="button"]:has-text("Đăng nhập")').first
            if await submit_btn.count() > 0 and await submit_btn.is_visible():
                try:
                    await submit_btn.click()
                    await asyncio.sleep(8.0)
                except Exception:
                    pass

            is_logged_in = await profile_sel.count() > 0
            if is_logged_in:
                log("🎉 Đăng nhập thành công!")
            else:
                log("⚠️ Cảnh báo: Chưa xác nhận được avatar đăng nhập, tiếp tục thử nghiệm...")
        else:
            log("✅ Phiên đăng nhập hợp lệ!")

        # Kiểm tra xem tài khoản hiện tại có phải Tran Minh không
        current_avatar = page.locator('div[aria-label="Tài khoản của bạn"], div[aria-label="Menu"]').first
        if await current_avatar.count() > 0:
            user_text = await page.evaluate("() => document.body.innerText.slice(0, 500)")
            if "An Tâm" in user_text and "Tran Minh" not in user_text:
                log("⚠️ Phát hiện đang đăng nhập nhầm vào hồ sơ 'An Tâm'! Đang đổi sang tài khoản 'Tran Minh'...")
                await page.goto("https://www.facebook.com/login/", wait_until="domcontentloaded")
                await asyncio.sleep(2.0)
                email_input = page.locator('input#email, input[name="email"]').first
                if await email_input.count() > 0 and FB_USERNAME:
                    await email_input.fill(FB_USERNAME)
                    await asyncio.sleep(1.0)
                    pass_input = page.locator('input[type="password"]').first
                    if await pass_input.count() > 0 and FB_PASSWORD:
                        await pass_input.fill(FB_PASSWORD)
                        await asyncio.sleep(1.0)
                        await page.keyboard.press("Enter")
                        await asyncio.sleep(8.0)

        # Trích xuất user ID của tài khoản
        my_user_id = next((c["value"] for c in cookies if c["name"] == "c_user"), "")
        log(f"🆔 ID tài khoản Facebook hiện tại: {my_user_id or 'Không xác định'}")

        total_new_comments = 0

        # 5. Duyệt qua từng nhóm
        for g_idx, group in enumerate(target_groups, 1):
            group_url = group["url"]
            group_name = group["name"]

            # Nhận diện Nhóm Kim Cương (qua database diamond_groups.json hoặc từ khóa thương hiệu hot)
            norm_name = group_name.lower()
            is_diamond = (
                group_url in diamond_urls or
                any(brand in norm_name for brand in ["fury", "mezz", "jflowers", "way cues", "thanh lý gậy bi a hà nội", "cuetec", "peri cues", "chợ thanh lý gậy bi a", "săn cơ bida"])
            )

            # Xác định chỉ tiêu bình luận: 10 - 15 bài cho Kim Cương, 1 - 2 bài cho Nhóm thường
            if is_diamond:
                target_comment_limit = random.randint(DIAMOND_COMMENTS_MIN, DIAMOND_COMMENTS_MAX)
                tier_badge = "💎 NHÓM KIM CƯƠNG (DIAMOND)"
            else:
                target_comment_limit = random.randint(NORMAL_COMMENTS_MIN, NORMAL_COMMENTS_MAX)
                tier_badge = "⚪ NHÓM TIÊU CHUẨN (NORMAL)"

            log(f"\n==================================================")
            log(f"[{g_idx}/{len(target_groups)}] 🌐 ĐANG QUÉT: {group_name}")
            log(f"🏷️  Phân loại: {tier_badge}")
            log(f"🎯 Chỉ tiêu bình luận ca này: {target_comment_limit} bài viết mới chưa tương tác")
            log(f"🔗 URL: {group_url}")
            log(f"==================================================")

            try:
                # Quét bài viết mới nhất (nạp sâu 30-40 bài cho nhóm Kim Cương)
                posts = await scan_top_20_posts(page, group_url, my_user_id=my_user_id, is_diamond=is_diamond)
                if not posts:
                    log("⚠️ Không trích xuất được bài viết nào từ nhóm này. Tiếp tục nhóm sau...")
                    if not TEST_GROUP_URL and not DRY_RUN:
                        visited_groups.add(group_url)
                        history["visited_groups"] = list(visited_groups)
                        save_history(history)
                    continue

                group_comment_count = 0

                for post in posts:
                    p_id = post["post_id"]
                    p_author = post["author"]
                    p_text = post["post_text"]
                    p_full = post["full_text"]

                    # 1. Kiểm tra nếu chính mình đã bình luận trên DOM
                    if post.get("has_my_comment"):
                        log(f"⏭️ [ĐÃ BÌNH LUẬN TRÊN DOM] Phát hiện comment của chính mình trên bài của '{p_author}' (ID: {p_id}). Bỏ qua an toàn.")
                        continue

                    # 2. Kiểm tra trùng lặp lịch sử local
                    if p_id in records:
                        log(f"⏭️ [ĐÃ BÌNH LUẬN TRONG LỊCH SỬ] Bỏ qua bài của '{p_author}' (ID: {p_id})")
                        continue

                    # Sử dụng ONNX Engine để đọc hiểu ngữ cảnh theo 3 tình huống
                    analysis = comment_engine.generate_contextual_comment(
                        post_text=p_text,
                        comments_text=p_full,
                        post_id=p_id,
                        author_name=p_author
                    )

                    if not analysis["should_comment"]:
                        log(f"🚫 [BỎ QUA - CHỐNG SPAM] Bài của '{p_author}': {analysis.get('reason', 'Không phù hợp')}")
                        continue

                    log(f"\n💡 [PHÁT HIỆN CƠ HỘI PHÙ HỢP]:")
                    log(f"   👤 Tác giả: {p_author}")
                    log(f"   📝 Tóm tắt bài: {p_text[:120].strip()}...")
                    log(f"   📌 Tình huống: {analysis['situation']}")
                    log(f"   🎯 Khớp sản phẩm: {analysis['matched_product']}")
                    log(f"   💬 Lời thoại đề xuất:\n   \"{analysis['comment_text']}\"")

                    # Thực hiện bình luận
                    success = await safe_comment_to_post(
                        page=page,
                        post_data=post,
                        comment_text=analysis["comment_text"],
                        dry_run=DRY_RUN
                    )

                    if success:
                        group_comment_count += 1
                        total_new_comments += 1

                        # Ghi nhận vào lịch sử
                        if not DRY_RUN:
                            records[p_id] = {
                                "post_id": p_id,
                                "post_url": post["post_url"],
                                "group_url": group_url,
                                "group_name": group_name,
                                "author": p_author,
                                "situation": analysis["situation"],
                                "matched_product": analysis["matched_product"],
                                "comment_text": analysis["comment_text"],
                                "commented_at": datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                            }
                            save_history(history)

                        # Chụp ảnh bằng chứng
                        proof_path = os.path.join(ASSETS_DIR, f"proof_comment_g{g_idx}_p{group_comment_count}.png")
                        try:
                            await page.screenshot(path=proof_path)
                            log(f"📸 Đã lưu ảnh bằng chứng: {proof_path}")
                        except Exception:
                            pass

                        # Đã đủ chỉ tiêu cho nhóm này chưa?
                        if group_comment_count >= target_comment_limit:
                            log(f"🎯 Đã đạt chỉ tiêu {target_comment_limit} bình luận cho nhóm ({tier_badge}). Chuyển nhóm tiếp theo...")
                            break

                        # Giãn cách giữa 2 bình luận trong cùng 1 nhóm (25s - 45s)
                        await human_delay(25.0, 45.0, "Giãn cách an toàn chống spam giữa 2 bình luận")

                # Ghi nhận nhóm đã hoàn thành trong chu kỳ này
                if not TEST_GROUP_URL and not DRY_RUN:
                    visited_groups.add(group_url)
                    history["visited_groups"] = list(visited_groups)
                    save_history(history)

            except Exception as e:
                log(f"⚠️ Lỗi khi quét nhóm {group_name}: {e}")

            # Giãn cách an toàn giữa 2 nhóm (35s - 60s)
            if g_idx < len(target_groups):
                await human_delay(35.0, 60.0, "Giãn cách an toàn chuyển sang nhóm tiếp theo")

        log(f"\n==================================================")
        log(f"🏁 TỔNG KẾT CA NÀY: Đã gửi thành công {total_new_comments} bình luận chuẩn ngữ cảnh!")
        log(f"📊 Tổng số bài viết đã tương tác trong lịch sử: {len(records)} bài.")
        log(f"==================================================")
        await browser.close()

if __name__ == "__main__":
    asyncio.run(main())
