#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
=============================================================================
DIAMOND GROUPS EVALUATOR & FILTER TOOL (Facebook Billiard Ecosystem)
=============================================================================
Công cụ tự động quét, đo lường tương tác và lọc danh sách Nhóm Kim Cương:
- Đo lường số bình luận thực tế (Comment Density)
- Đo lường lượt cảm xúc (Reactions)
- Đo lường độ tươi mới của bài viết (Post Recency)
- Tính điểm tiềm năng (Diamond Score: 0 - 100)
- Tự động lưu tiến độ (Resumable) sau mỗi nhóm
- Xuất file diamond_groups.json và báo cáo DIAMOND_GROUPS_REPORT.md
=============================================================================
"""

import os
import sys
import json
import time
import re
import random
import asyncio
import argparse
from typing import List, Dict, Any
from playwright.async_api import async_playwright, Page, BrowserContext

ROOT_DIR = os.path.dirname(os.path.abspath(__file__))
COOKIES_FILE = os.path.join(ROOT_DIR, "fb_cookies.json")
GROUPS_FILE = os.path.join(ROOT_DIR, "facebook_joined_groups.json")
PROGRESS_FILE = os.path.join(ROOT_DIR, "diamond_evaluation_progress.json")
OUTPUT_DIAMOND_FILE = os.path.join(ROOT_DIR, "diamond_groups.json")
REPORT_MD_FILE = os.path.join(ROOT_DIR, "DIAMOND_GROUPS_REPORT.md")

def log(msg: str):
    timestamp = time.strftime("[%Y-%m-%d %H:%M:%S]")
    print(f"{timestamp} {msg}", flush=True)

def load_cookies() -> List[Dict]:
    if not os.path.exists(COOKIES_FILE):
        log(f"❌ Không tìm thấy file {COOKIES_FILE}!")
        sys.exit(1)
    with open(COOKIES_FILE, "r", encoding="utf-8") as f:
        raw_cookies = json.load(f)

    formatted = []
    for c in raw_cookies:
        obj = {
            "name": c["name"],
            "value": c["value"],
            "domain": c.get("domain", ".facebook.com"),
            "path": c.get("path", "/"),
        }
        if "secure" in c: obj["secure"] = c["secure"]
        if "httpOnly" in c: obj["httpOnly"] = c["httpOnly"]
        if "sameSite" in c and c["sameSite"] in ["Strict", "Lax", "None"]:
            obj["sameSite"] = c["sameSite"]
        formatted.append(obj)
    return formatted

def load_progress() -> Dict[str, Dict]:
    if os.path.exists(PROGRESS_FILE):
        try:
            with open(PROGRESS_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            pass
    return {}

def save_progress(progress: Dict[str, Dict]):
    with open(PROGRESS_FILE, "w", encoding="utf-8") as f:
        json.dump(progress, f, indent=2, ensure_ascii=False)

def calculate_diamond_score(metrics: Dict) -> Dict:
    """
    Tính điểm tiềm năng từ 0 - 100 dựa trên:
    - Comment Score (max 40 pts)
    - Reaction Score (max 20 pts)
    - Recency Score (max 25 pts)
    - Post Volume & Discussion (max 15 pts)
    """
    total_comments = metrics.get("total_comments", 0)
    total_reactions = metrics.get("total_reactions", 0)
    valid_posts = metrics.get("valid_posts", 0)
    newest_recency_minutes = metrics.get("newest_recency_minutes", 99999)
    active_posts_count = metrics.get("active_posts_count", 0)

    # 1. Điểm bình luận (Mật độ khách hỏi mua/trao đổi - Trọng số cao nhất 40)
    avg_comments = (total_comments / valid_posts) if valid_posts > 0 else 0
    comment_pts = min(40.0, (total_comments * 3.0) + (avg_comments * 5.0))

    # 2. Điểm cảm xúc / lượt xem (Trọng số 20)
    avg_reactions = (total_reactions / valid_posts) if valid_posts > 0 else 0
    reaction_pts = min(20.0, (total_reactions * 1.5) + (avg_reactions * 2.0))

    # 3. Điểm tươi mới bài viết (Trọng số 25)
    recency_pts = 0.0
    if newest_recency_minutes <= 60:
        recency_pts = 25.0
    elif newest_recency_minutes <= 360: # 6 hours
        recency_pts = 20.0
    elif newest_recency_minutes <= 1440: # 24 hours
        recency_pts = 15.0
    elif newest_recency_minutes <= 4320: # 3 days
        recency_pts = 5.0
    else:
        recency_pts = 0.0

    # 4. Tỷ lệ bài viết có tương tác (Trọng số 15)
    interaction_pts = min(15.0, active_posts_count * 3.0)

    total_score = round(comment_pts + reaction_pts + recency_pts + interaction_pts, 1)

    # Xếp hạng Tier
    if total_score >= 35.0 or total_comments >= 6 or (newest_recency_minutes <= 60 and total_comments >= 3):
        tier = "DIAMOND"
    elif total_score >= 15.0 or valid_posts >= 2:
        tier = "NORMAL"
    else:
        tier = "LOW_ACTIVITY"

    if valid_posts == 0 or metrics.get("is_blocked"):
        tier = "DEAD_OR_BLOCKED"
        total_score = 0.0

    return {
        "score": total_score,
        "tier": tier,
        "avg_comments": round(avg_comments, 1),
        "avg_reactions": round(avg_reactions, 1),
    }

async def evaluate_single_group(page: Page, group: Dict) -> Dict:
    url = group["url"]
    name = group["name"].split("\n")[0].strip()

    result = {
        "name": name,
        "url": url,
        "status": "OK",
        "valid_posts": 0,
        "total_comments": 0,
        "total_reactions": 0,
        "total_shares": 0,
        "active_posts_count": 0,
        "newest_recency_str": "Không xác định",
        "newest_recency_minutes": 99999,
        "is_blocked": False,
    }

    try:
        await page.goto(url, wait_until="domcontentloaded", timeout=30000)
        await asyncio.sleep(3.0)

        content = await page.content()
        if "Bạn hiện không xem được nội dung này" in content:
            result["status"] = "BLOCKED_OR_DELETED"
            result["is_blocked"] = True
            return result

        # Tự đóng popup nếu có
        close_btn = page.locator('div[aria-label="Đóng"], div[aria-label="Close"], svg[aria-label="Đóng"]').first
        if await close_btn.count() > 0 and await close_btn.is_visible():
            try: await close_btn.click()
            except Exception: pass

        # Cuộn 2 lần để nạp top 10 bài viết
        for _ in range(2):
            await page.evaluate("window.scrollBy(0, 1000)")
            await asyncio.sleep(1.2)

        post_locs = page.locator('div[role="feed"] > div, div[role="article"]')
        count = await post_locs.count()

        # Kiểm tra nếu chưa nạp được feed thì bấm tab Thảo luận
        if count == 0:
            tab = page.locator('a:has-text("Thảo luận"), span:has-text("Thảo luận")').first
            if await tab.count() > 0 and await tab.is_visible():
                try:
                    await tab.click()
                    await asyncio.sleep(3.0)
                    await page.evaluate("window.scrollBy(0, 1000)")
                    await asyncio.sleep(1.0)
                    post_locs = page.locator('div[role="feed"] > div, div[role="article"]')
                    count = await post_locs.count()
                except Exception:
                    pass

        sample_posts = min(count, 12)
        valid_posts = 0
        total_comments = 0
        total_reactions = 0
        total_shares = 0
        active_posts = 0
        newest_recency_minutes = 99999
        newest_recency_str = "Chưa rõ"

        for idx in range(sample_posts):
            loc = post_locs.nth(idx)
            try:
                text = await loc.evaluate("el => el.innerText || ''")
                if len(text.strip()) < 30: continue
                # Bỏ qua hệ thống FB
                norm = text.lower()
                if any(x in norm for x in ["sắp xếp bảng feed", "tạo bài viết công khai", "bạn viết gì đi"]):
                    continue

                valid_posts += 1

                # 1. Trích xuất bình luận
                c_matches = re.findall(r'(\d+)\s*(?:bình luận|phản hồi|comments?)', text, re.I)
                post_comments = sum(int(m) for m in c_matches) if c_matches else 0

                # 2. Trích xuất chia sẻ
                s_matches = re.findall(r'(\d+)\s*(?:lượt chia sẻ|shares?)', text, re.I)
                post_shares = sum(int(m) for m in s_matches) if s_matches else 0

                # 3. Trích xuất cảm xúc (likes/reactions)
                post_reactions = 0
                lines = [l.strip() for l in text.splitlines() if l.strip()]
                for l in lines:
                    m_other = re.search(r'và (\d+) người khác', l)
                    if m_other: post_reactions = max(post_reactions, int(m_other.group(1)) + 1)
                    if re.match(r'^\d+$', l) and int(l) < 5000:
                        post_reactions = max(post_reactions, int(l))

                total_comments += post_comments
                total_reactions += post_reactions
                total_shares += post_shares

                if post_comments > 0 or post_reactions > 0:
                    active_posts += 1

                # 4. Phân tích thời gian bài viết (lấy bài đầu tiên làm mốc tươi mới)
                if valid_posts == 1:
                    time_line = " ".join(lines[1:4])
                    if "vừa xong" in time_line.lower():
                        newest_recency_minutes = 2
                        newest_recency_str = "Vừa xong"
                    elif "phút" in time_line.lower():
                        m_m = re.search(r'(\d+)\s*phút', time_line)
                        mins = int(m_m.group(1)) if m_m else 10
                        newest_recency_minutes = mins
                        newest_recency_str = f"{mins} phút trước"
                    elif "giờ" in time_line.lower():
                        m_h = re.search(r'(\d+)\s*giờ', time_line)
                        hrs = int(m_h.group(1)) if m_h else 1
                        newest_recency_minutes = hrs * 60
                        newest_recency_str = f"{hrs} giờ trước"
                    elif "hôm qua" in time_line.lower():
                        newest_recency_minutes = 1440
                        newest_recency_str = "Hôm qua"
                    elif "ngày" in time_line.lower():
                        m_d = re.search(r'(\d+)\s*ngày', time_line)
                        days = int(m_d.group(1)) if m_d else 2
                        newest_recency_minutes = days * 1440
                        newest_recency_str = f"{days} ngày trước"

            except Exception:
                continue

        result["valid_posts"] = valid_posts
        result["total_comments"] = total_comments
        result["total_reactions"] = total_reactions
        result["total_shares"] = total_shares
        result["active_posts_count"] = active_posts
        result["newest_recency_str"] = newest_recency_str
        result["newest_recency_minutes"] = newest_recency_minutes

    except Exception as e:
        result["status"] = f"ERROR: {str(e)[:100]}"

    return result

def generate_reports(progress: Dict[str, Dict]):
    """Tạo file diamond_groups.json và báo cáo Markdown"""
    sorted_groups = sorted(
        progress.values(),
        key=lambda x: (x.get("evaluation", {}).get("score", 0), x.get("total_comments", 0)),
        reverse=True
    )

    diamond_list = [g for g in sorted_groups if g.get("evaluation", {}).get("tier") == "DIAMOND"]

    # 1. Lưu diamond_groups.json
    export_diamonds = []
    for g in diamond_list:
        ev = g.get("evaluation", {})
        export_diamonds.append({
            "name": g["name"],
            "url": g["url"],
            "score": ev.get("score", 0),
            "tier": "diamond",
            "avg_comments": ev.get("avg_comments", 0),
            "avg_reactions": ev.get("avg_reactions", 0),
            "newest_recency": g.get("newest_recency_str", ""),
            "total_comments": g.get("total_comments", 0)
        })

    with open(OUTPUT_DIAMOND_FILE, "w", encoding="utf-8") as f:
        json.dump(export_diamonds, f, indent=2, ensure_ascii=False)

    # 2. Tạo Markdown Report
    lines = [
        "# BẢNG XẾP HẠNG TIỀM NĂNG NHÓM BI-A (DIAMOND GROUPS REPORT)\n",
        f"- **Thời gian cập nhật:** {time.strftime('%Y-%m-%d %H:%M:%S')}",
        f"- **Tổng số nhóm đã đánh giá:** {len(progress)} nhóm",
        f"- **Số nhóm đạt chuẩn KIM CƯƠNG (💎 DIAMOND):** {len(diamond_list)} nhóm\n",
        "## Top Nhóm Kim Cương Được Khuyến Nghị Cho Bot Comment (10–15 bài/nhóm)\n",
        "| Hạng | Tên Nhóm | Điểm Tiềm Năng | Bình luận/Mẫu | Cảm xúc/Mẫu | Bài mới nhất | Liên kết |",
        "| :---: | :--- | :---: | :---: | :---: | :---: | :---: |"
    ]

    for idx, g in enumerate(sorted_groups[:60], 1):
        ev = g.get("evaluation", {})
        tier_icon = "💎" if ev.get("tier") == "DIAMOND" else ("⚪" if ev.get("tier") == "NORMAL" else "⚠️")
        score = ev.get("score", 0)
        c_str = f"{g.get('total_comments', 0)} BL"
        r_str = f"{g.get('total_reactions', 0)} Like"
        rec = g.get("newest_recency_str", "Chưa rõ")
        name = g['name'][:40]
        url = g['url']
        lines.append(f"| {idx} | {tier_icon} {name} | **{score}/100** | {c_str} | {r_str} | {rec} | [Truy cập]({url}) |")

    with open(REPORT_MD_FILE, "w", encoding="utf-8") as f:
        f.write("\n".join(lines))

    log(f"💾 Đã xuất file {OUTPUT_DIAMOND_FILE} ({len(diamond_list)} nhóm Kim Cương)")
    log(f"📊 Đã tạo báo cáo {REPORT_MD_FILE}")

async def main():
    parser = argparse.ArgumentParser(description="Filter Diamond Groups for Facebook Auto Commenter")
    parser.add_argument("--limit", type=int, default=0, help="Giới hạn số nhóm quét (0 = tất cả)")
    parser.add_argument("--reset", action="store_true", help="Xóa lịch sử quét cũ, chạy lại từ đầu")
    args = parser.parse_args()

    log("==================================================")
    log("💎 FACEBOOK DIAMOND GROUPS EVALUATOR & FILTER")
    log("==================================================")

    if not os.path.exists(GROUPS_FILE):
        log(f"❌ Không tìm thấy file {GROUPS_FILE}!")
        sys.exit(1)

    with open(GROUPS_FILE, "r", encoding="utf-8") as f:
        all_groups = json.load(f)

    log(f"📋 Tổng số nhóm trong database: {len(all_groups)} nhóm")

    if args.reset and os.path.exists(PROGRESS_FILE):
        os.remove(PROGRESS_FILE)
        log("🔄 Đã reset bộ nhớ cache tiến độ cũ.")

    progress = load_progress()
    log(f"🕒 Tiến độ đã quét từ trước: {len(progress)}/{len(all_groups)} nhóm")

    target_groups = [g for g in all_groups if g["url"] not in progress]
    if args.limit > 0:
        target_groups = target_groups[:args.limit]
        log(f"🎯 Chế độ giới hạn: Sẽ quét {len(target_groups)} nhóm trong lượt này.")
    else:
        log(f"🎯 Sẽ quét {len(target_groups)} nhóm còn lại.")

    if not target_groups:
        log("🎉 ĐÃ QUÉT HẾT TẤT CẢ CÁC NHÓM TRONG DANH SÁCH!")
        generate_reports(progress)
        return

    formatted_cookies = load_cookies()

    async with async_playwright() as p:
        browser = await p.chromium.launch(
            headless=True,
            args=["--disable-blink-features=AutomationControlled", "--no-sandbox"]
        )
        context = await browser.new_context(
            viewport={"width": 1280, "height": 850},
            user_agent="Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/128.0.0.0 Safari/537.36",
            locale="vi-VN",
        )
        await context.add_cookies(formatted_cookies)
        page = await context.new_page()

        for idx, g in enumerate(target_groups, 1):
            g_url = g["url"]
            g_name = g["name"].split("\n")[0].strip()
            log(f"[{idx}/{len(target_groups)}] 🔍 Đang đánh giá: {g_name} ({g_url})")

            eval_data = await evaluate_single_group(page, g)
            score_data = calculate_diamond_score(eval_data)
            eval_data["evaluation"] = score_data

            log(f"   -> Kết quả: {score_data['tier']} | Điểm: {score_data['score']}/100 | BL: {eval_data['total_comments']} | Like: {eval_data['total_reactions']} | Bài mới: {eval_data['newest_recency_str']}")

            progress[g_url] = eval_data
            save_progress(progress)

            # Nghỉ ngắn giữa các nhóm (1.5 - 2.5s)
            await asyncio.sleep(random.uniform(1.5, 2.5))

            # Cứ mỗi 10 nhóm cập nhật lại báo cáo 1 lần
            if idx % 10 == 0:
                generate_reports(progress)

        await browser.close()

    generate_reports(progress)
    log("🏁 HOÀN TẤT QUÁ TRÌNH ĐÁNH GIÁ VÀ LỌC NHÓM!")

if __name__ == "__main__":
    asyncio.run(main())
