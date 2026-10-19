# Vinatrade — repo rules

Ứng dụng phân tích, lọc cổ phiếu và cảnh báo đầu tư chứng khoán Việt Nam (tên tài liệu gốc: VNSignal AI, chủ dự án Phan Dũng).
Căn cứ thiết kế đặt ngoài repo: `~/Downloads/vinatrade/*.docx` (kế hoạch, thiết kế giao diện, thiết kế hệ thống & CSDL, bản 1.2).
Tài liệu chỉ là tham khảo; hệ thống đi theo khuôn của Vinaguide (`~/AudioGuide`): FastAPI + Postgres + Alembic, Flutter, Railway.

| Thư mục | Công nghệ | Mô tả |
|---|---|---|
| `backend/` | FastAPI · SQLAlchemy async · Alembic · APScheduler · pandas | API, engine phân tích, chuỗi xử lý cuối ngày, cảnh báo, AI |
| `app/` | Flutter (Riverpod 2, go_router) | Một mã nguồn cho Web, Windows, iOS, Android, macOS; trang quản trị nằm trong app |

## Quy tắc

- Mọi thay đổi CSDL qua Alembic (`cd backend && .venv/bin/alembic revision --autogenerate -m "..."`). Không sửa migration đã deploy.
- Giá và tiền: API trả **số nguyên đồng**; app định dạng (`128.500 VNĐ`, `+2.000 (+1,58%)`, dấu trừ thật). Chỉ số 2 số lẻ.
- Gợi ý ít rủi ro nhất: mọi danh sách xếp theo `score_adj = điểm × (1 − risk_total/200)`; `risk_total` 6 thành phần (`engines/risk.py: total_risk`, bước `eod.risk_total`), trọng số/ngưỡng ở `risk.score_weights`, `risk.score_params`. Khối rủi ro luôn hiện ở mọi mức chi tiết.
- Tên khuyến nghị cố định: ≥80 Mua mạnh · 65–79 Tích lũy · 50–64 Nắm giữ · 35–49 Giảm tỷ trọng · <35 Bán (`engines/scoring.py`).
- Mọi nút Mua đi qua Kiểm tra trước khi mua (`POST /pretrade-check`); backend từ chối lệnh mua không có `pretrade_check_id` gần đây (`PRETRADE_REQUIRED`).
- Mức chi tiết giao diện chỉ ẩn số liệu phụ; cảnh báo rủi ro, dải cầu dao, mục Đỏ, nhãn mua đuổi, câu miễn trừ luôn hiện (BR-20).
- Ngưỡng, trọng số, tham số chiến lược nằm trong `system_config` (`services/sysconfig.py` có mặc định) — Admin sửa, không viết cứng trong mã.
- Nguồn dữ liệu: SSI iBoard (chính) + Vietcap (dự phòng, BCTC) qua `ingestion/adapters/`. Không dùng thư viện `vnstock` (yêu cầu đăng ký, không có bản macOS).
- Engine (`backend/app/engines/`) là Python thuần, không phụ thuộc DB — thêm chỉ báo/chiến lược ở đây và viết test trong `tests/test_engines.py`.
- AI (Claude) chỉ diễn giải số liệu lấy từ CSDL qua công cụ (`services/ai.py`); không để AI tự bịa số.
- Giao diện tiếng Việt; mã nguồn, tên bảng, cột tiếng Anh.

## Chạy nhanh

```bash
cd backend && .venv/bin/alembic upgrade head && .venv/bin/python -m app.seeds.seed
.venv/bin/uvicorn app.main:app --port 8010 --reload      # http://localhost:8010/docs (DEBUG=true)
.venv/bin/python -m app.tasks.bootstrap                   # lần đầu: nạp 6 năm giá + BCTC, chạy EOD, backfill tín hiệu (≈20 phút)
.venv/bin/python -m pytest                                # test engine + API (API test cần DB đã seed)
cd app && flutter run -d chrome --web-port 5173 --dart-define=API_BASE_URL=http://localhost:8010/api/v1
```

Cổng 8000 trên máy này đang được Vinaguide dùng; Vinatrade chạy 8010.
