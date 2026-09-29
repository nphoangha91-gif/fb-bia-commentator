import os
import re
import json
import random
import unicodedata
from typing import List, Dict, Optional, Tuple
import numpy as np

ASSETS_DIR = os.path.dirname(os.path.abspath(__file__))
CONTENT_FILE = os.path.join(ASSETS_DIR, "content.txt")
MODEL_DIR = os.path.join(ASSETS_DIR, "models")
ONNX_MODEL_FILE = os.path.join(MODEL_DIR, "onnx", "model_quantized.onnx")
TOKENIZER_FILE = os.path.join(MODEL_DIR, "tokenizer.json")

# Danh mục sản phẩm từ content.txt
OUR_PRODUCTS = {
    "ngon_apex": {
        "title": "Ngọn gỗ Apex vỏ gỗ mun Ebony lõi carbon",
        "details": "vỏ gỗ mun ebony lõi carbon lên ring tẩy mới lên dày cộp tình trạng hoàn hảo 99%",
        "selling_point": "đánh cực kỳ đầm chắc, trợ lực tốt, trợ lực thoát bi không thua kém các dòng ngọn hãng đắt tiền"
    },
    "chuoi_tg": {
        "title": "Chuôi TG full carbon kèm nối",
        "details": "chuôi TG full carbon kèm khúc nối trợ lực, tình trạng hoàn hảo 99%",
        "selling_point": "cầm đầm tay, cân bằng lực tốt, full carbon chống cong vênh tuyệt đối"
    },
    "bo_lankou": {
        "title": "Bộ Lankou Cơn bão Thanh Xuân 05 gỗ phong",
        "details": "gỗ phong chuyên đánh chinesepool chuẩn lực + chính xác 99%",
        "selling_point": "ngọn gỗ phong truyền lực đều, kiểm soát bi cái cực chuẩn trong tầm giá"
    },
    "gay_nhay_thunder": {
        "title": "Gậy nhảy ngọn carbon Thunder size 14",
        "details": "ngọn carbon thunder size 14 siêu nhạy + khỏe, chuôi gỗ lên ring ở Phúc Long 99%",
        "selling_point": "nhảy bi tê cực kỳ thoát bi và nhẹ tay, không tốn sức"
    },
    "full_combo": {
        "title": "Combo thanh lý nghỉ game (Có lẻ chuôi, lẻ ngọn, bao găng)",
        "details": "đủ ngọn Apex mun lõi carbon, chuôi TG carbon kèm nối, bộ Lankou 05, gậy nhảy Thunder, bao găng 99%",
        "selling_point": "giá thanh lý nghỉ game sốc nhất thị trường, xé lẻ thoải mái cho anh em"
    }
}

# Các hãng gậy phổ biến trên thị trường để phát hiện khi người dùng tìm kiếm
POPULAR_BRANDS = [
    "peri", "fury", "predator", "cuetec", "mezz", "mit", "rhino", "how", "konllen", "jflowers"
]

def normalize_text(text: str) -> str:
    """Loại bỏ dấu tiếng Việt và chuẩn hoá chữ thường."""
    if not text:
        return ""
    text = text.lower().strip()
    text = unicodedata.normalize("NFD", text)
    text = re.sub(r"[\u0300-\u036f]", "", text)
    return text.replace("đ", "d")


class ONNXCommentEngine:
    """
    ONNX Contextual Comment Engine phân loại bài viết theo 3 TÌNH HUỐNG (3 SITUATIONS):
    1. SITUATION_SALE (Bài đăng bán của người khác):
       -> Đọc người ta bán gì để BÌNH LUẬN BÁN CHÉO (CROSS-SELLING) ghép đôi hoàn hảo, hoặc xin phép chủ post ké pass lịch sự.
    2. SITUATION_FINDING (Bài tìm mua, hỏi mua, tư vấn gậy/phụ kiện):
       -> Đọc ngân sách, dòng gậy, thương hiệu tìm kiếm để gợi ý sản phẩm phù hợp nhất với giá nghỉ game tốt nhất thị trường.
    3. SITUATION_DISCUSS (Bài thảo luận, chia sẻ, giao lưu, giải trí):
       -> Bình luận ngắn gọn, văn minh: "Xin phép chủ post cho em ké pass..."
    """

    def __init__(self):
        self.session = None
        self.tokenizer = None
        self._init_onnx()

    def _init_onnx(self):
        if os.path.exists(ONNX_MODEL_FILE) and os.path.exists(TOKENIZER_FILE):
            try:
                import onnxruntime as ort
                from tokenizers import Tokenizer
                self.tokenizer = Tokenizer.from_file(TOKENIZER_FILE)
                self.session = ort.InferenceSession(ONNX_MODEL_FILE, providers=["CPUExecutionProvider"])
                print(f"🤖 ONNX Comment Engine: Đã nạp thành công ONNX Model từ {ONNX_MODEL_FILE}")
            except Exception as e:
                print(f"⚠️ Lỗi nạp ONNX Model ({e}). Sử dụng Hybrid Context Analyzer.")
                self.session = None
        else:
            print("ℹ️ ONNX Comment Engine: Sử dụng Hybrid Context Analyzer.")

    def detect_situation(self, post_text: str, comments_text: str = "") -> str:
        """
        Xác định bài viết thuộc tình huống nào trong 3 nhóm:
        - SITUATION_SALE (Chủ bài đang đăng bán / pass hàng)
        - SITUATION_FINDING (Bài tìm mua / hỏi mua / xin tư vấn)
        - SITUATION_DISCUSS (Thảo luận / giao lưu / cảnh báo / khác)
        """
        norm_post = normalize_text(post_text)

        # 1. Kiểm tra dấu hiệu người tìm mua trước (BUYER INDICATORS)
        # Các câu hỏi: ai có pass không, có ai thanh lý không, em cần, cần cây, tìm mua...
        buyer_indicators = [
            "ai co", "co ai", "anh em co", "bac nao co", "ai pass", "co pass lai", 
            "dang can", "can cay", "can tim", "tim mua", "can mua", "tim gay", 
            "tim chuoi", "tim ngon", "tim do", "can sam", "xin gia", "tu van", 
            "tai chinh", "ngan sach", "tam gia", "hoc sinh", "sinh vien"
        ]
        if any(b in norm_post for b in buyer_indicators) and not any(s in norm_post for s in ["can ban", "muon ban", "xa cay", "xa hang"]):
            # Loại trừ nếu bài chỉ là cảnh báo lừa đảo
            if not any(w in norm_post for w in ["canh bao", "lua dao", "phot", "scam"]):
                return "SITUATION_FINDING"

        # 2. Kiểm tra BÀI ĐĂNG BÁN (SITUATION_SALE)
        # Người bán: cần bán, pass lại cây, xả đồ, bán ngọn, giá công khai, lẻ ngọn, lẻ chuôi, để ae giá, gdtt, ship cod...
        sale_triggers = [
            "can ban", "muon ban", "ban cay", "ban ngon", "ban chuoi", "ban gay", "ban combo",
            "pass lai", "can pass", "thanh ly", "xa cay", "xa hang", "xa do", "xa co",
            "cong khai", "gia cong khai", "gia hat re", "ra di", "do choi", "de ae gia",
            "le ngon", "le chuoi", "gia tot", "ship cod", "gdtt", "con vài cay",
            "giao luu len doi", "con moi", "full box", "moi 99%", "moi 95%"
        ]
        has_price_tag = bool(re.search(r'\b[0-9]+(?:\.[0-9]+)?\s*(?:k|cu|trieu|tr|vnd|d)\b', norm_post)) or "1tr" in norm_post or "2tr" in norm_post or "3tr" in norm_post
        
        is_selling = any(kw in norm_post for kw in sale_triggers) or (
            ("ban" in norm_post or "pass" in norm_post or "xa" in norm_post or "nhay" in norm_post or "combo" in norm_post) and has_price_tag
        )

        if is_selling:
            return "SITUATION_SALE"

        # 3. Kiểm tra bài tìm mua thông thường còn sót lại
        if any(item in norm_post for item in ["ngon", "chuoi", "gay", "carbon", "jump", "nhay", "co", "phu kien"]):
            if any(action in norm_post for action in ["tim", "can", "mua"]):
                if not any(w in norm_post for w in ["canh bao", "lua dao", "phot"]):
                    return "SITUATION_FINDING"

        # 4. Mặc định là thảo luận / giao lưu chung (SITUATION_DISCUSS)
        return "SITUATION_DISCUSS"

    def generate_contextual_comment(
        self,
        post_text: str,
        comments_text: str = "",
        post_id: str = "",
        author_name: str = ""
    ) -> Dict:
        """
        Đọc và phân tích sâu bài viết để đưa ra bình luận chính xác theo 3 tình huống.
        """
        situation = self.detect_situation(post_text, comments_text)
        norm_post = normalize_text(post_text)

        # =========================================================================
        # TÌNH HUỐNG 1: BÀI ĐĂNG BÁN (SITUATION_SALE) -> BÁN CHÉO (CROSS-SELLING) HOẶC KÉ LỊCH SỰ
        # =========================================================================
        if situation == "SITUATION_SALE":
            is_selling_shaft = any(k in norm_post for k in ["ngon", "shaft", "dau co"])
            is_selling_butt = any(k in norm_post for k in ["chuoi", "butt", "can co"])

            if is_selling_shaft and not is_selling_butt:
                # Tác giả bán ngọn -> Mình gợi ý Chuôi TG full carbon ghép đôi!
                templates = [
                    "Ngọn của chủ thớt đẹp quá, chúc chủ thớt sớm bay nhé! Bác nào chốt ngọn của chủ thớt mà cần tìm chuôi carbon đầm tay thì em sẵn cây chuôi TG full carbon kèm nối 99% luôn ạ, ghép vào combo này đánh bao phê. Bác nào ưng chuôi nhắn em nhé.",
                    "Hàng đẹp chúc bác bay nhanh! Bác nào lấy ngọn của chủ post cần chuôi ghép cùng thì em có cây chuôi TG full carbon kèm khúc nối, giá nghỉ game cực tốt cho anh em lên trọn bộ ạ.",
                    "Ké bác chủ tí ạ: Bác nào hốt ngọn này cần chuôi trợ lực thì em dư cây TG full carbon kèm nối trợ lực mới 99%, giá nghỉ game bao mềm ghép đôi chuẩn bài."
                ]
                chosen = random.choice(templates)
                return {
                    "should_comment": True,
                    "situation": "SITUATION_SALE (Cross-sell Chuôi TG)",
                    "matched_product": OUR_PRODUCTS["chuoi_tg"]["title"],
                    "comment_text": chosen
                }

            elif is_selling_butt and not is_selling_shaft:
                # Tác giả bán chuôi -> Mình gợi ý Ngọn Apex mun Ebony lõi carbon ghép đôi!
                templates = [
                    "Cây chuôi của chủ thớt nhìn chất lượng quá! Bác nào chốt chuôi này cần ngọn đầm chắc trợ lực thì em sẵn cây ngọn Apex vỏ mun Ebony lõi carbon lên ring tẩy dày cộp 99% nhé, ghép với chuôi này đánh bao đầm tay. Bác nào cần ngọn ib em nha.",
                    "Chúc bác chủ bay nhanh! Tiện đây bác nào lấy chuôi của bác chủ mà cần ngọn chuẩn lực thì ới em, em có ngọn Apex mun Ebony lõi carbon 99% nghỉ game để lại giá mềm ạ.",
                    "Xin phép bác chủ cho em ké: Bác nào rước chuôi về cần tìm ngọn trợ lực cao cấp thì em sẵn ngọn Apex vỏ mun ebony lõi carbon, tình trạng hoàn hảo 99% xả nghỉ game giá êm."
                ]
                chosen = random.choice(templates)
                return {
                    "should_comment": True,
                    "situation": "SITUATION_SALE (Cross-sell Ngọn Apex)",
                    "matched_product": OUR_PRODUCTS["ngon_apex"]["title"],
                    "comment_text": chosen
                }

            else:
                # Tác giả bán trọn bộ cơ hoặc đồ khác -> Ké gậy nhảy hoặc ké trọn gói lịch sự
                templates = [
                    "Chúc chủ thớt mau bay hàng nhé! Bác nào chốt cơ của chủ thớt cần thêm cây gậy nhảy thoát bi cho đủ combo thì em sẵn cây Thunder ngọn carbon size 14 lên ring Phúc Long 99% thanh lý giá siêu mềm, cần xem gậy nhảy nhắn em nha.",
                    "Hàng đẹp quá chúc bác chủ sớm chốt! Em xin phép ké pass ít đồ nghỉ game giá sốc: ngọn Apex mun lõi carbon, chuôi TG full carbon kèm nối, bộ Lankou 05, gậy nhảy Thunder. Có xé lẻ cho anh em, bác nào quan tâm ib em nhé.",
                    "Xin phép chủ post cho em ké pass đồ cá nhân nghỉ game: ngọn gỗ Apex mun ebony lõi carbon, chuôi TG carbon kèm nối, gậy nhảy Thunder. Tình trạng 99% bao check thoải mái, bác nào cần món gì ới em nha."
                ]
                chosen = random.choice(templates)
                return {
                    "should_comment": True,
                    "situation": "SITUATION_SALE (Polite Cross-sell / Ké pass)",
                    "matched_product": OUR_PRODUCTS["full_combo"]["title"],
                    "comment_text": chosen
                }

        # =========================================================================
        # TÌNH HUỐNG 2: BÀI TÌM MUA (SITUATION_FINDING) -> TƯ VẤN SẢN PHẨM KHỚP & CAM KẾT GIÁ TỐT NHẤT
        # =========================================================================
        elif situation == "SITUATION_FINDING":
            # 1. Kiểm tra tìm chuôi
            if any(k in norm_post for k in ["tim chuoi", "can chuoi", "mua chuoi", "chuoi ngon", "chuoi carbon", "khuc noi", "chuoi tg"]):
                templates = [
                    "Bác tìm chuôi carbon thì tham khảo cây TG full carbon kèm nối của em xem sao ạ. Hàng em giữ gìn 99% không tì vết, cầm đầm tay và trợ lực cực thoát bi. Em đang nghỉ game để lại giá tốt nhất thị trường luôn, bao test trực tiếp thoải mái, bác quan tâm nhắn em gửi full ảnh nhé.",
                    "Nếu bác cần cây chuôi carbon đầm chắc, truyền lực tốt thì cây TG full carbon kèm khúc nối này của em chuẩn bài luôn. Em thanh lý nghỉ game giá sốc cho anh em, rẻ hơn nhiều so với mua mới mà chất lượng 99%, bác ưng ib em nha."
                ]
                return {
                    "should_comment": True,
                    "situation": "SITUATION_FINDING (Tìm chuôi)",
                    "matched_product": OUR_PRODUCTS["chuoi_tg"]["title"],
                    "comment_text": random.choice(templates)
                }

            # 2. Kiểm tra tìm ngọn hoặc hỏi các hãng Peri/Fury/Predator/Cuetec...
            elif any(k in norm_post for k in ["tim ngon", "can ngon", "mua ngon", "ngon carbon", "thay ngon", "do ngon", "ngon apex", "ngon mun"]) or any(b in norm_post for b in POPULAR_BRANDS):
                brand_mentioned = [b.capitalize() for b in POPULAR_BRANDS if b in norm_post]
                brand_str = brand_mentioned[0] if brand_mentioned else "các dòng hãng"
                templates = [
                    f"Nếu bác đang tìm ngọn trợ lực đầm tay chuẩn lực thay vì đầu tư quá nhiều vào {brand_str} thì tham khảo ngọn Apex vỏ mun Ebony lõi carbon bên em nhé. Em vừa lên ring với tẩy mới dày cộp, đánh thoát bi và đầm chắc 99%. Em nghỉ game để lại giá cam kết tốt nhất thị trường cho anh em, bác cần clip test ngọn cứ ới em.",
                    f"Bác ngó thử cây ngọn Apex vỏ gỗ mun Ebony lõi carbon của em xem sao. Độ đầm và cảm giác chạm bi cực tốt không thua kém gì {brand_str}, lên ring tẩy sẵn hoàn hảo 99%. Giá thanh lý nghỉ game bao mềm, bác quan tâm nhắn em gửi video check độ thẳng và lực nhé."
                ]
                return {
                    "should_comment": True,
                    "situation": "SITUATION_FINDING (Tìm ngọn / Thay thế hãng)",
                    "matched_product": OUR_PRODUCTS["ngon_apex"]["title"],
                    "comment_text": random.choice(templates)
                }

            # 3. Kiểm tra tìm gậy nhảy (Jump cue)
            elif any(k in norm_post for k in ["gay nhay", "tim nhay", "can nhay", "jump", "thoat bi", "bi te", "nhay coc"]):
                templates = [
                    "Bác cần gậy nhảy thoát bi nhẹ tay thì cây Thunder ngọn carbon size 14 của em chuẩn bài luôn nhé. Nhảy bi tê cực kỳ nhạy, chuôi gỗ đã lên ring bóng loáng ở Phúc Long 99%. Em nghỉ game pass lại giá tốt nhất thị trường cho anh em, bác cần video test nhảy thực tế cứ nhắn em nhé.",
                    "Nhảy bi tê hay bi xa thì dòng Thunder ngọn carbon size 14 này nhảy cực thoát và không tốn sức bác ạ. Cây của em đẹp như mới 99%, em nghỉ game xả giá rất mềm, bác ưng ib em trao đổi nha."
                ]
                return {
                    "should_comment": True,
                    "situation": "SITUATION_FINDING (Tìm gậy nhảy)",
                    "matched_product": OUR_PRODUCTS["gay_nhay_thunder"]["title"],
                    "comment_text": random.choice(templates)
                }

            # 4. Kiểm tra tìm gậy tập chơi / Chinesepool / Học sinh sinh viên
            elif any(k in norm_post for k in ["chinesepool", "tap choi", "hoc sinh", "sinh vien", "gia re", "ngan sach", "tam gia"]):
                templates = [
                    "Tầm tiền học sinh sinh viên mà muốn gậy chuẩn lực đánh chinesepool hoặc lỗ thì bộ Lankou Cơn bão Thanh Xuân 05 gỗ phong này là số 1 trong tầm giá bác ạ. Đánh cực đầm và ổn định, truyền lực đều. Em nghỉ game thanh lý cả bộ 99% giá rẻ nhất thị trường, bác quan tâm nhắn em gửi clip test nhé.",
                    "Mới tập chơi hoặc tìm gậy chuẩn lực thì bộ Lankou Thanh Xuân 05 gỗ phong này đúng bài luôn bác ơi, kiểm soát bi cái rất chính xác. Hàng cá nhân giữ gìn 99%, em thanh lý giá nghỉ game cực sinh viên, bác ib em gửi ảnh chi tiết nha."
                ]
                return {
                    "should_comment": True,
                    "situation": "SITUATION_FINDING (Tìm gậy tập chơi / Chinesepool)",
                    "matched_product": OUR_PRODUCTS["bo_lankou"]["title"],
                    "comment_text": random.choice(templates)
                }

            # 5. Tìm mua chung / hỏi mua đồ cũ chung chung
            else:
                templates = [
                    "Bác đang tìm đồ bi-a thì ghé em tham khảo nhé: em nghỉ game thanh lý toàn bộ đồ cá nhân 99% giá tốt nhất thị trường: ngọn gỗ Apex mun lõi carbon, chuôi TG full carbon kèm nối, bộ Lankou 05, gậy nhảy Thunder. Có xé lẻ chuôi ngọn thoải mái cho anh em, bác cần món nào nhắn em gửi ảnh chi tiết nhé.",
                    "Tiện đây em nghỉ game xả nhanh đồ chất lượng 99%: ngọn mun Apex carbon, chuôi TG full carbon, bộ Lankou Thanh Xuân, gậy nhảy Thunder, bao găng... Cam kết giá mềm nhất cho anh em thiện chí, bác quan tâm ib em tư vấn cụ thể nhé."
                ]
                return {
                    "should_comment": True,
                    "situation": "SITUATION_FINDING (Tìm đồ chung)",
                    "matched_product": OUR_PRODUCTS["full_combo"]["title"],
                    "comment_text": random.choice(templates)
                }

        # =========================================================================
        # TÌNH HUỐNG 3: BÀI THẢO LUẬN CHUNG (SITUATION_DISCUSS) -> XIN PHÉP CHỦ POST KÉ PASS LỊCH SỰ
        # =========================================================================
        else:
            templates = [
                "Xin phép chủ post cho em ké pass ít đồ nghỉ game giá sốc cho anh em: ngọn Apex mun Ebony lõi carbon, chuôi TG full carbon kèm nối, bộ Lankou 05 chinesepool, gậy nhảy Thunder. Tất cả 99% hoàn hảo có lẻ chuôi ngọn, bác nào quan tâm ib em nhé. Chúc chủ thớt và anh em giao lưu vui vẻ!",
                "Em xin phép chủ post ké pass đồ cá nhân nghỉ game: có ngọn gỗ Apex mun lõi carbon, chuôi TG full carbon kèm nối, bộ Lankou Thanh Xuân 05 và gậy nhảy Thunder size 14. Hàng như mới 99%, xé lẻ thoải mái giá siêu mềm, anh em nào cần món gì ới em nha.",
                "Xin phép bác chủ cho em ké bài tí ạ: Em nghỉ game thanh lý lẻ chuôi TG full carbon, ngọn Apex mun lõi carbon, bộ gậy Lankou và gậy nhảy Thunder. Đồ đẹp 99% giá hữu nghị cho anh em đam mê, bác nào quan tâm nhắn em gửi hình nhé."
            ]
            chosen = random.choice(templates)
            return {
                "should_comment": True,
                "situation": "SITUATION_DISCUSS (Ké pass lịch sự)",
                "matched_product": OUR_PRODUCTS["full_combo"]["title"],
                "comment_text": chosen
            }


if __name__ == "__main__":
    engine = ONNXCommentEngine()

    test_scenarios = [
        # --- NHÓM 1: BÀI ĐĂNG BÁN (SITUATION_SALE) ---
        ("Pass lại ngọn mộc Fury ren radial mới 95% giá 1tr5 công khai anh em", "Giao dịch HN"),
        ("Cần bán cây chuôi Peri full carbon không trầy xước giá 3tr2", "Có ship cod"),
        ("Xả cây cơ carbon nguyên bộ kèm bao da giá 4tr cho anh em nhanh gọn", "Inbox em"),

        # --- NHÓM 2: BÀI TÌM MUA (SITUATION_FINDING) ---
        ("Tài chính 2 củ tìm chuôi ngon về ghép ngọn mộc chơi tết các bác ơi", ""),
        ("Tìm ngọn carbon cho cơ peri tầm 2 đến 3 củ ai có không", "Hóng ké"),
        ("Mới tập chơi chinesepool thì nên lấy cây nào tầm giá học sinh sinh viên các bác?", ""),
        ("Cần cây gậy nhảy thoát bi ngon bổ rẻ anh em có pass lại nhé", ""),
        ("Có ai thanh lý đồ bida cũ giá rẻ không em đang cần sắm đồ", ""),

        # --- NHÓM 3: BÀI THẢO LUẬN GIAO LƯU (SITUATION_DISCUSS) ---
        ("Hôm nay giao lưu kèo 50k điểm tại CLB Hà Đông, anh em nào rảnh qua nhé!", "1 slot nhé"),
        ("Theo các bác thì tẩy mềm hay tẩy cứng đánh bi lỗ sướng hơn?", "Mỗi người 1 gu"),
        ("Cảnh báo nick FB ảo chuyên lừa cọc anh em mua bán cẩn thận", "Cảm ơn bác")
    ]

    print("\n" + "=" * 70)
    print("🎯 KIỂM TRA ĐỘ THÔNG MINH THEO ĐÚNG 3 TÌNH HUỐNG THỰC TẾ")
    print("=" * 70)

    for idx, (post, cmts) in enumerate(test_scenarios, 1):
        res = engine.generate_contextual_comment(post, cmts)
        print(f"\n[Scenario {idx}] Bài viết: \"{post}\"")
        print(f"📌 Phân loại tình huống: {res['situation']}")
        print(f"📦 Nhắm tới: {res['matched_product']}")
        print(f"💬 Bình luận sinh ra:\n\"{res['comment_text']}\"")
        print("-" * 70)
