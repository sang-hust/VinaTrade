# Vinatrade — Phân tích, lọc cổ phiếu và cảnh báo đầu tư chứng khoán Việt Nam

Ứng dụng cho nhà đầu tư cá nhân: thu thập giá và báo cáo tài chính của toàn bộ mã HOSE/HNX/UPCoM, tính chỉ báo, nhận diện nền giá và đợt tăng,
chấm điểm 0–100 theo ba khung đầu tư, sinh tín hiệu kèm vùng mua / cắt lỗ / chốt lời, cảnh báo cuối ngày và trong phiên, kiểm tra trước khi mua,
cầu dao giới hạn lỗ, thẻ "Cần xử lý" cho danh mục, trợ lý AI và trang quản trị. Bản 1 miễn phí, Admin kích hoạt tài khoản cho bạn bè.

Căn cứ thiết kế (ngoài repo): `~/Downloads/vinatrade/` — Kế hoạch dự án, Phân tích & thiết kế giao diện, Phân tích & thiết kế hệ thống và CSDL (VNSignal AI v1.2).

| Thư mục | Công nghệ | Mô tả |
|---|---|---|
| `backend/` | FastAPI · PostgreSQL · SQLAlchemy async · Alembic · APScheduler · pandas · Claude API | API, engine phân tích, chuỗi xử lý cuối ngày (EOD), cảnh báo, AI, quản trị |
| `app/` | Flutter (Riverpod 2, go_router) | Một mã nguồn cho Web, Windows, macOS, iOS, Android; trang quản trị trong cùng app |

## Kiến trúc backend

```
backend/app
├── ingestion/     adapters/ssi.py (SSI iBoard: danh sách mã, giá ngày), adapters/vci.py (Vietcap: giá, hồ sơ, BCTC),
│                  universe.py, prices.py, fundamentals.py, file_import.py (Admin nhập file giá), icb.py (ngành ICB)
├── engines/       indicators.py (MA, RSI, MACD, ADX, ATR, BB, OBV, MFI, CMF, Stoch, RS, hỗ trợ/kháng cự, xu hướng 5 mức)
│                  bases.py (nền giá, đợt tăng, thống kê), regime.py (trạng thái thị trường + câu kết luận), ratios.py (chỉ số TTM, định giá),
│                  scoring.py (điểm kỹ thuật / cơ bản / tổng hợp, xếp loại, kế hoạch mua bán), strategies.py (12 chiến lược tín hiệu),
│                  risk.py (điểm rủi ro DN, kiểm tra trước khi mua, cầu dao, ký quỹ, tương quan, độ tin cậy)
├── screener/      dsl.py (ngôn ngữ điều kiện JSON → SQL / đánh giá trong bộ nhớ), presets.py (11 bộ lọc mẫu + biểu mẫu)
├── services/      notify.py (cảnh báo + Telegram/email/push), portfolio.py, trades.py (giao dịch, kế hoạch nếu–thì), riskguard.py (cầu dao, Cần xử lý),
│                  ai.py (Claude: câu kết luận, trợ lý có công cụ dữ liệu, huấn luyện viên), coach.py, sysconfig.py, jobs.py
├── tasks/         eod.py (16 bước EOD), alerts.py, intraday.py (5 phút trong phiên), backfill.py (backtest 4 năm → độ tin cậy), scheduler.py, bootstrap.py
├── api/v1/        auth, me, market (thị trường, mã, ngành, cơ hội, tín hiệu), screener, alerts, watchlists, portfolios (+ kế hoạch, nhật ký),
│                  risk (pretrade-check, position-sizing), ai, admin (A01–A10), system (health, Telegram webhook, WebSocket)
└── models/        55 bảng (users, stocks, price_daily, indicators_daily, stock_scores, signals, stock_snapshots, portfolios, action_items…)
```

Chuỗi EOD (15:05 ngày giao dịch): universe → giá & chỉ số → chỉ báo → nền giá → RS/beta → chỉ số tài chính → trạng thái thị trường & câu kết luận (AI viết lại)
→ điểm ngành → rủi ro DN → chấm điểm → tín hiệu → snapshot → kết quả tín hiệu & độ tin cậy → bộ lọc mẫu → AI giải thích → cảnh báo, cầu dao, Cần xử lý, báo cáo.

## Chạy local

```bash
brew install postgresql@18 && brew services start postgresql@18 && createdb vinatrade
cd backend && uv venv --python 3.12 && uv pip install -r pyproject.toml
cp .env.example .env        # điền ANTHROPIC_API_KEY, ADMIN_EMAIL/PASSWORD, TELEGRAM_BOT_TOKEN (tuỳ chọn)
.venv/bin/alembic upgrade head && .venv/bin/python -m app.seeds.seed
.venv/bin/python -m app.tasks.bootstrap        # nạp 6 năm giá cho ~1.750 mã + BCTC, chạy EOD, backfill tín hiệu (≈20–30 phút)
.venv/bin/uvicorn app.main:app --port 8010 --reload
.venv/bin/python -m pytest

cd app && flutter pub get && flutter run -d chrome --web-port 5173 --dart-define=API_BASE_URL=http://localhost:8010/api/v1
```

Tài khoản đầu tiên: `ADMIN_EMAIL` / `ADMIN_PASSWORD` trong `.env`. Người khác đăng ký → chờ Admin kích hoạt (hoặc dùng mã mời tự kích hoạt).

## Biến môi trường chính

| Biến | Mở khoá | Khi chưa có |
|---|---|---|
| `ANTHROPIC_API_KEY` | Câu kết luận thị trường do AI viết lại, câu kết luận từng mã, trợ lý AI, huấn luyện viên | Dùng câu quy tắc; trợ lý báo chưa cấu hình |
| `TELEGRAM_BOT_TOKEN`, `TELEGRAM_WEBHOOK_SECRET` | Cảnh báo qua bot Telegram, lệnh `/gia FPT`, `/canhbao`, `/thitruong` | Chỉ cảnh báo trong app |
| `SMTP_*` | Email đặt lại mật khẩu, kích hoạt, báo cáo | Liên kết ghi vào log (`DEBUG=true` trả `debug_token`) |
| `FIREBASE_CREDENTIALS` / `GCP_CREDENTIALS_JSON` | Thông báo đẩy iOS/Android/Web | Bỏ qua kênh push |
| `SCHEDULER_ENABLED` | Lịch tác vụ trong tiến trình API (chỉ bật ở 1 bản) | Chạy tay qua Admin → Dữ liệu & tác vụ |

Đăng ký webhook Telegram sau khi deploy: `https://api.telegram.org/bot<TOKEN>/setWebhook?url=<API>/api/v1/telegram/webhook&secret_token=<SECRET>`.

## Triển khai

Xem [`docs/DEPLOY.md`](docs/DEPLOY.md) — Railway (API + Postgres, Singapore) giống Vinaguide, Flutter web build tĩnh.

## Giới hạn hiện tại

- Dữ liệu trong phiên: quét 5 phút một lần cho mã theo dõi (SSI), chưa phải realtime 15 giây; WebSocket đã có kênh `quotes:<mã>`.
- Tin tức, giao dịch nội bộ, cầm cố, sự kiện quyền chưa có nguồn — điểm rủi ro DN hiện dựa trên BCTC và diện cảnh báo của Sở.
- Điểm ngành dùng hiệu suất giá, độ rộng, dòng tiền và yếu tố vĩ mô do Admin bật (`macro.active_factors`); chưa nạp số liệu vĩ mô tự động.
- Giá điều chỉnh theo nguồn (SSI/Vietcap đã điều chỉnh sự kiện quyền).
- Backtest chiến lược: `backfill.py` chạy lại chiến lược trên 4 năm để có độ tin cậy; chưa có báo cáo đường vốn chi tiết từng chiến lược.
