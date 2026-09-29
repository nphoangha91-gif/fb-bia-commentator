# Facebook ONNX Contextual Auto-Comment Agent (`bia commentator`)

Hệ thống tự động quét 20 bài viết mới nhất trong các nhóm bi-a Facebook, sử dụng **ONNX Model & Hybrid Semantic Engine** để đọc hiểu ngữ cảnh bài viết và bình luận hiện có, tự động từ chối các bài viết không liên quan để **chống spam**, và tạo bình luận đối thoại tự nhiên mang phong cách cơ thủ thực thụ để tư vấn/bán các sản phẩm trong `content.txt`.

---

## 🌟 Điểm nổi bật & Khác biệt hoàn toàn với Bot Spam

1. **Hiểu ngữ cảnh bài viết trước khi nói**:
   - Không quăng quảng cáo hàng loạt vào các bài viết rủ kèo giao lưu, cảnh báo lừa đảo hay bài viết không liên quan.
   - Chỉ tham gia khi bài viết có nhu cầu tìm mua, tư vấn, nâng cấp hoặc thảo luận về cơ gậy/ngọn/phụ kiện bi-a.
2. **Đối thoại tự nhiên, không rập khuôn**:
   - Trả lời đúng vào câu hỏi hoặc thắc mắc của tác giả trước (ví dụ: hỏi loại ren chuôi, tư vấn chọn gậy phong cho chinesepool, cảm giác đánh ngọn carbon...).
   - Khéo léo giới thiệu đúng món đồ liên quan trong danh mục `content.txt`.
3. **Chống trùng lặp tuyệt đối (Double Duplicate Check)**:
   - Lưu trữ toàn bộ ID bài viết đã từng bình luận vào `commented_history.json`.
   - Kiểm tra trực tiếp trên DOM để không bao giờ bình luận 2 lần trên cùng một bài viết.
4. **Hạn mức bình luận linh hoạt theo Hạng nhóm (Dynamic Tiered Limits)**:
   - 💎 **Nhóm Kim Cương (Diamond Groups)**: Bình luận **10 – 15 bài viết mới nhất**, nạp sâu 35–40 bài và ưu tiên bài có người đang thảo luận.
   - ⚪ **Nhóm thường (Normal Groups)**: Bình luận **1 – 2 bài viết** để duy trì hiện diện và tối ưu thời gian ca chạy.
5. **An toàn tài khoản cao nhất (Anti-Ban Guard)**:
   - Giãn cách ngẫu nhiên kiểu người thật (25s–45s giữa các bình luận, 35s–60s giữa các nhóm).
   - Mô phỏng tốc độ gõ phím tự nhiên (keystroke jitter 15ms–32ms).
   - Chu kỳ quay vòng 2–3 ngày: Duyệt hết 637 nhóm sẽ tự động quay vòng lại từ đầu, bảo lưu 100% ID bài cũ để không bao giờ comment trùng lặp.

---

## 📖 Tài liệu Kiến trúc Hệ thống

Xem chi tiết kiến trúc nâng cấp, công thức tính điểm và luồng hoạt động tại: **[ARCHITECTURE.md](./ARCHITECTURE.md)**

---

## 📦 Danh mục sản phẩm tư vấn (`content.txt`)

- **Ngọn Apex mun Ebony lõi carbon**: Tư vấn cho người tìm ngọn carbon đầm tay, trợ lực, thay ngọn mộc.
- **Chuôi TG full carbon kèm nối**: Tư vấn cho người tìm chuôi carbon, cần khúc nối, nâng cấp cán cơ.
- **Bộ Lankou Cơn bão Thanh Xuân 05 gỗ phong**: Tư vấn cho người mới tập chơi chinesepool hoặc tìm combo gậy giá tốt chuẩn lực.
- **Gậy nhảy ngọn carbon Thunder size 14**: Tư vấn cho người cần gậy jump thoát bi, nhảy bi tê nhẹ tay.
- **Thanh lý phụ kiện / nghỉ game (Lẻ chuôi lẻ ngọn)**: Tư vấn cho các bài viết hỏi mua đồ thanh lý chung hoặc gom phụ kiện bao găng.

---

## 🚀 Hướng dẫn sử dụng

### 1. Cài đặt môi trường
```bash
pip install -r requirements.txt
playwright install chromium --with-deps
```

### 2. Quét & Lọc Nhóm Kim Cương (Diamond Groups Evaluator)
```bash
# Quét 20 nhóm kế tiếp
python filter_diamond_groups.py --limit 20

# Quét toàn bộ nhóm trong database
python filter_diamond_groups.py
```

### 3. Chạy thử nghiệm cào bài & sinh bình luận (DRY RUN - An toàn 100%)
Chế độ này sẽ vào nhóm, trích xuất bài mới nhất, đọc nội dung, hiển thị các bình luận đề xuất ra màn hình console và **KHÔNG** bấm gửi lên Facebook:
```bash
DRY_RUN=true TOTAL_GROUPS_LIMIT=1 python github_cron_commenter.py
```

### 4. Chạy bình luận thật (LIVE COMMENT)
```bash
DRY_RUN=false TOTAL_GROUPS_LIMIT=5 python github_cron_commenter.py
```

---

## ⚙️ Thiết lập chạy tự động trên GitHub Actions (Cronjob)

1. Đưa toàn bộ mã nguồn lên repository GitHub.
2. Cài đặt các **GitHub Secrets** (`Settings` -> `Secrets and variables` -> `Actions`):
   - `FB_COOKIES_JSON`: Chuỗi JSON trích xuất từ file `fb_cookies.json`.
   - `FB_USERNAME`: Tên/SĐT đăng nhập Facebook (dự phòng).
   - `FB_PASSWORD`: Mật khẩu Facebook (dự phòng).
3. Workflow `.github/workflows/facebook_comment_cron.yml` sẽ tự động kích hoạt **16 ca mỗi ngày** (vào phút thứ :50 mỗi giờ từ 07:50 đến 22:50 giờ Việt Nam).

