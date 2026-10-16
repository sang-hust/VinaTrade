// Smoke test against the real backend (skipped when http://localhost:8010 is not reachable).
// Run: flutter test test/smoke_backend_test.dart
import 'dart:io';

import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:google_fonts/google_fonts.dart';
import 'package:shared_preferences/shared_preferences.dart';
import 'package:vinatrade/core/api.dart';
import 'package:vinatrade/core/config.dart';
import 'package:vinatrade/app/router.dart';
import 'package:vinatrade/main.dart';
import 'package:vinatrade/shared/widgets/common.dart';

Future<bool> _backendUp() async {
  try {
    final c = HttpClient();
    final r = await c.getUrl(Uri.parse('${AppConfig.apiBaseUrl}/health')).then((q) => q.close());
    c.close();
    return r.statusCode == 200;
  } catch (_) {
    return false;
  }
}

Future<void> _settle(WidgetTester tester, {int frames = 20}) async {
  for (var i = 0; i < frames; i++) {
    await tester.pump(const Duration(milliseconds: 100));
  }
}

Future<void> _wait(WidgetTester tester, Finder f, {int seconds = 12}) async {
  for (var i = 0; i < seconds * 5; i++) {
    await tester.runAsync(() => Future.delayed(const Duration(milliseconds: 200)));
    await tester.pump(const Duration(milliseconds: 100));
    if (f.evaluate().isNotEmpty) return;
  }
  final texts = find.byType(Text).evaluate().map((e) => (e.widget as Text).data ?? '').where((t) => t.isNotEmpty).take(120).join(' | ');
  final skel = find.byType(SkeletonList).evaluate().length;
  final err = find.byType(ErrorBox).evaluate().length;
  throw TestFailure('Không thấy: $f\nSkeleton=$skel Error=$err\nTrên màn hình: $texts');
}

/// Wait until [marker] is on screen, or (short screens) until the page finished loading: no skeleton, no error box.
Future<void> _waitLoaded(WidgetTester tester, String marker, {int seconds = 25}) async {
  for (var i = 0; i < seconds * 5; i++) {
    await tester.runAsync(() => Future.delayed(const Duration(milliseconds: 200)));
    await tester.pump(const Duration(milliseconds: 100));
    if (find.textContaining(marker).evaluate().isNotEmpty) return;
    if (i >= 15 && find.byType(SkeletonList).evaluate().isEmpty && find.byType(Skeleton).evaluate().isEmpty && find.byType(ErrorBox).evaluate().isEmpty) return;
  }
  throw TestFailure('Trang chưa tải xong: $marker');
}

void main() {
  TestWidgetsFlutterBinding.ensureInitialized();
  GoogleFonts.config.allowRuntimeFetching = false;

  testWidgets('đăng nhập admin và duyệt qua các màn chính với dữ liệu thật', (tester) async {
    HttpOverrides.global = null;
    final up = await tester.runAsync(_backendUp) ?? false;
    if (!up) {
      markTestSkipped('Backend không chạy ở ${AppConfig.apiBaseUrl}');
      return;
    }
    SharedPreferences.setMockInitialValues({});
    tester.view.physicalSize = const Size(1440, 1000);
    tester.view.devicePixelRatio = 1;
    addTearDown(tester.view.reset);
    final container = ProviderContainer();
    await tester.pumpWidget(UncontrolledProviderScope(container: container, child: const VinatradeApp()));
    await _wait(tester, find.widgetWithText(FilledButton, 'Đăng nhập'));

    await tester.enterText(find.byType(TextField).at(0), 'sang.vo@paxiegames.com');
    await tester.enterText(find.byType(TextField).at(1), 'admin-change-me');
    await tester.tap(find.widgetWithText(FilledButton, 'Đăng nhập'));
    // Onboarding for a fresh account, else the market page
    await _wait(tester, find.byWidgetPredicate((w) => w is Text && (w.data?.contains('Bỏ qua, dùng cài đặt mặc định') == true || w.data?.contains('Tín hiệu hôm nay') == true)), seconds: 25);
    final api = container.read(apiProvider);
    expect(api.accessToken, isNotNull);
    if (find.text('Bỏ qua, dùng cài đặt mặc định').evaluate().isNotEmpty) {
      await tester.tap(find.text('Bỏ qua, dùng cài đặt mặc định'));
    }
    await _wait(tester, find.textContaining('Tín hiệu hôm nay'), seconds: 25);
    expect(find.textContaining('Thị trường'), findsWidgets);

    // Analysis FPT
    final router = container.read(routerProvider);
    router.go('/stocks/FPT');
    await _wait(tester, find.text('Kế hoạch giao dịch'), seconds: 20);
    expect(find.text('Vì sao có khuyến nghị'), findsOneWidget);

    // Screener
    router.go('/screener');
    await _wait(tester, find.textContaining('Điều chỉnh về MA50'), seconds: 25);
    await _wait(tester, find.text('Kết quả'), seconds: 20);

    // Alerts
    router.go('/alerts');
    await _wait(tester, find.text('Quy tắc cảnh báo'), seconds: 20);

    // Portfolio: create one if missing, then record a BUY through the pretrade sheet
    router.go('/portfolio');
    await _wait(tester, find.byWidgetPredicate((w) => w is Text && (w.data == 'Tạo danh mục' || w.data == 'Ghi nhận giao dịch')), seconds: 25);
    if (find.text('Tạo danh mục').evaluate().isNotEmpty) {
      await tester.tap(find.text('Tạo danh mục'));
      await _settle(tester);
      await tester.enterText(find.widgetWithText(TextField, 'Tên danh mục'), 'Danh mục thử nghiệm');
      await tester.enterText(find.widgetWithText(TextField, 'Tiền mặt ban đầu (đồng)'), '500000000');
      await tester.tap(find.widgetWithText(FilledButton, 'Tạo'));
      await _wait(tester, find.text('Ghi nhận giao dịch'), seconds: 25);
    }
    await _wait(tester, find.text('Ghi nhận giao dịch'), seconds: 20);
    await tester.tap(find.text('Ghi nhận giao dịch'));
    await _settle(tester);
    await tester.enterText(find.widgetWithText(TextField, 'Mã'), 'FPT');
    await tester.tap(find.widgetWithText(FilledButton, 'Ghi nhận'));
    await _wait(tester, find.textContaining('Kiểm tra trước khi mua'), seconds: 20);
    await _wait(tester, find.text('Lệnh dự kiến'), seconds: 20);
    // result box present (GREEN/YELLOW/RED)
    expect(find.byType(FilledButton), findsWidgets);

    // Admin overview
    await tester.tap(find.byIcon(Icons.close).last);
    await _settle(tester);
    router.go('/admin/overview');
    await _wait(tester, find.text('Chuỗi xử lý cuối ngày'), seconds: 20);
    expect(find.text('Nguồn dữ liệu'), findsWidgets);

    expect(tester.takeException(), isNull);
    await tester.runAsync(() => Future.delayed(const Duration(seconds: 3))); // let in-flight requests finish
    await _settle(tester, frames: 5);
    await tester.pumpWidget(const SizedBox());
    container.dispose();
    await tester.runAsync(() => Future.delayed(const Duration(seconds: 1)));
    await _settle(tester, frames: 5);
    await tester.pump(const Duration(minutes: 3)); // let keep-alive / toast / debounce timers expire
  }, timeout: const Timeout(Duration(minutes: 5)));

  testWidgets('bố cục điện thoại (390×844): các màn chính không tràn và không lỗi', (tester) async {
    HttpOverrides.global = null;
    final up = await tester.runAsync(_backendUp) ?? false;
    if (!up) {
      markTestSkipped('Backend không chạy ở ${AppConfig.apiBaseUrl}');
      return;
    }
    SharedPreferences.setMockInitialValues({});
    tester.view.physicalSize = const Size(390, 844);
    tester.view.devicePixelRatio = 1;
    addTearDown(tester.view.reset);
    final container = ProviderContainer();
    await tester.pumpWidget(UncontrolledProviderScope(container: container, child: const VinatradeApp()));
    await _wait(tester, find.widgetWithText(FilledButton, 'Đăng nhập'));
    await tester.enterText(find.byType(TextField).at(0), 'sang.vo@paxiegames.com');
    await tester.enterText(find.byType(TextField).at(1), 'admin-change-me');
    await tester.tap(find.widgetWithText(FilledButton, 'Đăng nhập'));
    await _wait(tester, find.byWidgetPredicate((w) => w is Text && (w.data?.contains('Bỏ qua') == true || w.data?.contains('Tín hiệu hôm nay') == true)), seconds: 25);
    if (find.text('Bỏ qua').evaluate().isNotEmpty) await tester.tap(find.text('Bỏ qua'));
    await _wait(tester, find.textContaining('Tín hiệu hôm nay'), seconds: 25);
    final router = container.read(routerProvider);
    for (final (route, marker) in [('/stocks/FPT', 'Kế hoạch giao dịch'), ('/watch', 'Danh sách của tôi'), ('/alerts', 'Tất cả'), ('/portfolio', 'Cần xử lý'), ('/account', 'Giới hạn rủi ro'), ('/screener', 'Kết quả')]) {
      router.go(route);
      await _wait(tester, find.textContaining(marker), seconds: 25);
      await _settle(tester, frames: 10);
      expect(tester.takeException(), isNull, reason: 'lỗi ở $route');
    }
    await tester.runAsync(() => Future.delayed(const Duration(seconds: 3))); // let in-flight requests finish
    await _settle(tester, frames: 5);
    await tester.pumpWidget(const SizedBox());
    container.dispose();
    await tester.runAsync(() => Future.delayed(const Duration(seconds: 1)));
    await _settle(tester, frames: 5);
    await tester.pump(const Duration(minutes: 3));
  }, timeout: const Timeout(Duration(minutes: 5)));

  // iPad / tablet / landscape phone with a status bar and side insets: every main screen must render without overflow,
  // the top bar must sit below the status bar and the account avatar must stay on screen.
  for (final (name, size, pad) in [
    ('iPad mini dọc 744×1133', const Size(744, 1133), const FakeViewPadding(top: 24, bottom: 20)),
    ('iPad mini ngang 1133×744', const Size(1133, 744), const FakeViewPadding(top: 24, bottom: 20)),
    ('iPad Air dọc 820×1180', const Size(820, 1180), const FakeViewPadding(top: 24, bottom: 20)),
    ('iPad Air ngang 1180×820', const Size(1180, 820), const FakeViewPadding(top: 24, bottom: 20)),
    ('iPhone ngang 844×390', const Size(844, 390), const FakeViewPadding(left: 47, right: 47, bottom: 21)),
  ]) {
    testWidgets('bố cục $name: không tràn, thanh trên dưới thanh trạng thái, đủ nút', (tester) async {
      HttpOverrides.global = null;
      final up = await tester.runAsync(_backendUp) ?? false;
      if (!up) {
        markTestSkipped('Backend không chạy ở ${AppConfig.apiBaseUrl}');
        return;
      }
      SharedPreferences.setMockInitialValues({});
      tester.view.physicalSize = size;
      tester.view.devicePixelRatio = 1;
      tester.view.padding = pad;
      tester.view.viewPadding = pad;
      addTearDown(tester.view.reset);
      final container = ProviderContainer();
      await tester.pumpWidget(UncontrolledProviderScope(container: container, child: const VinatradeApp()));
      await _wait(tester, find.widgetWithText(FilledButton, 'Đăng nhập'));
      await tester.enterText(find.byType(TextField).at(0), 'sang.vo@paxiegames.com');
      await tester.enterText(find.byType(TextField).at(1), 'admin-change-me');
      await tester.tap(find.widgetWithText(FilledButton, 'Đăng nhập'));
      await _waitLoaded(tester, 'Thị trường');
      if (find.textContaining('Bỏ qua').evaluate().isNotEmpty) await tester.tap(find.textContaining('Bỏ qua').first);
      await _waitLoaded(tester, 'Thị trường');
      final router = container.read(routerProvider);
      for (final (route, marker) in [('/', 'Tín hiệu hôm nay'), ('/stocks/FPT', 'Kế hoạch giao dịch'), ('/watch', 'Danh sách của tôi'), ('/screener', 'Kết quả'),
                                     ('/alerts', 'Tất cả'), ('/portfolio', 'Cần xử lý'), ('/account', 'Giới hạn rủi ro'), ('/admin/overview', 'Chuỗi xử lý cuối ngày')]) {
        router.go(route);
        await _waitLoaded(tester, marker);
        await _settle(tester, frames: 10);
        expect(tester.takeException(), isNull, reason: 'lỗi bố cục ở $route ($name)');
        if (size.width >= 600 && !route.startsWith('/admin')) {
          final avatar = find.byTooltip('Tài khoản');
          expect(avatar, findsOneWidget, reason: 'mất nút tài khoản ở $route ($name)');
          final r = tester.getRect(avatar);
          expect(r.right <= size.width - pad.right + 0.5 && r.left >= 0, isTrue, reason: 'nút tài khoản tràn khỏi màn hình ở $route ($name): $r');
          expect(r.top >= pad.top, isTrue, reason: 'thanh trên nằm dưới thanh trạng thái ở $route ($name): $r');
          expect(find.byTooltip('Cảnh báo'), findsOneWidget, reason: 'mất chuông ở $route ($name)');
        }
      }
      await tester.runAsync(() => Future.delayed(const Duration(seconds: 3)));
      await _settle(tester, frames: 5);
      await tester.pumpWidget(const SizedBox());
      container.dispose();
      await tester.runAsync(() => Future.delayed(const Duration(seconds: 1)));
      await _settle(tester, frames: 5);
      await tester.pump(const Duration(minutes: 3));
    }, timeout: const Timeout(Duration(minutes: 5)));
  }
}
