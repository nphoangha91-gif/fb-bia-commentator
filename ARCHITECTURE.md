# Hệ Thống Tự Động Facebook Billiards Ecosystem
## Kiến Trúc Nâng Cấp: Dual-Bot & Diamond Groups Dynamic Engine

Tài liệu mô tả chi tiết toàn bộ kiến trúc hệ thống, quy trình vận hành và thuật toán phân loại tương tác được nâng cấp cho hệ sinh thái tự động hóa Facebook Bi-a (`fb-bia-poster` & `fb-bia-commentator`).

---

## 1. Triết Lý Vận Hành 2 Bot (Dual-Agent Strategy)

Hệ thống kết hợp 2 tài khoản Facebook chuyên biệt với hai mục tiêu chiến lược bổ trợ lẫn nhau:

```text
┌─────────────────────────────────────────────────────────────────────────────┐
│ 1. BOT ĐĂNG BÀI (fb-bia-poster - Tài khoản: An Tâm)                         │
│  • Mục tiêu: PHỦ RỘNG TẤT CẢ NHÓM (SEO Keyword Coverage).                  │
│  • Phạm vi: Quét luân phiên 100% danh sách 626 nhóm bi-a.                   │
│  • Tác dụng: Tạo vết từ khóa trên công cụ tìm kiếm Facebook. Khi khách tìm │
│    "mua cơ bida", "thanh lý cơ", "cơ fury", "ngọn carbon"... bài viết luôn │
│    xuất hiện trên top kết quả ở mọi hội nhóm.                               │
│  • Tần suất: Chạy định kỳ vào phút thứ :25 mỗi giờ.                         │
├─────────────────────────────────────────────────────────────────────────────┤
│ 2. BOT BÌNH LUẬN (fb-bia-commentator - Tài khoản: Tran Minh)                │
│  • Mục tiêu: ĐÁNH TẬP TRUNG NHÓM KIM CƯƠNG (Deep Diamond Snipping).         │
│  • Cơ chế linh hoạt:                                                        │
│    - 💎 Nhóm Kim Cương (Diamond): Bình luận 10 - 15 bài viết mới nhất.      │
│    - ⚪ Nhóm Thường (Normal): Bình luận 1 - 2 bài viết duy trì hiện diện.    │
│  • Tác dụng: Tiếp cận trực tiếp khách hàng thật đang thảo luận, hỏi mua      │
│    bằng bình luận đối thoại tự nhiên, thông minh (ONNX Contextual Engine).  │
│  • Tần suất: Chạy 16 ca/ngày vào phút thứ :50 mỗi giờ (7h50 - 22h50 VN).    │
└─────────────────────────────────────────────────────────────────────────────┘
```

---

## 2. Kiến Trúc Phân Hạng Nhóm Động (Dynamic Tiering Engine)

Để tối ưu hóa số lượng chuyển đổi và tiết kiệm hạn ngạch Facebook, toàn bộ 637 nhóm bi-a được phân cấp thành các tầng:

### A. Công thức tính Điểm Tiềm Năng (Diamond Score: 0 – 100)
Dựa trên mẫu 10–12 bài viết mới nhất được trích xuất từ DOM:
$$\text{Score} = \text{Comment Pts (max 40)} + \text{Reaction Pts (max 20)} + \text{Recency Pts (max 25)} + \text{Discussion Pts (max 15)}$$

* **Mật độ Bình luận (40%):** $(\text{Tổng BL} \times 3) + (\text{BL Trung bình/bài} \times 5)$. Đo lường số người hỏi mua (*"xin giá", "check ib", "giao lưu"*).
* **Lượt Cảm xúc (20%):** $(\text{Tổng Like} \times 1.5) + (\text{Like Trung bình/bài} \times 2)$. Đo lường lượng người lướt đọc bài.
* **Độ Tươi Mới (25%):**
  - Bài mới nhất $\le 1$ giờ: **25 điểm**
  - Bài mới nhất $\le 6$ giờ: **20 điểm**
  - Bài mới nhất $\le 24$ giờ: **15 điểm**
  - Bài mới nhất $\le 3$ ngày: **5 điểm**
* **Tỷ lệ Bài có Thảo luận (15%):** Số lượng bài viết có $\ge 1$ tương tác $\times 3$.

### B. Tiêu chuẩn phân hạng & Hành vi của Bot:

| Phân Hạng | Tiêu Chuẩn | Hành Vi Cuộn Trang | Hạn Mức Bình Luận | Mục Tiêu |
| :--- | :--- | :--- | :---: | :--- |
| 💎 **DIAMOND** | Điểm $\ge 35$ hoặc $\ge 6$ bình luận mẫu | Cuộn sâu **6 chu kỳ**, nạp **35–40 bài** mới | **10 – 15 bài/nhóm** | Tối đa hóa tiếp cận khách hàng đang có nhu cầu thực tế |
| ⚪ **NORMAL** | Điểm 15 – 34 | Cuộn tiêu chuẩn **4 chu kỳ**, nạp **20 bài** | **1 – 2 bài/nhóm** | Giữ hiện diện thương hiệu, tiết kiệm thời gian ca chạy |
| ⚠️ **DEAD/BLOCKED**| 0 bài viết, nhóm đóng hoặc bị FB chặn | Dừng kiểm tra | **0 bài** (Bỏ qua) | Chống nghẽn tiến trình |

---

## 3. Quy Trình Vòng Lặp Chu Kỳ & Chống Spam Tuyệt Đối

```mermaid
graph TD
    A[Bắt đầu Ca Chạy Mới] --> B[Đọc facebook_joined_groups.json]
    B --> C{Còn nhóm chưa duyệt?}
    C -- Còn nhóm --> D[Chọn nhóm kế tiếp theo Round-Robin]
    C -- Đã hết 637 nhóm --> E[🎉 Tự Động Reset visited_groups = []]
    E --> D
    D --> F{Nhóm có phải Diamond?}
    F -- Phải 💎 --> G[Target: 10 - 15 bài | Nạp sâu 35-40 bài]
    F -- Không ⚪ --> H[Target: 1 - 2 bài | Nạp 20 bài]
    G --> I[Lọc bỏ bài đã comment: records + DOM check]
    H --> I
    I --> J[Ưu tiên bài có thảo luận lên đầu]
    J --> K[ONNX Engine đọc hiểu & sinh lời thoại]
    K --> L[Gõ phím tự nhiên + Gửi bình luận]
    L --> M[Lưu Post ID vào records & Chụp ảnh chứng minh]
    M --> N{Đạt chỉ tiêu nhóm?}
    N -- Chưa --> L
    N -- Đã đủ --> O[Giãn cách an toàn 35-60s -> Nhóm tiếp theo]
```

### Cơ chế bảo vệ 3 tầng không bao giờ comment trùng bài:
1. **Lớp 1 - Database Post ID Vĩnh Viễn (`records`):**
   - Lưu trữ toàn bộ ID bài viết đã từng bình luận trong `commented_history.json` (hiện có $\approx 300$ bài).
   - Khi reset chu kỳ vòng lặp, `records` **KHÔNG BAO GIỜ BỊ XÓA**.
2. **Lớp 2 - Kiểm tra trực tiếp trên Facebook DOM (`has_my_comment`):**
   - Quét thẻ avatar `Tran Minh` hoặc nút *Chỉnh sửa/Xóa bình luận* của chính mình trên khối bài viết. Nếu có $\rightarrow$ Bỏ qua ngay lập tức.
3. **Lớp 3 - Chu kỳ 2–3 ngày tự nhiên:**
   - Với 637 nhóm chia cho 16 ca/ngày, đúng **2 – 3 ngày** bot mới quay trở lại nhóm cũ.
   - Lúc này, các bài cũ đã bị trôi xuống dưới và bot **chỉ bình luận vào những bài viết mới tinh vừa xuất hiện trong 2-3 ngày qua**.

---

## 4. Thuật Toán Trí Tuệ Nhân Tạo ONNX Contextual Engine

Bot không dùng mẫu cố định mà phân tích nội dung theo 3 tình huống mua/bán thực tế:

1. **Tình huống 1: BÀI ĐĂNG BÁN (Cross-Selling / Gợi ý bổ trợ)**
   - Khách bán ngọn $\rightarrow$ Bot giới thiệu chuôi TG full carbon ghép đôi.
   - Khách bán chuôi $\rightarrow$ Bot giới thiệu ngọn gỗ Apex mun Ebony lõi carbon.
   - Khách bán cơ lỗ $\rightarrow$ Bot giới thiệu thêm gậy nhảy Thunder hỗ trợ thế bi khó.
2. **Tình huống 2: BÀI TÌM MUA (Targeted Matching)**
   - Khách tìm đồ theo ngân sách học sinh sinh viên $\rightarrow$ Giới thiệu bộ Lankou 05.
   - Khách tìm ngọn đầm lực thay ngọn mộc $\rightarrow$ Giới thiệu ngọn Apex mun lõi carbon.
3. **Tình huống 3: BÀI THẢO LUẬN GIAO LƯU (Polite Guest Pass)**
   - Lịch sự xin phép chủ post cho ké pass nhanh đồ cá nhân nghỉ game giá thanh lý.

---

## 5. Danh Mục Công Cụ & File Cấu Trúc

| Tên File | Vai Trò & Chức Năng |
| :--- | :--- |
| `github_cron_commenter.py` | Engine thực thi chính của bot comment trên GitHub Actions |
| `comment_workflow_core.py` | Bộ điều khiển Playwright: nạp bài theo CHRONOLOGICAL, kiểm tra DOM, gõ phím |
| `onnx_comment_engine.py` | Bộ não AI phân loại ngữ cảnh 3 tình huống & sinh lời thoại |
| `filter_diamond_groups.py` | Công cụ tự động quét, đo lường tương tác và lọc danh sách Nhóm Kim Cương |
| `facebook_joined_groups.json` | Database 637 nhóm bi-a (đã xếp Top Nhóm Kim Cương lên đầu) |
| `diamond_groups.json` | Danh sách trích xuất các nhóm đạt chuẩn Kim Cương |
| `DIAMOND_GROUPS_REPORT.md` | Bảng xếp hạng điểm tiềm năng chi tiết |
| `commented_history.json` | Sổ cái lịch sử lưu trữ `visited_groups` và `records` post ID |
| `.github/workflows/facebook_comment_cron.yml` | Lịch trình GitHub Actions chạy 16 ca/ngày tự động |

---

## 6. Cơ Chế Phòng Vệ Chống Chiếm Quyền Khung Chat Messenger (Messenger Anti-Hijack Defense)

Khi chạy tài khoản trên trình duyệt Facebook Desktop, người dùng hoặc Facebook có thể tự động mở các cửa sổ chat dock nổi ở góc dưới bên phải màn hình. Để đảm bảo **TUYỆT ĐỐI KHÔNG BAO GIỜ** gõ nhầm nội dung bình luận vào hộp thư cá nhân của bạn bè/khách hàng, hệ thống trang bị cơ chế bảo vệ 4 tầng độc lập:

```text
┌─────────────────────────────────────────────────────────────────────────────┐
│ 🛡️ 4 TẦNG PHÒNG VỆ CHỐNG GÕ NHẦM MESSENGER                                  │
├─────────────────────────────────────────────────────────────────────────────┤
│ 1. Cô Lập Selector 100% (Strict Scoping):                                   │
│    - Xóa bỏ hoàn toàn fallback toàn trang 'div[role="textbox"].last'.       │
│    - Ô nhập bắt buộc phải là con đẻ của phần tử bài viết (loc).            │
│ 2. Dọn Dẹp Cửa Sổ Nổi (Auto-Close Dock):                                    │
│    - Tự động phát hiện và đóng toàn bộ tab chat Messenger ngay khi vào nhóm │
│      và trước mỗi lần tương tác bài viết (close_all_chat_windows).          │
│ 3. Kiểm Tra Cây Phả Hệ DOM (Ancestry Guard):                                │
│    - Hàm is_messenger_element thẩm tra tổ tiên của ô nhập. Nếu nằm trong     │
│      [data-pagelet="ChatTab"] hoặc [aria-label*="Đoạn chat"] -> Hủy ngay!   │
│ 4. Kiểm Tra Tiêu Điểm Bàn Phím Thời Gian Thực (ActiveElement Guard):        │
│    - Thẩm định document.activeElement sau khi click và ngay trước khi       │
│      nhấn Enter. Nếu tiêu điểm là Messenger -> Bấm Escape x2 & Hủy bỏ!      │
└─────────────────────────────────────────────────────────────────────────────┘
```


---

## 6. Cơ Chế Phòng Vệ Chống Chiếm Quyền Khung Chat Messenger (Messenger Anti-Hijack Defense)

Khi chạy tài khoản trên trình duyệt Facebook Desktop, người dùng hoặc Facebook có thể tự động mở các cửa sổ chat dock nổi ở góc dưới bên phải màn hình. Để đảm bảo **TUYỆT ĐỐI KHÔNG BAO GIỜ** gõ nhầm nội dung bình luận vào hộp thư cá nhân của bạn bè/khách hàng, hệ thống trang bị cơ chế bảo vệ 4 tầng độc lập:

```text
┌─────────────────────────────────────────────────────────────────────────────┐
│ 🛡️ 4 TẦNG PHÒNG VỆ CHỐNG GÕ NHẦM MESSENGER                                  │
├─────────────────────────────────────────────────────────────────────────────┤
│ 1. Cô Lập Selector 100% (Strict Scoping):                                   │
│    - Xóa bỏ hoàn toàn fallback toàn trang 'div[role="textbox"].last'.       │
│    - Ô nhập bắt buộc phải là con đẻ của phần tử bài viết (loc).            │
│ 2. Dọn Dẹp Cửa Sổ Nổi (Auto-Close Dock):                                    │
│    - Tự động phát hiện và đóng toàn bộ tab chat Messenger ngay khi vào nhóm │
│      và trước mỗi lần tương tác bài viết (close_all_chat_windows).          │
│ 3. Kiểm Tra Cây Phả Hệ DOM (Ancestry Guard):                                │
│    - Hàm is_messenger_element thẩm tra tổ tiên của ô nhập. Nếu nằm trong     │
│      [data-pagelet="ChatTab"] hoặc [aria-label*="Đoạn chat"] -> Hủy ngay!   │
│ 4. Kiểm Tra Tiêu Điểm Bàn Phím Thời Gian Thực (ActiveElement Guard):        │
│    - Thẩm định document.activeElement sau khi click và ngay trước khi       │
│      nhấn Enter. Nếu tiêu điểm là Messenger -> Bấm Escape x2 & Hủy bỏ!      │
└─────────────────────────────────────────────────────────────────────────────┘
```
