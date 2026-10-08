#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
=============================================================================
AUTO-DISCOVER & DIAMOND GROUP EVALUATION PIPELINE (Facebook Billiard Ecosystem)
=============================================================================
Quy trình tự động tìm kiếm, phân loại và đo lường nhóm Facebook mới:
1. Thu thập ứng viên gợi ý từ Facebook Discover Categories (Thể thao, Sở thích, Giải trí)
2. Loại bỏ các nhóm đã có trong hệ thống (đối soát với 715+ nhóm hiện có)
3. Sử dụng mô hình ONNX Transformer + Luật ngữ nghĩa để lọc tên nhóm liên quan Bida/Bi-a
4. Dùng Playwright thẩm định sâu feed: thành viên >= 1000, trạng thái tạm dừng, bình luận, cảm xúc, độ tươi mới
5. Tính điểm tiềm năng Diamond Score (0 - 100)
6. Lưu tiến độ liên tục, xuất new_diamond_groups.json và báo cáo DISCOVERED_DIAMOND_REPORT.md
7. Hỗ trợ cờ --auto-add để tự động nạp nhóm đạt chuẩn vào facebook_joined_groups.json
=============================================================================
"""

import os
import sys
import json
import time
import re
import argparse
import asyncio
from typing import List, Dict, Any, Optional
import numpy as np

ROOT_DIR = os.path.dirname(os.path.abspath(__file__))
MODELS_DIR = os.path.join(ROOT_DIR, "models")
COOKIES_FILE = os.path.join(ROOT_DIR, "fb_cookies.json")
BACKUP_COOKIES = os.path.expanduser("~/.fb_bia_credentials_backup/fb-bia-commentator/fb_cookies.json")
REFRESHED_COOKIES = "/tmp/refreshed_fb_cookies.json"
JOINED_GROUPS_FILE = os.path.join(ROOT_DIR, "facebook_joined_groups.json")
BIA_REPO_GROUPS = os.path.expanduser("~/Downloads/github cronjobs repos/bia/facebook_joined_groups.json")

PROGRESS_FILE = os.path.join(ROOT_DIR, "discovered_diamond_progress.json")
OUTPUT_NEW_DIAMONDS = os.path.join(ROOT_DIR, "new_diamond_groups.json")
REPORT_MD_FILE = os.path.join(ROOT_DIR, "DISCOVERED_DIAMOND_REPORT.md")

# Default Facebook category IDs to explore
DEFAULT_CATEGORIES = [
    {"id": "933473080154675", "name": "Thể thao & thể hình"},
    {"id": "218636258914720", "name": "Sở thích & đam mê"},
    {"id": "905635913112034", "name": "Giải trí"}
]

def log(msg: str):
    timestamp = time.strftime("[%Y-%m-%d %H:%M:%S]")
    print(f"{timestamp} {msg}", flush=True)

# ---------------------------------------------------------------------------
# 1. ONNX RELEVANCE CLASSIFIER
# ---------------------------------------------------------------------------
class GroupRelevanceClassifier:
    """
    Phân loại nhóm có liên quan tới Bi-a/Billiards bằng mô hình ONNX + Từ khóa ngữ nghĩa.
    """
    def __init__(self, models_dir: str = MODELS_DIR):
        self.session = None
        self.tokenizer = None
        self.anchor_embedding = None
        self._init_model(models_dir)

    def _init_model(self, models_dir: str):
        tok_path = os.path.join(models_dir, "tokenizer.json")
        onnx_path = os.path.join(models_dir, "onnx", "model_quantized.onnx")

        # Fallback to bia repo if needed
        if not (os.path.exists(tok_path) and os.path.exists(onnx_path)):
            alt_dir = os.path.expanduser("~/Downloads/github cronjobs repos/bia/models")
            if os.path.exists(os.path.join(alt_dir, "tokenizer.json")):
                tok_path = os.path.join(alt_dir, "tokenizer.json")
                onnx_path = os.path.join(alt_dir, "onnx", "model_quantized.onnx")

        if os.path.exists(tok_path) and os.path.exists(onnx_path):
            try:
                import onnxruntime as ort
                from tokenizers import Tokenizer
                self.tokenizer = Tokenizer.from_file(tok_path)
                self.session = ort.InferenceSession(onnx_path, providers=["CPUExecutionProvider"])
                log(f"🤖 ONNX Classifier: Đã nạp thành công mô hình từ {onnx_path}")
                # Compute anchor embedding
                anchor_text = "Cộng đồng bida câu lạc bộ bi-a mua bán cơ bida gậy bida phụ kiện bàn bida pool carom 3c"
                self.anchor_embedding = self._compute_embedding(anchor_text)
            except Exception as e:
                log(f"⚠️ Không thể khởi tạo ONNX runtime: {e}. Sử dụng bộ phân loại từ khóa kết hợp.")
                self.session = None
        else:
            log("ℹ️ Không tìm thấy file mô hình ONNX. Sử dụng bộ phân loại từ khóa.")

    def _compute_embedding(self, text: str) -> Optional[np.ndarray]:
        if not self.session or not self.tokenizer:
            return None
        try:
            encoded = self.tokenizer.encode(text)
            input_ids = np.array([encoded.ids], dtype=np.int64)
            attention_mask = np.array([encoded.attention_mask], dtype=np.int64)
            token_type_ids = np.zeros_like(input_ids, dtype=np.int64)

            outputs = self.session.run(None, {
                "input_ids": input_ids,
                "attention_mask": attention_mask,
                "token_type_ids": token_type_ids
            })
            last_hidden = outputs[0]  # (1, seq_len, hidden_dim)
            mask_expanded = np.expand_dims(attention_mask, -1)
            sum_embeddings = np.sum(last_hidden * mask_expanded, axis=1)
            sum_mask = np.clip(mask_expanded.sum(axis=1), a_min=1e-9, a_max=None)
            mean_pooled = sum_embeddings / sum_mask
            norm = np.linalg.norm(mean_pooled, axis=1, keepdims=True)
            return (mean_pooled / norm)[0]
        except Exception:
            return None

    def is_billiard_group(self, group_name: str, snippet: str = "") -> Dict[str, Any]:
        combined_text = f"{group_name} {snippet}".lower().strip()

        # Obvious negative filters (reject immediately)
        negatives = [
            "bể cá", "thủy sinh", "việc làm", "tuyển dụng", "xe máy", "ô tô",
            "bất động sản", "nhà trọ", "phòng trọ", "thú cưng", "mèo", "chó",
            "điện thoại", "iphone", "sinh viên tìm việc", "hàng bom", "shoppe"
        ]
        if any(neg in combined_text for neg in negatives) and not any(pos in combined_text for pos in ["bida", "bi-a", "billiards"]):
            return {"is_match": False, "score": 0.0, "reason": "Chứa từ khóa loại trừ"}

        # Direct positive keyword check
        positives = [
            "bida", "bi-a", "billiards", "cơ bida", "gậy bida", "ngọn carbon",
            "bàn bida", "pool 9 bi", "chinesepool", "carom", "3c", "snooker", "chợ bida"
        ]
        has_direct_kw = any(kw in combined_text for kw in positives)

        # ONNX Semantic Cosine Similarity
        sim_score = 0.0
        if self.anchor_embedding is not None:
            emb = self._compute_embedding(group_name)
            if emb is not None:
                sim_score = float(np.dot(self.anchor_embedding, emb))

        # Decision
        if has_direct_kw:
            is_match = True
            reason = f"Trùng từ khóa cốt lõi (ONNX sim: {sim_score:.3f})"
        elif sim_score >= 0.52:
            is_match = True
            reason = f"Độ tương đồng ngữ nghĩa ONNX cao ({sim_score:.3f} >= 0.52)"
        else:
            is_match = False
            reason = f"Không đủ điểm liên quan (ONNX sim: {sim_score:.3f})"

        return {
            "is_match": is_match,
            "similarity": round(sim_score, 3),
            "has_keyword": has_direct_kw,
            "reason": reason
        }

# ---------------------------------------------------------------------------
# 2. COOKIES & REPOSITORIES INTEGRATION
# ---------------------------------------------------------------------------
def load_cookies() -> List[Dict]:
    candidate_paths = [REFRESHED_COOKIES, COOKIES_FILE, BACKUP_COOKIES]
    for p in candidate_paths:
        if os.path.exists(p):
            try:
                with open(p, "r", encoding="utf-8") as f:
                    raw = json.load(f)
                formatted = []
                for c in raw:
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
                log(f"🍪 Đã nạp thành công {len(formatted)} cookies từ {p}")
                return formatted
            except Exception:
                pass
    log("⚠️ Không tìm thấy file cookies nào khả dụng!")
    return []

def load_existing_group_slugs() -> set:
    slugs = set()
    files = [JOINED_GROUPS_FILE, BIA_REPO_GROUPS]
    for fp in files:
        if os.path.exists(fp):
            try:
                with open(fp, "r", encoding="utf-8") as f:
                    data = json.load(f)
                for item in data:
                    u = item.get("url", "")
                    cleaned = u.strip("/").split("/")[-1].lower()
                    if cleaned:
                        slugs.add(cleaned)
            except Exception:
                pass
    log(f"📋 Đã tải {len(slugs)} nhóm đã tham gia từ hệ thống để chống trùng lặp.")
    return slugs

def load_progress() -> Dict[str, Dict]:
    if os.path.exists(PROGRESS_FILE):
        try:
            with open(PROGRESS_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            pass
    return {}

def save_progress(data: Dict[str, Dict]):
    with open(PROGRESS_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)

# ---------------------------------------------------------------------------
# 3. DIAMOND SCORING ENGINE
# ---------------------------------------------------------------------------
def calculate_diamond_score(metrics: Dict) -> Dict:
    total_comments = metrics.get("total_comments", 0)
    total_reactions = metrics.get("total_reactions", 0)
    valid_posts = metrics.get("valid_posts", 0)
    newest_recency_minutes = metrics.get("newest_recency_minutes", 99999)
    active_posts_count = metrics.get("active_posts_count", 0)

    # 1. Điểm bình luận (Mật độ tương tác khách hỏi mua - Max 40)
    avg_comments = (total_comments / valid_posts) if valid_posts > 0 else 0
    comment_pts = min(40.0, (total_comments * 3.0) + (avg_comments * 5.0))

    # 2. Điểm cảm xúc / reactions (Max 20)
    avg_reactions = (total_reactions / valid_posts) if valid_posts > 0 else 0
    reaction_pts = min(20.0, (total_reactions * 1.5) + (avg_reactions * 2.0))

    # 3. Điểm tươi mới bài viết (Max 25)
    if newest_recency_minutes <= 60:
        recency_pts = 25.0
    elif newest_recency_minutes <= 360:
        recency_pts = 20.0
    elif newest_recency_minutes <= 1440:
        recency_pts = 15.0
    elif newest_recency_minutes <= 4320:
        recency_pts = 5.0
    else:
        recency_pts = 0.0

    # 4. Tỷ lệ bài có tương tác (Max 15)
    interaction_pts = min(15.0, active_posts_count * 3.0)

    total_score = round(comment_pts + reaction_pts + recency_pts + interaction_pts, 1)

    # Xếp hạng Tier
    if total_score >= 30.0 or total_comments >= 5 or (newest_recency_minutes <= 60 and valid_posts >= 2):
        tier = "DIAMOND"
    elif total_score >= 15.0 or valid_posts >= 1:
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

# ---------------------------------------------------------------------------
# 4. DEEP GROUP EVALUATOR (PLAYWRIGHT)
# ---------------------------------------------------------------------------
async def evaluate_group_feed(page, group_url: str, group_name: str) -> Dict[str, Any]:
    result = {
        "url": group_url,
        "name": group_name,
        "status": "OK",
        "members": "0",
        "members_num": 0,
        "is_paused": False,
        "valid_posts": 0,
        "total_comments": 0,
        "total_reactions": 0,
        "active_posts_count": 0,
        "newest_recency_str": "Không rõ",
        "newest_recency_minutes": 99999,
        "is_blocked": False
    }
    try:
        await page.goto(group_url, wait_until="domcontentloaded", timeout=22000)
        await asyncio.sleep(2.5)

        body_text = await page.inner_text("body")

        # 1. Kiểm tra tạm dừng
        if ("tạm dừng nhóm" in body_text.lower()) or ("nhóm này đang tạm dừng" in body_text.lower()) or ("group is paused" in body_text.lower()):
            result["is_paused"] = True
            result["status"] = "PAUSED"
            return result

        if "bạn hiện không xem được nội dung này" in body_text.lower():
            result["is_blocked"] = True
            result["status"] = "BLOCKED_OR_DELETED"
            return result

        # 2. Trích xuất số lượng thành viên
        m_match = re.search(r"·\s*([\d\.,]+[KkMm]?)\s*thành viên", body_text)
        if not m_match:
            m_match = re.search(r"([\d\.,]+[KkMm]?)\s*(?:thành viên|members)", body_text)
        
        member_str = m_match.group(1).strip() if m_match else "0"
        result["members"] = member_str

        mem_num = 0
        if "k" in member_str.lower():
            clean_m = re.sub(r"[^\d\.,]", "", member_str).replace(",", ".")
            try: mem_num = float(clean_m) * 1000
            except: pass
        elif "m" in member_str.lower() or "triệu" in member_str.lower():
            clean_m = re.sub(r"[^\d\.,]", "", member_str).replace(",", ".")
            try: mem_num = float(clean_m) * 1000000
            except: pass
        else:
            clean_m = re.sub(r"[^\d]", "", member_str)
            if clean_m:
                try: mem_num = float(clean_m)
                except: pass
        result["members_num"] = int(mem_num)

        if 0 < mem_num < 1000:
            result["status"] = "TOO_FEW_MEMBERS"
            return result

        # 3. Cuộn để nạp bài viết
        for _ in range(2):
            await page.evaluate("window.scrollBy(0, 1200)")
            await asyncio.sleep(1.2)

        # Trích xuất feed text
        feed_text = await page.inner_text("body")

        # Đếm bình luận
        c_matches = re.findall(r"(\d+)\s*(?:bình luận|phản hồi|comments?)", feed_text, re.I)
        result["total_comments"] = sum(int(m) for m in c_matches) if c_matches else 0

        # Đếm lượt tương tác/cảm xúc
        r_matches = re.findall(r"(\d+)\s*(?:lượt thích|người khác|cảm xúc)", feed_text, re.I)
        result["total_reactions"] = sum(int(m) for m in r_matches) if r_matches else 0

        # Xác định độ mới của bài viết
        rec_matches = re.findall(r"(\b\d+\s*(?:phút|giờ|ngày|tuần|tháng|năm)\s*trước\b|\bvừa xong\b|\bkhoảng \d+\s*(?:phút|giờ)\s*trước\b)", feed_text, re.I)
        if rec_matches:
            newest_rec = rec_matches[0]
            result["newest_recency_str"] = newest_rec
            low_rec = newest_rec.lower()
            if "vừa xong" in low_rec:
                result["newest_recency_minutes"] = 2
            elif "phút" in low_rec:
                m_mins = re.search(r"(\d+)", low_rec)
                result["newest_recency_minutes"] = int(m_mins.group(1)) if m_mins else 10
            elif "giờ" in low_rec:
                m_hrs = re.search(r"(\d+)", low_rec)
                result["newest_recency_minutes"] = (int(m_hrs.group(1)) if m_hrs else 1) * 60
            elif "hôm qua" in low_rec:
                result["newest_recency_minutes"] = 1440
            elif "ngày" in low_rec:
                m_days = re.search(r"(\d+)", low_rec)
                result["newest_recency_minutes"] = (int(m_days.group(1)) if m_days else 2) * 1440
            elif "tuần" in low_rec or "tháng" in low_rec or "năm" in low_rec:
                result["newest_recency_minutes"] = 100000

        articles = await page.query_selector_all("div[role='feed'] div[role='article'], div[role='article']")
        result["valid_posts"] = len(articles) or (1 if rec_matches else 0)
        result["active_posts_count"] = min(len(c_matches), result["valid_posts"])

    except Exception as e:
        result["status"] = f"ERROR: {str(e)[:80]}"

    return result

# ---------------------------------------------------------------------------
# 5. DISCOVERY HARVESTER
# ---------------------------------------------------------------------------
async def harvest_category_groups(page, category_id: str, category_name: str) -> List[Dict]:
    url = f"https://www.facebook.com/groups/categories/?category_id={category_id}"
    log(f"🔎 Đang quét danh mục khám phá: {category_name} ({url}) ...")
    candidates = []
    try:
        await page.goto(url, wait_until="domcontentloaded", timeout=25000)
        await asyncio.sleep(3.0)

        # Cuộn 3 lần để nạp thêm các thẻ nhóm
        for _ in range(3):
            await page.evaluate("window.scrollBy(0, 1500)")
            await asyncio.sleep(1.5)

        raw_links = await page.evaluate("""() => {
            const anchors = Array.from(document.querySelectorAll('a[href*="/groups/"]'));
            const items = [];
            for (const a of anchors) {
                const href = a.href;
                const text = a.innerText.trim();
                if (href.includes("/categories") || href.includes("/feed") || href.includes("/permalink")) continue;
                const match = href.match(/facebook\\.com\\/groups\\/([^\\/?]+)/);
                if (match) {
                    const id = match[1];
                    items.push({
                        id: id,
                        url: "https://www.facebook.com/groups/" + id + "/",
                        name: text,
                        context: a.closest("div") ? a.closest("div").innerText.slice(0, 200) : ""
                    });
                }
            }
            return items;
        }""")

        # Deduplicate
        seen = set()
        for item in raw_links:
            gid = item["id"].lower()
            if gid not in seen and item["name"] and len(item["name"]) > 2:
                seen.add(gid)
                candidates.append(item)

        log(f"   -> Thu hoạch được {len(candidates)} thẻ nhóm từ danh mục {category_name}.")
    except Exception as e:
        log(f"❌ Lỗi khi quét danh mục {category_name}: {e}")

    return candidates

# ---------------------------------------------------------------------------
# 6. REPORT & AUTO-ADD GENERATOR
# ---------------------------------------------------------------------------
def generate_reports(progress: Dict[str, Dict]):
    diamond_list = [g for g in progress.values() if g.get("evaluation", {}).get("tier") == "DIAMOND"]
    diamond_list.sort(key=lambda x: x.get("evaluation", {}).get("score", 0), reverse=True)

    # 1. Xuất new_diamond_groups.json
    export_data = []
    for g in diamond_list:
        ev = g.get("evaluation", {})
        export_data.append({
            "name": g["name"],
            "url": g["url"],
            "members": g.get("members", "0"),
            "diamond_score": ev.get("score", 0),
            "tier": "DIAMOND",
            "newest_recency": g.get("newest_recency_str", "Không rõ"),
            "total_comments": g.get("total_comments", 0),
            "total_reactions": g.get("total_reactions", 0)
        })

    with open(OUTPUT_NEW_DIAMONDS, "w", encoding="utf-8") as f:
        json.dump(export_data, f, indent=2, ensure_ascii=False)
    log(f"💎 Đã lưu {len(export_data)} Nhóm Kim Cương mới vào {OUTPUT_NEW_DIAMONDS}")

    # 2. Xuất DISCOVERED_DIAMOND_REPORT.md
    with open(REPORT_MD_FILE, "w", encoding="utf-8") as f:
        f.write("# 💎 Báo Cáo Nhóm Facebook Bida Kim Cương Khám Phá Mới\n\n")
        f.write(f"> **Tổng hợp:** {len(export_data)} nhóm Kim Cương đạt chuẩn tương tác cao.\n\n")
        f.write("| STT | Tên Nhóm | Thành Viên | Điểm Kim Cương | Bình Luận | Cảm Xúc | Bài Mới Nhất | Link |\n")
        f.write("| :---: | :--- | :---: | :---: | :---: | :---: | :---: | :--- |\n")
        for idx, g in enumerate(export_data, 1):
            f.write(f"| {idx} | **{g['name']}** | {g['members']} | **{g['diamond_score']}** | {g['total_comments']} | {g['total_reactions']} | {g['newest_recency']} | [Xem]({g['url']}) |\n")
        f.write("\n---\n*Báo cáo được tạo tự động bởi Auto-Discover & Diamond Evaluator Pipeline.*\n")
    log(f"📊 Đã tạo báo cáo Markdown tại {REPORT_MD_FILE}")

def auto_add_to_repos(diamond_groups: List[Dict]):
    if not diamond_groups:
        log("ℹ️ Không có nhóm Kim Cương mới để nạp vào hệ thống.")
        return

    targets = [JOINED_GROUPS_FILE, BIA_REPO_GROUPS]
    for fp in targets:
        if not os.path.exists(fp):
            continue
        try:
            with open(fp, "r", encoding="utf-8") as f:
                data = json.load(f)
            existing_slugs = {item.get("url", "").strip("/").split("/")[-1].lower() for item in data}

            added_count = 0
            for g in diamond_groups:
                slug = g["url"].strip("/").split("/")[-1].lower()
                if slug not in existing_slugs:
                    data.append({
                        "name": f"{g['name']}\nLần hoạt động gần nhất: {g.get('newest_recency', 'Vừa xong')}",
                        "url": g["url"]
                    })
                    existing_slugs.add(slug)
                    added_count += 1

            if added_count > 0:
                with open(fp, "w", encoding="utf-8") as f:
                    json.dump(data, f, indent=2, ensure_ascii=False)
                log(f"✅ Đã thêm {added_count} nhóm mới vào {fp}")
            else:
                log(f"ℹ️ Không có nhóm mới nào cần nạp vào {fp} (đã tồn tại).")
        except Exception as e:
            log(f"❌ Lỗi khi cập nhật {fp}: {e}")

# ---------------------------------------------------------------------------
# 7. MAIN ORCHESTRATION PIPELINE
# ---------------------------------------------------------------------------
async def main():
    parser = argparse.ArgumentParser(description="Auto-Discover & Diamond Group Evaluator")
    parser.add_argument("--limit", type=int, default=15, help="Giới hạn số nhóm đánh giá sâu")
    parser.add_argument("--auto-add", action="store_true", help="Tự động nạp nhóm đạt chuẩn vào facebook_joined_groups.json")
    parser.add_argument("--category-id", type=str, default="", help="Chỉ định ID danh mục cần quét")
    parser.add_argument("--seed-file", type=str, default="", help="Đường dẫn file JSON/TXT chứa danh sách link nhóm ứng viên bổ sung")
    parser.add_argument("--headless", type=bool, default=True, help="Chạy ẩn danh")
    args = parser.parse_args()

    log("🚀 Khởi chạy Auto-Discover & Diamond Group Evaluation Pipeline...")

    # 1. Khởi tạo bộ phân loại ONNX
    classifier = GroupRelevanceClassifier(MODELS_DIR)

    # 2. Tải danh sách nhóm đã tham gia
    existing_slugs = load_existing_group_slugs()

    # 3. Nạp cookies
    cookies = load_cookies()
    if not cookies:
        log("❌ Không thể tiếp tục do thiếu cookies!")
        sys.exit(1)

    # 4. Tải tiến độ cũ
    progress = load_progress()

    from playwright.async_api import async_playwright
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=args.headless)
        context = await browser.new_context(
            viewport={"width": 1280, "height": 900},
            user_agent="Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/128.0.0.0 Safari/537.36",
            locale="vi-VN",
            timezone_id="Asia/Ho_Chi_Minh"
        )
        await context.add_cookies(cookies)
        page = await context.new_page()

        # Kiểm tra phiên
        await page.goto("https://www.facebook.com/", wait_until="domcontentloaded")
        await asyncio.sleep(3.0)

        raw_candidates = []

        # A. Nạp từ seed-file nếu có
        if args.seed_file and os.path.exists(args.seed_file):
            log(f"📂 Đang nạp danh sách ứng viên từ seed file: {args.seed_file} ...")
            try:
                with open(args.seed_file, "r", encoding="utf-8") as f:
                    content = f.read().strip()
                if content.startswith("[") or content.startswith("{"):
                    seed_data = json.loads(content)
                    if isinstance(seed_data, list):
                        for item in seed_data:
                            if isinstance(item, str):
                                m = re.search(r"groups/([^/?]+)", item)
                                if m:
                                    raw_candidates.append({
                                        "id": m.group(1),
                                        "url": f"https://www.facebook.com/groups/{m.group(1)}/",
                                        "name": m.group(1),
                                        "context": ""
                                    })
                            elif isinstance(item, dict):
                                u = item.get("url") or item.get("group_url", "")
                                m = re.search(r"groups/([^/?]+)", u)
                                if m:
                                    raw_candidates.append({
                                        "id": m.group(1),
                                        "url": f"https://www.facebook.com/groups/{m.group(1)}/",
                                        "name": item.get("name", m.group(1)),
                                        "context": ""
                                    })
                else:
                    for line in content.splitlines():
                        line = line.strip()
                        m = re.search(r"groups/([^/?]+)", line)
                        if m:
                            raw_candidates.append({
                                "id": m.group(1),
                                "url": f"https://www.facebook.com/groups/{m.group(1)}/",
                                "name": m.group(1),
                                "context": ""
                            })
                log(f"   -> Nạp thành công {len(raw_candidates)} ứng viên từ seed file.")
            except Exception as e:
                log(f"❌ Lỗi nạp seed file: {e}")

        # B. Thu hoạch ứng viên từ danh mục nếu không chỉ định riêng seed-file hoặc có yêu cầu
        if not args.seed_file or args.category_id:
            categories_to_scan = DEFAULT_CATEGORIES
            if args.category_id:
                categories_to_scan = [{"id": args.category_id, "name": f"Tùy chọn ({args.category_id})"}]

            for cat in categories_to_scan:
                items = await harvest_category_groups(page, cat["id"], cat["name"])
                raw_candidates.extend(items)

        # Lọc chống trùng lặp
        unjoined_candidates = []
        seen = set()
        for c in raw_candidates:
            slug = c["id"].lower()
            if slug not in existing_slugs and slug not in seen:
                seen.add(slug)
                unjoined_candidates.append(c)

        log(f"🎯 Sau khi loại trừ các nhóm cũ, còn {len(unjoined_candidates)} nhóm ứng viên mới hoàn toàn.")

        # Lọc ngữ nghĩa ONNX
        billiard_candidates = []
        for c in unjoined_candidates:
            # Nếu tên chỉ là chuỗi số ID (do nạp từ link trần), lấy tiêu đề thật của trang trước
            if re.match(r"^\d+$", c["name"]):
                try:
                    log(f"🔍 Đang lấy tên nhóm cho ID trần: {c['url']} ...")
                    await page.goto(c["url"], wait_until="domcontentloaded", timeout=12000)
                    title_txt = await page.title()
                    c["name"] = re.sub(r"\s*\|\s*Facebook$", "", title_txt).strip() or c["id"]
                    log(f"   -> Tên nhóm nhận diện được: {c['name']}")
                except Exception:
                    pass

            rel = classifier.is_billiard_group(c["name"], c.get("context", ""))
            if rel["is_match"]:
                c["classifier_reason"] = rel["reason"]
                c["similarity"] = rel["similarity"]
                billiard_candidates.append(c)
                log(f"  ✅ [MATCH ONNX] {c['name']} -> {rel['reason']}")
            else:
                log(f"  ❌ [DISCARD] {c['name']} -> {rel['reason']}")

        log(f"🎱 Đã xác định được {len(billiard_candidates)} nhóm liên quan Bida/Bi-a.")

        # Thẩm định sâu (Deep Feed Evaluation)
        evaluated_count = 0
        for idx, cand in enumerate(billiard_candidates, 1):
            if evaluated_count >= args.limit:
                log(f"⏹ Đã đạt giới hạn --limit {args.limit}, dừng ca đánh giá.")
                break

            url = cand["url"]
            slug = cand["id"].lower()

            if slug in progress and progress[slug].get("evaluation", {}).get("tier") in ["DIAMOND", "NORMAL"]:
                log(f"⏩ Nhóm {cand['name']} đã được đánh giá trước đó, bỏ qua.")
                continue

            log(f"[{idx}/{len(billiard_candidates)}] 🧐 Đang thẩm định tương tác thực tế: {cand['name']} ({url})...")
            metrics = await evaluate_group_feed(page, url, cand["name"])
            ev = calculate_diamond_score(metrics)
            metrics["evaluation"] = ev
            metrics["id"] = cand["id"]

            progress[slug] = metrics
            save_progress(progress)
            evaluated_count += 1

            status_str = f"Tier: {ev['tier']} | Score: {ev['score']} | Comments: {metrics['total_comments']} | Recency: {metrics['newest_recency_str']}"
            if ev["tier"] == "DIAMOND":
                log(f"  💎 XÁC NHẬN NHÓM KIM CƯƠNG: {cand['name']} -> {status_str}")
            else:
                log(f"  ⚪ {cand['name']} -> {status_str}")

        await browser.close()

    # Xuất báo cáo
    generate_reports(progress)

    # Nạp tự động nếu có yêu cầu
    if args.auto_add:
        diamonds = [g for g in progress.values() if g.get("evaluation", {}).get("tier") == "DIAMOND"]
        auto_add_to_repos(diamonds)

    log("🏁 Hoàn tất quy trình Auto-Discover & Diamond Group Evaluation Pipeline!")

if __name__ == "__main__":
    asyncio.run(main())
