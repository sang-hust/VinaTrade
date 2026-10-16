# Nguồn dữ liệu và dịch vụ cần bổ sung

Cập nhật 16/10/2026. Đối chiếu 65 yêu cầu chức năng (FR) trong tài liệu VNSignal AI v1.2: app đạt ≈ 84% (P1 ≈ 90%).
Phần còn thiếu chủ yếu do **chưa có nguồn dữ liệu**, không phải do code. Hiện app dùng miễn phí API công khai của
SSI iBoard (danh sách mã, giá ngày, giá tham chiếu/trần/sàn) và Vietcap (giá dự phòng, hồ sơ công ty, BCTC).
Các API công khai này không có hợp đồng, có thể đổi hoặc chặn bất cứ lúc nào (rủi ro "Bản quyền dữ liệu" trong kế hoạch, mục 9).

## 1. Dữ liệu thị trường (cần mua để đạt đủ tài liệu)

| # | Dữ liệu cần | Mở khoá yêu cầu | Hiện trạng | Nhà cung cấp gợi ý (cần hỏi báo giá) |
|---|---|---|---|---|
| 1 | **Giá realtime trong phiên** (tick / nến 1 phút, có streaming) | FR-06, FR-24 cảnh báo ≤ 60 giây, FR-49 kế hoạch nhắc đúng lúc, NFR-02 | Quét 5 phút/lần qua SSI iBoard, chỉ mã đang theo dõi | **SSI FastConnect Data** (có WebSocket/streaming, kế hoạch đã nêu); DNSE, VPS, TCBS nếu có gói dữ liệu cho bên thứ ba |
| 2 | **Giao dịch khối ngoại và tự doanh** theo mã, theo ngày | FR-06, M10 dòng tiền khối ngoại/tự doanh, điểm ngành (dòng tiền) | Chưa có | SSI FastConnect Data; FiinTrade; Vietstock |
| 3 | **Sự kiện quyền**: cổ tức tiền/cổ phiếu, phát hành thêm, chia tách, GDKHQ, ĐHCĐ, ngày công bố BCTC | FR-09 điều chỉnh giá, FR-37 lịch sự kiện, kiểm tra trước khi mua (tiêu chí "BCTC/GDKHQ trong 5 phiên"), điểm rủi ro (pha loãng) | Bảng `corporate_actions` có sẵn nhưng trống | **FiinTrade / FiinPro API**; **Vietstock Finance API**; nguồn công bố của HOSE/HNX (miễn phí, phải tự bóc tách) |
| 4 | **Giao dịch nội bộ**: lãnh đạo, cổ đông lớn, người liên quan (đăng ký và kết quả), **cầm cố cổ phiếu** | FR-46 (P1, chưa làm), FR-45 điểm rủi ro DN (15 + 10 điểm) | Bảng `insider_transactions` có sẵn nhưng trống | FiinTrade; Vietstock; công bố thông tin HOSE/HNX/UBCKNN (miễn phí, phải tự bóc tách) |
| 5 | **Ý kiến kiểm toán, nộp BCTC chậm**, diện cảnh báo/kiểm soát chính thức | FR-45 điểm rủi ro DN | Chỉ có diện cảnh báo từ SSI | FiinTrade; Vietstock |
| 6 | **Tin tức doanh nghiệp + báo cáo phân tích của CTCK** (có gắn mã) | FR-08, FR-32 AI tóm tắt và chấm cảm xúc tin, tab Tin tức, bản tin trước phiên | Chưa có | Vietstock; CafeF/VnEconomy RSS (miễn phí, cần kiểm tra điều khoản); báo cáo CTCK (VCBS, FPTS, SSI Research) |
| 7 | **Vĩ mô**: GDP, CPI, lãi suất điều hành, tín dụng, tỷ giá, FDI, PMI, giá hàng hoá (dầu, thép, phân bón) | FR-08, FR-22 ngành hưởng lợi theo vĩ mô (M5) | Admin bật tay yếu tố vĩ mô | Tổng cục Thống kê, Ngân hàng Nhà nước (miễn phí, cập nhật tay hoặc bóc tách); Trading Economics API; FiinTrade (gói vĩ mô) |
| 8 | **Danh mục & kỳ cơ cấu quỹ ETF**, lịch đáo hạn phái sinh VN30 | FR-52 | Chưa có | FiinTrade; công bố của các quỹ (VanEck, FTSE, Diamond, Fubon); HNX phái sinh |
| 9 | **Dự phóng lợi nhuận / đồng thuận giá mục tiêu** | FR-52 dự báo BCTC, định giá P/E dự phóng (mục 3.3b) | Dùng EPS 4 quý gần nhất | FiinTrade (consensus); báo cáo CTCK |
| 10 | **Danh sách mã cho vay ký quỹ** theo từng CTCK | M12 kiểm tra trước khi mua, ký quỹ (FR-47) | Admin nhập tay ở trang quản trị | Mỗi CTCK công bố file định kỳ (miễn phí, cần tải và nhập) |

**Gợi ý mua theo thứ tự:** (1) giá realtime → (3) + (4) sự kiện quyền và giao dịch nội bộ (thường bán cùng gói dữ liệu cơ bản) → (6) tin tức → (7) vĩ mô.
Một gói **FiinTrade** hoặc **Vietstock** thường phủ được (2)(3)(4)(5)(8)(9); **SSI FastConnect** phủ (1)(2).
Trước khi mua: hỏi rõ điều khoản **cho phép hiển thị lại cho người dùng khác** (bạn bè được mời), không chỉ dùng cá nhân.

Khi có API: viết adapter mới trong `backend/app/ingestion/adapters/` cùng interface với `ssi.py`, `vci.py`; đổi ưu tiên ở Admin → Dữ liệu & tác vụ.

## 2. Dịch vụ để bật các kênh đã có code

| Dịch vụ | Cần gì | Mở khoá | Chi phí |
|---|---|---|---|
| **Bot Telegram** | Token từ @BotFather | Cảnh báo qua Telegram, lệnh `/gia FPT`, `/canhbao`, `/thitruong` | Miễn phí |
| **Email (SMTP)** | Brevo / Resend / Gmail app password | Quên mật khẩu, email kích hoạt, báo cáo cuối ngày | Miễn phí ở mức nhỏ |
| **Firebase (project mới)** | `google-services.json`, `GoogleService-Info.plist`, service account JSON | Thông báo đẩy Android/iOS/Web | Miễn phí |
| **Apple Developer Program** | Tài khoản trả phí, khoá APNs (.p8) | Push iOS, TestFlight, app không hết hạn sau 7 ngày | 99 USD/năm |
| **Google Play Console** | Tài khoản nhà phát triển | Phát hành Android | 25 USD một lần |
| **Tên miền** | Ví dụ `vinatrade.vn` | Thay `*.up.railway.app`, link mời đẹp | ~300–500 nghìn/năm |

## 3. Việc làm được ngay, không cần nguồn mới

- Bổ sung chỉ báo còn thiếu: Ichimoku, Parabolic SAR, Keltner, VWAP, Fibonacci, Volume Profile, mẫu nến (Engulfing, Hammer, Doji…).
- Định giá DCF.
- Cho người dùng tự chạy backtest chiến lược (FR-34) — engine `backfill.py` đã có.
- Giao dịch thử tự khớp theo giá thật (FR-55).
- Chuyển Railway sang vùng Singapore để giảm độ trễ.
