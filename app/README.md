# Vinatrade — ứng dụng khách (Flutter)

Một mã nguồn cho Web, Windows, macOS, iOS, Android. Giao diện tiếng Việt, nền tối mặc định, trang quản trị nền sáng (theo tài liệu thiết kế giao diện v1.2).

## Chạy

Backend phải chạy trước (mặc định `http://localhost:8010/api/v1`). Địa chỉ API truyền qua `--dart-define`:

```bash
flutter pub get
# Web (Chrome)
flutter run -d chrome --web-port 5173 --dart-define=API_BASE_URL=http://localhost:8010/api/v1
# macOS / Windows
flutter run -d macos --dart-define=API_BASE_URL=http://localhost:8010/api/v1
flutter run -d windows --dart-define=API_BASE_URL=https://api.vinatrade.vn/api/v1
# Android / iOS (máy thật cần địa chỉ server công khai)
flutter run -d <device> --dart-define=API_BASE_URL=https://api.vinatrade.vn/api/v1
```

Build phát hành:

```bash
flutter build web --release --dart-define=API_BASE_URL=https://api.vinatrade.vn/api/v1   # build/web
flutter build apk --release --dart-define=API_BASE_URL=...
flutter build macos --release --dart-define=API_BASE_URL=...
flutter build windows --release --dart-define=API_BASE_URL=...
```

`API_BASE_URL` không có → dùng `http://localhost:8010/api/v1`. WebSocket suy ra từ cùng địa chỉ (`/api/v1/ws`).

## Kiểm thử

```bash
flutter analyze
flutter test                      # định dạng số, điều hướng, widget
flutter test test/smoke_backend_test.dart   # cần backend đang chạy: đăng nhập admin, duyệt các màn chính với dữ liệu thật
```

## Cấu trúc

```
lib/
  main.dart                 khởi tạo, theme, router
  app/router.dart           go_router + computeRedirect (chờ kích hoạt / bước hỏi / admin)
  core/                     api (dio + làm mới token + SSE), session (/me), ws, theme (VNColors), format (128.500 VNĐ), responsive
  shared/widgets/           thước điểm, nhãn khuyến nghị, N·T·D, thanh cắt lỗ→mục tiêu, biểu đồ nến (CustomPainter), bảng mã, thẻ, skeleton, toast
  features/
    auth/ onboarding/       đăng nhập, đăng ký mã mời, quên mật khẩu, 2 lớp, chờ kích hoạt, 5 câu hỏi
    shell/                  thanh trên 6 mục (máy tính) / 5 tab (điện thoại), dải chỉ số, tìm mã Ctrl K
    market/ stock/          Thị trường, Phân tích mã (thẻ khuyến nghị luôn trên cùng, 3 mức chi tiết)
    pretrade/               Kiểm tra trước khi mua — mọi nút Mua đều đi qua đây
    watch/ screener/ alerts/ Theo dõi, 11 bộ lọc mẫu + trình ghép VÀ/HOẶC, cảnh báo + quy tắc
    portfolio/              Danh mục: Cần xử lý, vị thế, rủi ro & ký quỹ, giao dịch, hiệu suất, kế hoạch nếu–thì
    account/ ai/            Tài khoản, huấn luyện viên AI, Hỏi AI (bảng bên / toàn màn, stream SSE)
    admin/                  Quản trị A01–A10 (nền sáng)
```

## Ghi chú nền tảng

- Web: token lưu `shared_preferences`; các nền tảng khác dùng `flutter_secure_storage`.
- Windows: thông báo đẩy và khay hệ thống chưa nối (cần Firebase + `local_notifier`), cảnh báo vẫn về qua WebSocket khi app mở.
- Push (FCM) cần Firebase project mới; màn Tài khoản đã có công tắc, token gửi lên `POST /me/push-token` khi tích hợp `firebase_messaging`.
