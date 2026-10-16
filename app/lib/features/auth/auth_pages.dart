import 'dart:async';

import 'package:flutter/material.dart';
import 'package:flutter_animate/flutter_animate.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:go_router/go_router.dart';

import '../../core/api.dart';
import '../../core/session.dart';
import '../../core/theme.dart';
import '../../shared/widgets/common.dart';

class AuthScaffold extends StatelessWidget {
  final String title;
  final String? subtitle;
  final Widget child;
  const AuthScaffold({super.key, required this.title, this.subtitle, required this.child});
  @override
  Widget build(BuildContext context) {
    final c = context.vn;
    return Scaffold(
      body: Center(
        child: SingleChildScrollView(
          padding: const EdgeInsets.all(20),
          child: ConstrainedBox(
            constraints: const BoxConstraints(maxWidth: 420),
            child: Column(mainAxisSize: MainAxisSize.min, crossAxisAlignment: CrossAxisAlignment.stretch, children: [
              Row(mainAxisAlignment: MainAxisAlignment.center, children: [
                Container(width: 40, height: 40, decoration: BoxDecoration(color: c.accent, borderRadius: BorderRadius.circular(10)), child: const Icon(Icons.show_chart, color: Colors.white)),
                const SizedBox(width: 10),
                Text('Vinatrade', style: Theme.of(context).textTheme.titleLarge?.copyWith(fontWeight: FontWeight.w700)),
              ]).animate().fadeIn(duration: 300.ms).slideY(begin: -0.1),
              const SizedBox(height: 28),
              Text(title, style: Theme.of(context).textTheme.titleLarge),
              if (subtitle != null) Padding(padding: const EdgeInsets.only(top: 4), child: Text(subtitle!, style: TextStyle(color: c.muted))),
              const SizedBox(height: 20),
              AppCard(padding: const EdgeInsets.all(20), child: child).animate().fadeIn(duration: 300.ms, delay: 80.ms).slideY(begin: 0.05),
            ]),
          ),
        ),
      ),
    );
  }
}

class LoginPage extends ConsumerStatefulWidget {
  final String? next;
  const LoginPage({super.key, this.next});
  @override
  ConsumerState<LoginPage> createState() => _LoginPageState();
}

class _LoginPageState extends ConsumerState<LoginPage> {
  final _email = TextEditingController(), _pw = TextEditingController(), _totp = TextEditingController();
  bool _busy = false, _needTotp = false, _hide = true;
  String? _err;

  Future<void> _submit() async {
    setState(() {
      _busy = true;
      _err = null;
    });
    try {
      await ref.read(sessionProvider.notifier).login(_email.text.trim(), _pw.text, totp: _needTotp ? _totp.text.trim() : null);
      if (mounted) context.go(widget.next ?? '/');
    } on ApiException catch (e) {
      setState(() {
        if (e.code == 'TOTP_REQUIRED') {
          _needTotp = true;
        } else {
          _err = e.message;
        }
      });
    } finally {
      if (mounted) setState(() => _busy = false);
    }
  }

  @override
  Widget build(BuildContext context) => AuthScaffold(
        title: 'Đăng nhập',
        subtitle: 'Phân tích, lọc cổ phiếu và cảnh báo đầu tư',
        child: AutofillGroup(
          child: Column(crossAxisAlignment: CrossAxisAlignment.stretch, children: [
            TextField(controller: _email, decoration: const InputDecoration(labelText: 'Email'), keyboardType: TextInputType.emailAddress, autofillHints: const [AutofillHints.email], onSubmitted: (_) => _submit()),
            const SizedBox(height: 12),
            TextField(controller: _pw, obscureText: _hide, decoration: InputDecoration(labelText: 'Mật khẩu', suffixIcon: IconButton(icon: Icon(_hide ? Icons.visibility_off : Icons.visibility), onPressed: () => setState(() => _hide = !_hide))), autofillHints: const [AutofillHints.password], onSubmitted: (_) => _submit()),
            if (_needTotp) ...[
              const SizedBox(height: 12),
              TextField(controller: _totp, decoration: const InputDecoration(labelText: 'Mã xác thực 2 lớp'), keyboardType: TextInputType.number, autofocus: true, onSubmitted: (_) => _submit()).animate().fadeIn(),
            ],
            if (_err != null) Padding(padding: const EdgeInsets.only(top: 10), child: Text(_err!, style: TextStyle(color: context.vn.downText, fontSize: 13))),
            const SizedBox(height: 16),
            FilledButton(onPressed: _busy ? null : _submit, child: _busy ? const SizedBox(width: 18, height: 18, child: CircularProgressIndicator(strokeWidth: 2, color: Colors.white)) : const Text('Đăng nhập')),
            const SizedBox(height: 8),
            Wrap(alignment: WrapAlignment.spaceBetween, children: [
              TextButton(onPressed: () => context.push('/forgot-password'), child: const Text('Quên mật khẩu?')),
              TextButton(onPressed: () => context.push('/register'), child: const Text('Đăng ký bằng mã mời')),
            ]),
          ]),
        ),
      );
}

class RegisterPage extends ConsumerStatefulWidget {
  final String? invite;
  const RegisterPage({super.key, this.invite});
  @override
  ConsumerState<RegisterPage> createState() => _RegisterPageState();
}

class _RegisterPageState extends ConsumerState<RegisterPage> {
  final _name = TextEditingController(), _email = TextEditingController(), _pw = TextEditingController(), _phone = TextEditingController();
  late final _invite = TextEditingController(text: widget.invite ?? '');
  bool _busy = false;
  String? _err;

  Future<void> _submit() async {
    if (_pw.text.length < 8) return setState(() => _err = 'Mật khẩu cần ít nhất 8 ký tự');
    setState(() {
      _busy = true;
      _err = null;
    });
    try {
      await ref.read(sessionProvider.notifier).register(email: _email.text.trim(), password: _pw.text, fullName: _name.text.trim(), phone: _phone.text.trim().isEmpty ? null : _phone.text.trim(), invite: _invite.text.trim().isEmpty ? null : _invite.text.trim());
      if (mounted) context.go('/');
    } on ApiException catch (e) {
      setState(() => _err = e.message);
    } finally {
      if (mounted) setState(() => _busy = false);
    }
  }

  @override
  Widget build(BuildContext context) => AuthScaffold(
        title: 'Đăng ký',
        subtitle: 'Tài khoản sẽ dùng được sau khi quản trị viên kích hoạt',
        child: Column(crossAxisAlignment: CrossAxisAlignment.stretch, children: [
          TextField(controller: _name, decoration: const InputDecoration(labelText: 'Họ tên')),
          const SizedBox(height: 12),
          TextField(controller: _email, decoration: const InputDecoration(labelText: 'Email'), keyboardType: TextInputType.emailAddress),
          const SizedBox(height: 12),
          TextField(controller: _phone, decoration: const InputDecoration(labelText: 'Số điện thoại (tùy chọn)'), keyboardType: TextInputType.phone),
          const SizedBox(height: 12),
          TextField(controller: _pw, obscureText: true, decoration: const InputDecoration(labelText: 'Mật khẩu (≥ 8 ký tự)')),
          const SizedBox(height: 12),
          TextField(controller: _invite, decoration: const InputDecoration(labelText: 'Mã mời (nếu có)'), textCapitalization: TextCapitalization.characters),
          if (_err != null) Padding(padding: const EdgeInsets.only(top: 10), child: Text(_err!, style: TextStyle(color: context.vn.downText, fontSize: 13))),
          const SizedBox(height: 16),
          FilledButton(onPressed: _busy ? null : _submit, child: const Text('Tạo tài khoản')),
          TextButton(onPressed: () => context.go('/login'), child: const Text('Đã có tài khoản? Đăng nhập')),
        ]),
      );
}

class ForgotPage extends ConsumerStatefulWidget {
  const ForgotPage({super.key});
  @override
  ConsumerState<ForgotPage> createState() => _ForgotPageState();
}

class _ForgotPageState extends ConsumerState<ForgotPage> {
  final _email = TextEditingController();
  String? _msg, _debugToken;
  bool _busy = false;
  @override
  Widget build(BuildContext context) => AuthScaffold(
        title: 'Quên mật khẩu',
        child: Column(crossAxisAlignment: CrossAxisAlignment.stretch, children: [
          TextField(controller: _email, decoration: const InputDecoration(labelText: 'Email')),
          const SizedBox(height: 16),
          FilledButton(
            onPressed: _busy
                ? null
                : () async {
                    setState(() => _busy = true);
                    try {
                      final r = await ref.read(apiProvider).post('/auth/password/forgot', data: {'email': _email.text.trim()});
                      setState(() {
                        _msg = r['message'];
                        _debugToken = r['data']?['debug_token'];
                      });
                    } on ApiException catch (e) {
                      setState(() => _msg = e.message);
                    } finally {
                      setState(() => _busy = false);
                    }
                  },
            child: const Text('Gửi liên kết đặt lại'),
          ),
          if (_msg != null) Padding(padding: const EdgeInsets.only(top: 12), child: Text(_msg!, style: TextStyle(color: context.vn.muted))),
          if (_debugToken != null) TextButton(onPressed: () => context.go('/reset-password?token=$_debugToken'), child: const Text('Mở trang đặt lại (chế độ thử)')),
          TextButton(onPressed: () => context.go('/login'), child: const Text('Quay lại đăng nhập')),
        ]),
      );
}

class ResetPage extends ConsumerStatefulWidget {
  final String? token;
  const ResetPage({super.key, this.token});
  @override
  ConsumerState<ResetPage> createState() => _ResetPageState();
}

class _ResetPageState extends ConsumerState<ResetPage> {
  final _pw = TextEditingController();
  String? _err;
  @override
  Widget build(BuildContext context) => AuthScaffold(
        title: 'Đặt lại mật khẩu',
        child: Column(crossAxisAlignment: CrossAxisAlignment.stretch, children: [
          TextField(controller: _pw, obscureText: true, decoration: const InputDecoration(labelText: 'Mật khẩu mới (≥ 8 ký tự)')),
          if (_err != null) Padding(padding: const EdgeInsets.only(top: 10), child: Text(_err!, style: TextStyle(color: context.vn.downText))),
          const SizedBox(height: 16),
          FilledButton(
            onPressed: () async {
              try {
                await ref.read(apiProvider).post('/auth/password/reset', data: {'token': widget.token, 'password': _pw.text});
                if (mounted) {
                  showToast(context, 'Đã đổi mật khẩu, hãy đăng nhập lại');
                  context.go('/login');
                }
              } on ApiException catch (e) {
                setState(() => _err = e.message);
              }
            },
            child: const Text('Đổi mật khẩu'),
          ),
        ]),
      );
}

/// Shown while the account is PENDING; polls /me every 15 s.
class PendingPage extends ConsumerStatefulWidget {
  const PendingPage({super.key});
  @override
  ConsumerState<PendingPage> createState() => _PendingPageState();
}

class _PendingPageState extends ConsumerState<PendingPage> {
  Timer? _t;
  @override
  void initState() {
    super.initState();
    _t = Timer.periodic(const Duration(seconds: 15), (_) => ref.read(sessionProvider.notifier).refreshMe(silent: true));
  }

  @override
  void dispose() {
    _t?.cancel();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) {
    final s = ref.watch(sessionProvider);
    final c = context.vn;
    final status = s.status;
    final (title, body) = switch (status) {
      'LOCKED' => ('Tài khoản đang bị khóa', 'Tài khoản của bạn đang bị khóa. Liên hệ quản trị viên để mở lại.'),
      'REJECTED' => ('Yêu cầu chưa được chấp nhận', 'Quản trị viên chưa chấp nhận yêu cầu đăng ký của bạn.'),
      'EXPIRED' => ('Tài khoản đã hết hạn', 'Liên hệ quản trị viên để gia hạn.'),
      _ => ('Chờ kích hoạt', 'Tài khoản của bạn đang chờ quản trị viên duyệt. Trang này tự kiểm tra lại mỗi 15 giây.'),
    };
    return AuthScaffold(
      title: title,
      child: Column(crossAxisAlignment: CrossAxisAlignment.stretch, children: [
        for (final (i, step) in ['Đăng ký ✓', status == 'PENDING' ? 'Admin kích hoạt (đang chờ)' : 'Admin kích hoạt', 'Hồ sơ đầu tư', 'Bắt đầu dùng'].indexed)
          ListTile(dense: true, leading: CircleAvatar(radius: 12, backgroundColor: i == 0 ? c.up : c.surface2, child: Text('${i + 1}', style: TextStyle(fontSize: 11, color: i == 0 ? Colors.white : c.muted))), title: Text(step)),
        const SizedBox(height: 8),
        Text(body, style: TextStyle(color: c.muted)),
        const SizedBox(height: 16),
        OutlinedButton.icon(onPressed: () => ref.read(sessionProvider.notifier).refreshMe(), icon: const Icon(Icons.refresh, size: 18), label: const Text('Kiểm tra lại trạng thái')),
        TextButton(onPressed: () => ref.read(sessionProvider.notifier).logout(), child: const Text('Đăng xuất')),
      ]),
    );
  }
}
