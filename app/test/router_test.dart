import 'package:flutter_test/flutter_test.dart';
import 'package:vinatrade/app/router.dart';

void main() {
  String? go({bool loading = false, bool auth = true, String status = 'ACTIVE', bool onboarding = false, bool admin = false, required String path}) =>
      computeRedirect(loading: loading, authenticated: auth, status: status, needsOnboarding: onboarding, isAdmin: admin, path: path);

  group('Điều hướng theo trạng thái tài khoản', () {
    test('đang tải phiên → không chuyển hướng', () => expect(go(loading: true, path: '/'), null));
    test('chưa đăng nhập → /login kèm next', () => expect(go(auth: false, path: '/stocks/FPT'), '/login?next=%2Fstocks%2FFPT'));
    test('chưa đăng nhập vẫn mở được trang đăng ký', () => expect(go(auth: false, path: '/register'), null));
    test('PENDING → màn chờ kích hoạt', () {
      expect(go(status: 'PENDING', path: '/'), '/pending');
      expect(go(status: 'PENDING', path: '/pending'), null);
    });
    test('LOCKED → màn chờ (bị khóa)', () => expect(go(status: 'LOCKED', path: '/portfolio'), '/pending'));
    test('ACTIVE chưa làm bước hỏi → /onboarding', () {
      expect(go(onboarding: true, path: '/'), '/onboarding');
      expect(go(onboarding: true, path: '/onboarding'), null);
    });
    test('đã làm bước hỏi → không vào lại /onboarding', () => expect(go(path: '/onboarding'), '/'));
    test('đã đăng nhập mở /login → về trang chính', () => expect(go(path: '/login'), '/'));
    test('thành viên không vào được /admin', () {
      expect(go(path: '/admin/users'), '/');
      expect(go(admin: true, path: '/admin/users'), null);
    });
  });
}
