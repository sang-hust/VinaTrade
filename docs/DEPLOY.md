# Triển khai Vinatrade lên Railway

> **Production (16/10/2026):** project Railway `vinatrade` (gói Hobby, vùng US East), service `vinatrade-api` + `Postgres`.
> API: `https://vinatrade-api-production.up.railway.app/api/v1` · Dữ liệu chép từ máy local bằng `pg_restore | railway connect Postgres`.
> Deploy lại: `cd backend && railway up --service vinatrade-api` (chưa nối GitHub auto-deploy).

Giống Vinaguide: 1 service API (Docker) + 1 Postgres, vùng Singapore. Railway CLI đã cài và đăng nhập trên máy dev.

| Thành phần | Dịch vụ |
|---|---|
| Backend API + lịch tác vụ (EOD 15:05, quét 5 phút trong phiên) | Railway service `vinatrade-api`, deploy từ thư mục `backend/` |
| Database | Railway Postgres (Postgres thường, không cần extension) |
| App | Build Flutter trỏ `API_BASE_URL` vào domain Railway |

## 1. Tạo project và Postgres

```bash
cd /Users/vohongsang/Vinatrade/backend
railway init                      # tên: vinatrade
railway add --database postgres
```

Dashboard → project `vinatrade` → Settings → Region: **Southeast Asia (Singapore)** cho cả 2 service.

## 2. Chép dữ liệu từ máy local lên (khỏi nạp lại 30 phút)

Lấy `DATABASE_PUBLIC_URL` ở Postgres → Variables, rồi:

```bash
pg_dump -Fc --no-owner --no-acl -d vinatrade -f /tmp/vinatrade.dump
pg_restore --no-owner --no-acl -d "<DATABASE_PUBLIC_URL>" /tmp/vinatrade.dump
```

Bỏ qua bước này nếu muốn server tự nạp dữ liệu từ đầu (đặt `BOOTSTRAP_DATA=true` ở bước 3).

## 3. Tạo service API và biến môi trường

```bash
railway add --service vinatrade-api
railway link                      # chọn project vinatrade, service vinatrade-api
railway variables \
  --set 'DATABASE_URL=${{Postgres.DATABASE_URL}}' \
  --set "JWT_SECRET=$(openssl rand -base64 48)" \
  --set DEBUG=false \
  --set ADMIN_EMAIL=sang.vo@paxiegames.com \
  --set 'ADMIN_PASSWORD=<mật khẩu mạnh>' \
  --set 'ADMIN_NAME=Sang Vo' \
  --set "ANTHROPIC_API_KEY=$(grep ^ANTHROPIC_API_KEY= .env | cut -d= -f2-)" \
  --set SCHEDULER_ENABLED=true \
  --set BOOTSTRAP_DATA=false
```

`ADMIN_PASSWORD` chỉ dùng khi tạo admin lần đầu. Nếu đã chép dữ liệu ở bước 2, mật khẩu admin là mật khẩu trên máy local — đổi trong app.

## 4. Deploy

```bash
railway up                        # build backend/Dockerfile, start.sh: migrate → seed → uvicorn
railway domain                    # tạo https://vinatrade-api-xxxx.up.railway.app
curl https://<domain>/api/v1/health
```

Xem log: `railway logs`. Deploy lại sau khi sửa code: `railway up` (hoặc nối GitHub để tự deploy khi push `main`).

## 5. Build app trỏ vào server

```bash
cd ../app
flutter build apk --release --dart-define=API_BASE_URL=https://<domain>/api/v1
flutter run --release -d <iphone> --dart-define=API_BASE_URL=https://<domain>/api/v1
flutter build web --release --dart-define=API_BASE_URL=https://<domain>/api/v1
```

### Web (service `vinatrade-web`, nginx tĩnh)

Đang chạy tại https://vinatrade-web-production.up.railway.app. Deploy lại sau mỗi thay đổi giao diện:

```bash
app/deploy/deploy_web.sh        # build Flutter web trỏ vào API production, đóng gói nginx, railway up --service vinatrade-web
```

Lần đầu tạo service: `railway add --service vinatrade-web`, `railway domain --service vinatrade-web`.
Service API cần `CORS_ORIGINS=https://vinatrade-web-production.up.railway.app` và `PUBLIC_WEB_URL` cùng giá trị
(nhiều origin thì ngăn cách bằng dấu phẩy). nginx trả `index.html` cho mọi đường dẫn (deep link như `/stocks/FPT`), kiểm tra sống ở `/healthz`.

## Tuỳ chọn

- Telegram: `--set TELEGRAM_BOT_TOKEN=... --set TELEGRAM_WEBHOOK_SECRET=...`, rồi
  `curl "https://api.telegram.org/bot<TOKEN>/setWebhook?url=https://<domain>/api/v1/telegram/webhook&secret_token=<SECRET>"`.
- Email: `SMTP_HOST`, `SMTP_PORT`, `SMTP_USER`, `SMTP_PASSWORD`, `SMTP_FROM`.
- Push: `GCP_CREDENTIALS_JSON` (service account của Firebase project mới).

## Lưu ý

- Chỉ chạy **1 bản** service API (lịch tác vụ nằm trong tiến trình). Không bật autoscale nhiều replica.
- Gói Trial của Railway có hạn mức; dùng thật thì nâng Hobby ($5/tháng) để service không bị dừng.
- Nguồn dữ liệu SSI/Vietcap gọi từ máy chủ Singapore: nếu bị chặn, Admin → Dữ liệu & tác vụ sẽ báo nguồn DOWN.
