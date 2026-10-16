# Nguồn dữ liệu của Vinatrade

Cập nhật 16/10/2026. Mỗi địa chỉ dưới đây đã được gọi thử thật ngày 16/10/2026 (mã thử: FPT).
Tất cả là **API công khai không chính thức** của các công ty chứng khoán / báo: không có hợp đồng, không cần khoá,
có thể đổi định dạng hoặc chặn bất cứ lúc nào. Khi dùng cho nhiều người, cần xem điều khoản sử dụng (kế hoạch, mục 9).
Mỗi nguồn được bọc trong một adapter ở `backend/app/ingestion/adapters/` để thay nguồn không ảnh hưởng phần còn lại.

> **16/10/2026 tối:** đã tích hợp các nguồn B#1–#6, #8, #11 (khối ngoại toàn sàn tính từ VNDirect thay CafeF), #12 — xem bảng A2 bên dưới.
> Chưa dùng: #7 cổ đông Vietcap, #9 chỉ số VNDirect, #10 giá VNDirect (adapter đã có `daily_history`, chưa bật làm dự phòng), #13 World Bank, #14 tỷ giá.

## A. Đang sử dụng

| Nguồn | Địa chỉ | Dữ liệu lấy về | Dùng cho | Tác vụ / tần suất |
|---|---|---|---|---|
| SSI iBoard – danh sách mã | `iboard-query.ssi.com.vn/stock/exchange/{hose,hnx,upcom}` | Mã, tên, sàn, số CP niêm yết, giá tham chiếu/trần/sàn, giá khớp, diện cảnh báo | Danh sách mã, diện cảnh báo/kiểm soát, giá trong phiên | `eod.universe` hằng ngày; quét 5 phút trong phiên (mã đang theo dõi) |
| SSI iBoard – nhóm VN30 | `iboard-query.ssi.com.vn/stock/group/VN30` | Thành phần VN30 | Cờ VN30, bộ lọc | Hằng ngày |
| SSI iBoard – giá lịch sử | `iboard-api.ssi.com.vn/statistics/charts/history?resolution=1D` | OHLCV ngày đã điều chỉnh, VN-Index, VN30, HNX-Index | Chỉ báo, nền giá, chấm điểm, biểu đồ, trạng thái thị trường | `eod.prices` 15:05, nguồn **chính** |
| Vietcap – danh sách mã | `trading.vietcap.com.vn/api/price/symbols/getAll` | Mã, tên ngắn, mã ngành ICB cấp 2 | Phân ngành, điểm ngành | Hằng ngày |
| Vietcap – biểu đồ giá | `trading.vietcap.com.vn/api/chart/OHLCChart/gap-chart` | OHLCV ngày + giá trị GD, UPCoM-Index | Nguồn **dự phòng** khi SSI lỗi; chỉ số UPCoM | Khi SSI lỗi |
| Vietcap – hồ sơ công ty | `…/iq-insight-service/v1/company/{mã}` | Ngành ICB cấp 4, free-float, sở hữu NN/Nhà nước, ngày niêm yết, giới thiệu, cổ tức/CP, khuyến nghị Vietcap | Hồ sơ mã, tỷ suất cổ tức | `fundamentals_sync` 18:00 |
| Vietcap – báo cáo tài chính | `…/company/{mã}/financial-statement?section=INCOME_STATEMENT/BALANCE_SHEET/CASH_FLOW` | KQKD, CĐKT, LCTT theo quý và năm từ 2015 | Chỉ số TTM (EPS, P/E, P/B, ROE…), định giá, điểm cơ bản, điểm rủi ro DN | 18:00 hằng ngày |
| Claude API (Anthropic) | `api.anthropic.com` (có khoá) | — | Câu kết luận thị trường, câu kết luận từng mã, trợ lý AI, huấn luyện viên | Sau EOD; theo câu hỏi |

### A2. Thêm ngày 16/10/2026

| Nguồn | Dữ liệu | Lưu vào | Dùng cho | Tác vụ |
|---|---|---|---|---|
| Vietcap `…/company/{mã}/insider-transaction` | Giao dịch nội bộ (đăng ký + kết quả) | `insider_transactions` | FR-46; điểm rủi ro DN (nội bộ bán ròng 90 ngày); lý do/điểm trừ ở Phân tích mã; cảnh báo "lãnh đạo đăng ký bán"; trường lọc `insider_net_90d` | `eod.extras` (mã GTGD ≥ 1 tỷ + mã đang theo dõi) |
| VNDirect `v4/events` (locale VN) | Cổ tức tiền/CP, thưởng, phát hành thêm, ĐHCĐ, chốt quyền, diện kiểm soát/nhắc nhở/tạm ngừng/hủy niêm yết | `corporate_actions` | Lịch sự kiện (FR-37), tiêu chí "sự kiện trong 5 phiên" của kiểm tra trước khi mua, tỷ suất cổ tức thực trả, pha loãng và "chậm nộp BCTC" trong điểm rủi ro, cảnh báo GDKHQ | `eod.extras` |
| VNDirect `v4/foreigns`, `v4/proprietary_trading` | Khối ngoại và tự doanh mua/bán theo mã, theo ngày | `investor_flows` | Thẻ khối ngoại ở Thị trường, tab Dòng tiền & nội bộ, cảnh báo gom/xả, trường lọc `foreign_net_5d/20d`, `prop_net_5d` | `eod.extras` (3 phiên gần nhất) |
| VNDirect `v4/recommendations` | Khuyến nghị và giá mục tiêu của CTCK | `broker_recommendations` | Giá mục tiêu trung bình, `consensus_upside_pct` | `eod.extras` |
| RSS CafeF, Vietstock, VnExpress, VnEconomy | Tiêu đề, tóm tắt, link | `news_articles`, `news_stock_links` | Tab Tin tức, tin thị trường, Claude chấm cảm xúc và lọc mã, cảnh báo tin tiêu cực, công cụ `get_news` của trợ lý | `news_sync` mỗi 30 phút 6:00–22:00 |

Nạp lịch sử một lần: `python -m app.ingestion.extras 60` hoặc Admin → chạy tác vụ `extras_backfill`.

## B. Miễn phí, đã thử gọi được — có thể thêm

| # | Nguồn | Địa chỉ | Dữ liệu | Mục đích / yêu cầu mở khoá | Ưu tiên |
|---|---|---|---|---|---|
| 1 | **Vietcap – giao dịch nội bộ** | `…/company/{mã}/insider-transaction?page=0&size=50` | Lãnh đạo/cổ đông lớn đăng ký và kết quả mua bán: người giao dịch, số CP trước/sau, đăng ký, thực hiện, tỷ lệ sở hữu, ngày công bố, link nguồn (FPT: 273 bản ghi) | **FR-46** (P1 duy nhất chưa làm) → bảng `insider_transactions`; **điểm rủi ro DN** (lãnh đạo bán ròng, 15 điểm); cảnh báo "lãnh đạo đăng ký bán" | **Cao** |
| 2 | **VNDirect – sự kiện quyền** | `api-finfo.vndirect.com.vn/v4/events?q=code:{mã}~group:investorRight` | Cổ tức tiền, cổ phiếu thưởng, phát hành thêm, niêm yết bổ sung, ngày GDKHQ, tỷ lệ | **FR-37** lịch sự kiện; **kiểm tra trước khi mua** (tiêu chí "GDKHQ/BCTC trong 5 phiên"); **pha loãng** trong điểm rủi ro; tỷ suất cổ tức chính xác → bảng `corporate_actions` | **Cao** |
| 3 | **VNDirect – khối ngoại** | `api-finfo.vndirect.com.vn/v4/foreigns?q=code:{mã}` | Mua/bán/ròng của NĐT nước ngoài theo mã, theo ngày (giá trị, KL) | **FR-06**, M10 dòng tiền khối ngoại, cảnh báo "khối ngoại gom/xả mạnh", điểm ngành (dòng tiền) | Cao |
| 4 | **SSI iBoard – khối ngoại trong phiên** | trong `stock/exchange/{sàn}` (đang gọi sẵn): `buyForeignQtty/Value`, `sellForeignQtty/Value`, `remainForeignQtty` | Khối ngoại mua/bán **trong phiên**, room còn lại | Cùng mục đích #3 nhưng realtime; không tốn thêm request | Cao |
| 5 | **VNDirect – tự doanh** | `api-finfo.vndirect.com.vn/v4/proprietary_trading?q=code:{mã}` | Tự doanh CTCK mua/bán theo mã | FR-06 (tự doanh), M10 | Trung bình |
| 6 | **VNDirect – cổ đông lớn** | `api-finfo.vndirect.com.vn/v4/shareholders?q=code:{mã}` | Cổ đông lớn, số CP, % sở hữu, ngày hiệu lực | Hồ sơ mã; theo dõi thay đổi sở hữu | Trung bình |
| 7 | **Vietcap – cổ đông** | `…/company/{mã}/shareholder` | Danh sách cổ đông, lãnh đạo | Hồ sơ mã; nối người giao dịch nội bộ với chức vụ | Thấp |
| 8 | **VNDirect – khuyến nghị CTCK** | `api-finfo.vndirect.com.vn/v4/recommendations?q=code:{mã}` | Công ty, khuyến nghị (BUY…), giá mục tiêu, ngày báo cáo, chuyên viên | **FR-08/M8** "tổng hợp nguồn phân tích": giá mục tiêu đồng thuận; định giá P/E dự phóng | Trung bình |
| 9 | **VNDirect – chỉ số tài chính** | `api-finfo.vndirect.com.vn/v4/ratios/latest?filter=ratioCode:…&where=code:{mã}` | P/E, vốn hoá, … theo VNDirect | **Đối chiếu** chỉ số tự tính (NFR-07 đối chiếu 2 nguồn) | Thấp |
| 10 | **VNDirect – giá ngày** | `api-finfo.vndirect.com.vn/v4/stock_prices?q=code:{mã}` | OHLCV, tham chiếu/trần/sàn (nghìn đồng) | **Nguồn dự phòng thứ ba** cho giá; đối chiếu sai lệch > 0,5% (NFR-07) | Trung bình |
| 11 | **CafeF – khối ngoại toàn thị trường** | `cafef.vn/du-lieu/Ajax/PageNew/DataHistory/GDKhoiNgoai.ashx?Symbol=VNINDEX` | KL/GT mua bán khối ngoại toàn sàn theo ngày | Màn Thị trường: chip "khối ngoại ròng"; câu kết luận thị trường | Trung bình |
| 12 | **RSS tin tức** | `vnexpress.net/rss/kinh-doanh.rss`, `cafef.vn/thi-truong-chung-khoan.rss`, `vietstock.vn/830/chung-khoan/co-phieu.rss` | Tiêu đề, tóm tắt, link, giờ đăng | **FR-08, FR-32**: tab Tin tức của mã (gắn mã bằng nhận diện tên/mã trong tiêu đề), AI tóm tắt + chấm cảm xúc tin, bản tin trước phiên. Chỉ lưu tiêu đề + link, không chép toàn văn | **Cao** |
| 13 | **World Bank API** | `api.worldbank.org/v2/country/VN/indicator/{mã chỉ tiêu}?format=json` | GDP tăng trưởng, CPI, tín dụng, FDI… (theo **năm**) | **FR-08/M5** vĩ mô dài hạn cho điểm ngành; biểu đồ vĩ mô | Thấp (chỉ số năm, chậm) |
| 14 | **Vietcombank – tỷ giá** | `portal.vietcombank.com.vn/Usercontrols/TVPortal.TyGia/pXML.aspx?b=10` (tối đa 1 lần / 5 phút) | Tỷ giá mua/bán các ngoại tệ | M5: yếu tố "tỷ giá tăng" → ngành xuất khẩu hưởng lợi | Trung bình |

### Đề xuất thêm theo thứ tự

1. **#1 giao dịch nội bộ + #2 sự kiện quyền** — đóng FR-46 (P1), làm đủ điểm rủi ro DN, lịch sự kiện, tiêu chí GDKHQ trong kiểm tra trước khi mua. Dự kiến app lên ≈ P1 95%.
2. **#3 + #4 khối ngoại, #5 tự doanh** — dòng tiền cho M10, điểm ngành, cảnh báo gom/xả.
3. **#12 RSS tin tức** — tab Tin tức, AI tóm tắt và chấm cảm xúc (FR-32).
4. **#8 khuyến nghị CTCK, #11 khối ngoại toàn sàn, #14 tỷ giá, #13 World Bank**.
5. **#10 VNDirect giá** — nguồn dự phòng thứ ba và đối chiếu.

Ước lượng: mục 1–3 khoảng 1–2 ngày làm; đưa app từ ≈ 84% lên ≈ 92% yêu cầu chức năng.

## C. Đã thử nhưng không dùng được miễn phí

| Nguồn | Kết quả thử | Ghi chú |
|---|---|---|
| `vnstock` (Python) | Gỡ khỏi PyPI, cần đăng ký khoá, không có bản macOS | Thay bằng adapter gọi thẳng SSI/Vietcap |
| TCBS `apipubaws.tcbs.com.vn` | 403 (Cloudflare chặn) | — |
| Fireant `restv2.fireant.vn` | 401 cần token | Có gói trả phí |
| Vietstock `finance.vietstock.vn/data/*` | Cần cookie/token phiên | RSS của Vietstock vẫn dùng được (#12) |
| VNDirect `insider_transactions`, `macro_parameters`, `news` | 404 / rỗng | Dùng Vietcap (#1) và RSS (#12) thay |
| Vietcap `news`, `events` | 404 | Dùng VNDirect events (#2) |
| Yahoo Finance (dầu, tỷ giá) | 429 giới hạn tần suất | Không ổn định |
| Stooq (giá hàng hoá) | Trang không tồn tại | — |
| SJC giá vàng | 403 (Cloudflare) | — |
| KBS `kbbuddywts.kbsec.com.vn` | Cần tham số khác, chưa dò thêm | Có thể là nguồn giá dự phòng sau |

**Vẫn chưa có nguồn miễn phí:** giá **realtime** dạng streaming (tick/nến phút ≤ 60 giây), **giá hàng hoá** (dầu, thép, phân bón),
**vĩ mô hằng tháng** (CPI, PMI, tín dụng — Tổng cục Thống kê/NHNN chỉ có trang web, phải bóc tách tay), **dự phóng lợi nhuận**, **danh mục ETF**.
Các mục này vẫn cần nguồn trả phí — xem [`API-CAN-BO-SUNG.md`](API-CAN-BO-SUNG.md).
