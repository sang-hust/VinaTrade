import 'dart:async';

import 'package:flutter/material.dart';
import 'package:flutter/services.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:go_router/go_router.dart';
import 'package:qr_flutter/qr_flutter.dart';

import '../../core/api.dart';
import '../../core/format.dart';
import '../../core/providers.dart';
import '../../core/responsive.dart';
import '../../core/session.dart';
import '../../core/theme.dart';
import '../../shared/widgets/brand.dart';
import '../../shared/widgets/common.dart';
import '../../shared/widgets/score.dart';
import 'admin_common.dart';
import 'pages/ai_page.dart';
import 'pages/audit_page.dart';
import 'pages/broadcasts_page.dart';
import 'pages/config_page.dart';
import 'pages/jobs_page.dart';
import 'pages/overview_page.dart';
import 'pages/performance_page.dart';
import 'pages/risk_page.dart';
import 'pages/strategies_page.dart';
import 'pages/users_page.dart';

/// Admin console frame (UI spec 15): light theme, left menu with "Quản trị" under the logo, top bar with search (Ctrl K),
/// system-health and session badges, bell with the "Cần xử lý" items; footer shows the admin and 2FA state.
/// Gates: 2FA required (ADMIN_2FA_REQUIRED) and the 30-minute idle lock (ADMIN_SESSION_EXPIRED).
class AdminShell extends ConsumerStatefulWidget {
  final String section;
  final Map<String, String> query;
  const AdminShell({super.key, required this.section, this.query = const {}});
  @override
  ConsumerState<AdminShell> createState() => _AdminShellState();
}

class _AdminShellState extends ConsumerState<AdminShell> {
  Timer? _poll;
  late final ApiClient _api;

  @override
  void initState() {
    super.initState();
    _api = ref.read(apiProvider);
    _api.onAdminGate = (code) {
      if (mounted) ref.read(adminGateProvider.notifier).set(code);
    };
    _poll = Timer.periodic(const Duration(seconds: 60), (_) {
      if (mounted) ref.invalidate(getProvider('/admin/status'));
    });
  }

  @override
  void dispose() {
    _poll?.cancel();
    _api.onAdminGate = null; // no ref access in dispose (Riverpod 3)
    super.dispose();
  }

  @override
  Widget build(BuildContext context) {
    final brightness = ref.watch(adminThemeProvider);
    return Theme(
      data: buildTheme(brightness),
      child: Builder(builder: (context) {
        final c = context.vn;
        final s = ref.watch(sessionProvider);
        final gate = ref.watch(adminGateProvider);
        final status = ref.watch(getMapProvider('/admin/status'));
        final st = status.value ?? const <String, dynamic>{};
        final pending = asInt(st['users_pending']) ?? 0;
        final todo = asList(st['todo']);
        final body = switch (widget.section) {
          'users' => UsersPage(query: widget.query),
          'strategies' => StrategiesPage(code: widget.query['code']),
          'jobs' => const JobsPage(),
          'performance' => const PerformancePage(),
          'config' => ConfigPage(focusKey: widget.query['key']),
          'risk' => const RiskPage(),
          'broadcasts' => const BroadcastsPage(),
          'audit' => const AuditPage(),
          'ai' => const AiPage(),
          _ => const OverviewPage(),
        };
        final menu = Material(
          type: MaterialType.transparency,
          child: Column(children: [
            Padding(
              padding: const EdgeInsets.fromLTRB(18, 16, 12, 8),
              child: Row(children: [BrandMark(size: 30, light: brightness == Brightness.dark), const SizedBox(width: 10), Column(crossAxisAlignment: CrossAxisAlignment.start, children: [Text('Vinatrade', style: TextStyle(fontWeight: FontWeight.w800, fontSize: 16, color: c.text)), Text('Quản trị', style: TextStyle(color: c.muted, fontSize: 12))])]),
            ),
            Expanded(
              child: ListView(padding: const EdgeInsets.symmetric(vertical: 4, horizontal: 8), children: [
                for (final sec in adminSections)
                  ListTile(
                    dense: true, visualDensity: VisualDensity.compact, shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(10)),
                    selected: sec.$1 == widget.section, selectedTileColor: c.accent.withValues(alpha: 0.1), selectedColor: c.accent,
                    leading: Icon(sec.$3, size: 20), title: Text(sec.$2, style: const TextStyle(fontSize: 13.5)),
                    trailing: sec.$1 == 'users' && pending > 0 ? Badge(label: Text('$pending'), backgroundColor: c.down) : null,
                    onTap: () => context.go('/admin/${sec.$1}'),
                  ),
                const Divider(),
                ListTile(dense: true, visualDensity: VisualDensity.compact, shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(10)), leading: const Icon(Icons.home_outlined, size: 20), title: const Text('Mở ứng dụng', style: TextStyle(fontSize: 13.5)), onTap: () => context.go('/')),
              ]),
            ),
            const Divider(height: 1),
            ListTile(
              dense: true,
              leading: CircleAvatar(radius: 16, backgroundColor: c.accent.withValues(alpha: 0.15), child: Text((s.user['full_name']?.toString() ?? '?').characters.first.toUpperCase(), style: TextStyle(color: c.accent, fontWeight: FontWeight.w700))),
              title: Text(s.user['full_name']?.toString() ?? '', style: const TextStyle(fontSize: 13, fontWeight: FontWeight.w600), maxLines: 1, overflow: TextOverflow.ellipsis),
              subtitle: Text(s.user['totp_enabled'] == true ? 'Admin, đã bật 2FA' : 'Admin, chưa bật 2FA', style: TextStyle(fontSize: 11.5, color: s.user['totp_enabled'] == true ? c.muted : c.down)),
              onTap: () => context.go('/account?s=security'),
            ),
          ]),
        );
        final health = st['health']?.toString();
        final healthLabel = {'GREEN': 'Hệ thống hoạt động bình thường', 'YELLOW': 'Có việc cần chú ý', 'RED': 'Có lỗi cần xử lý'}[health];
        final topBar = LayoutBuilder(builder: (ctx, box) {
          final roomy = box.maxWidth >= 1120; // full badge text only when the bar has room; otherwise dot + tooltip
          return Container(
            height: 56,
            padding: const EdgeInsets.symmetric(horizontal: 16),
            decoration: BoxDecoration(color: c.surface, border: Border(bottom: BorderSide(color: c.line))),
            child: Row(children: [
              if (!context.isDesktop) Builder(builder: (ctx) => IconButton(icon: const Icon(Icons.menu), onPressed: () => Scaffold.of(ctx).openDrawer())),
              Flexible(
                child: ConstrainedBox(
                  constraints: const BoxConstraints(maxWidth: 380),
                  child: InkWell(
                    borderRadius: BorderRadius.circular(10),
                    onTap: () => showAdminSearch(context),
                    child: Container(
                      height: 38, padding: const EdgeInsets.symmetric(horizontal: 10),
                      decoration: BoxDecoration(color: c.surface2, borderRadius: BorderRadius.circular(10), border: Border.all(color: c.line)),
                      child: Row(children: [Icon(Icons.search, size: 18, color: c.faint), const SizedBox(width: 8), Expanded(child: Text('Tìm người dùng, tác vụ, cấu hình…', maxLines: 1, overflow: TextOverflow.ellipsis, style: TextStyle(color: c.faint, fontSize: 13))), if (roomy) Pill('Ctrl K', color: c.faint, bg: c.surface, fontSize: 10)]),
                    ),
                  ),
                ),
              ),
              const SizedBox(width: 8),
              if (healthLabel != null) _TopPill(color: c.levelColor(health), text: healthLabel, compact: !roomy),
              if (st['session'] != null) ...[const SizedBox(width: 8), _TopPill(color: st['session']['state'] == 'OPEN' ? c.up : c.ref, text: st['session']['label'].toString(), compact: !roomy)],
              const SizedBox(width: 4),
              MenuAnchor(
                builder: (ctx, controller, _) => IconButton(
                  tooltip: 'Việc cần xử lý',
                  onPressed: () => controller.isOpen ? controller.close() : controller.open(),
                  icon: todo.isEmpty ? const Icon(Icons.notifications_none) : Badge(label: Text('${todo.length}'), backgroundColor: c.down, child: const Icon(Icons.notifications_none)),
                ),
                menuChildren: todo.isEmpty
                    ? [const MenuItemButton(child: Text('Không có việc cần xử lý'))]
                    : [for (final t in todo) MenuItemButton(leadingIcon: const Icon(Icons.circle, size: 8), onPressed: () => context.go(t['route'].toString()), child: SizedBox(width: 320, child: Column(crossAxisAlignment: CrossAxisAlignment.start, mainAxisSize: MainAxisSize.min, children: [Text(t['text'].toString(), style: const TextStyle(fontWeight: FontWeight.w600, fontSize: 13)), if ((t['detail']?.toString() ?? '').isNotEmpty) Text(t['detail'].toString(), style: TextStyle(fontSize: 11.5, color: c.muted), maxLines: 2, overflow: TextOverflow.ellipsis)])))],
              ),
              IconButton(tooltip: brightness == Brightness.dark ? 'Chuyển nền sáng' : 'Chuyển nền tối', onPressed: () => ref.read(adminThemeProvider.notifier).toggle(), icon: Icon(brightness == Brightness.dark ? Icons.light_mode_outlined : Icons.dark_mode_outlined)),
              if (roomy) TextButton.icon(onPressed: () => context.go('/'), icon: const Icon(Icons.exit_to_app, size: 18), label: const Text('Mở ứng dụng')) else IconButton(tooltip: 'Mở ứng dụng', onPressed: () => context.go('/'), icon: const Icon(Icons.exit_to_app)),
            ]),
          );
        });
        return CallbackShortcuts(
          bindings: {
            const SingleActivator(LogicalKeyboardKey.keyK, control: true): () => showAdminSearch(context),
            const SingleActivator(LogicalKeyboardKey.keyK, meta: true): () => showAdminSearch(context),
          },
          child: Focus(
            autofocus: true,
            child: Scaffold(
              backgroundColor: c.bg,
              drawer: context.isDesktop ? null : Drawer(child: menu),
              body: Stack(children: [
                Row(children: [
                  if (context.isDesktop) SizedBox(width: 248, child: Container(decoration: BoxDecoration(color: c.surface, border: Border(right: BorderSide(color: c.line))), child: menu)),
                  Expanded(child: Column(children: [
                    topBar,
                    Expanded(child: SingleChildScrollView(padding: EdgeInsets.all(context.isPhone ? 16 : 24), child: Align(alignment: Alignment.topCenter, child: ConstrainedBox(constraints: const BoxConstraints(maxWidth: 1680), child: body)))),
                  ])),
                ]),
                if (gate != null || (s.user['totp_enabled'] != true && st['require_2fa'] == true)) _AdminGateOverlay(code: gate ?? 'ADMIN_2FA_REQUIRED', idleMinutes: asInt(st['idle_minutes']) ?? 30),
              ]),
            ),
          ),
        );
      }),
    );
  }
}

class _TopPill extends StatelessWidget {
  final Color color;
  final String text;
  final bool compact;
  const _TopPill({required this.color, required this.text, this.compact = false});
  @override
  Widget build(BuildContext context) {
    final c = context.vn;
    return Tooltip(
      message: text,
      child: Container(
        padding: EdgeInsets.symmetric(horizontal: compact ? 8 : 10, vertical: 6),
        decoration: BoxDecoration(color: c.surface, borderRadius: BorderRadius.circular(8), border: Border.all(color: c.line)),
        child: Row(mainAxisSize: MainAxisSize.min, children: [StatusDot(color, size: 8), if (!compact) ...[const SizedBox(width: 6), Text(text, style: TextStyle(fontSize: 12.5, fontWeight: FontWeight.w600, color: c.text))]]),
      ),
    );
  }
}

/// Overlay for the two gates. 2FA: inline TOTP setup (QR + code). Idle lock: password (+ TOTP) re-entry.
class _AdminGateOverlay extends ConsumerStatefulWidget {
  final String code;
  final int idleMinutes;
  const _AdminGateOverlay({required this.code, required this.idleMinutes});
  @override
  ConsumerState<_AdminGateOverlay> createState() => _AdminGateOverlayState();
}

class _AdminGateOverlayState extends ConsumerState<_AdminGateOverlay> {
  final pw = TextEditingController(), totp = TextEditingController(), code = TextEditingController();
  Map<String, dynamic>? setup;
  bool busy = false;
  String? error;

  Future<void> _unlock() async {
    setState(() {
      busy = true;
      error = null;
    });
    try {
      await ref.read(apiProvider).post('/admin/session/unlock', data: {'password': pw.text, if (totp.text.trim().isNotEmpty) 'totp': totp.text.trim()});
      ref.read(adminGateProvider.notifier).set(null);
      ref.invalidate(getProvider('/admin/status'));
      if (mounted) showToast(context, 'Đã mở lại phiên quản trị');
    } on ApiException catch (e) {
      setState(() => error = e.message);
    } finally {
      if (mounted) setState(() => busy = false);
    }
  }

  Future<void> _startSetup() async {
    try {
      final r = asMap(await ref.read(apiProvider).post('/auth/2fa/setup'));
      setState(() => setup = asMap(r['data']));
    } on ApiException catch (e) {
      setState(() => error = e.message);
    }
  }

  Future<void> _verify() async {
    setState(() => busy = true);
    try {
      await ref.read(apiProvider).post('/auth/2fa/verify', data: {'code': code.text.trim()});
      await ref.read(sessionProvider.notifier).refreshMe();
      ref.read(adminGateProvider.notifier).set(null);
      ref.invalidate(getProvider('/admin/status'));
      if (mounted) showToast(context, 'Đã bật xác thực 2 lớp');
    } on ApiException catch (e) {
      setState(() => error = e.message);
    } finally {
      if (mounted) setState(() => busy = false);
    }
  }

  @override
  Widget build(BuildContext context) {
    final c = context.vn;
    final s = ref.watch(sessionProvider);
    final twoFa = widget.code == 'ADMIN_2FA_REQUIRED';
    return Positioned.fill(
      child: Container(
        color: c.bg.withValues(alpha: 0.92),
        alignment: Alignment.center,
        padding: const EdgeInsets.all(24),
        child: ConstrainedBox(
          constraints: const BoxConstraints(maxWidth: 440),
          child: AppCard(
            padding: const EdgeInsets.all(24),
            child: Column(mainAxisSize: MainAxisSize.min, crossAxisAlignment: CrossAxisAlignment.start, children: [
              Row(children: [Icon(twoFa ? Icons.security : Icons.lock_clock_outlined, color: c.accent), const SizedBox(width: 10), Expanded(child: Text(twoFa ? 'Trang quản trị yêu cầu xác thực 2 lớp' : 'Phiên quản trị đã khóa', style: Theme.of(context).textTheme.titleMedium))]),
              const SizedBox(height: 8),
              Text(twoFa ? 'Theo quy định bảo mật, tài khoản Admin phải bật xác thực 2 lớp (Google Authenticator) trước khi vào trang quản trị.' : 'Hơn ${widget.idleMinutes} phút không thao tác. Nhập lại mật khẩu${s.user['totp_enabled'] == true ? ' và mã 2 lớp' : ''} để tiếp tục. Ứng dụng người dùng vẫn đăng nhập bình thường.',
                  style: TextStyle(color: c.muted, fontSize: 13.5)),
              const SizedBox(height: 16),
              if (twoFa) ...[
                if (setup == null)
                  FilledButton.icon(onPressed: _startSetup, icon: const Icon(Icons.qr_code_2, size: 18), label: const Text('Bật xác thực 2 lớp'))
                else ...[
                  Text('Quét mã bằng Google Authenticator rồi nhập mã 6 số:', style: TextStyle(color: c.muted, fontSize: 12.5)),
                  const SizedBox(height: 8),
                  Center(child: Container(color: Colors.white, padding: const EdgeInsets.all(8), child: QrImageView(data: setup!['otpauth_uri'].toString(), size: 170))),
                  SelectableText('Khóa dự phòng: ${setup!['secret']}', style: TextStyle(fontSize: 11.5, color: c.faint)),
                  const SizedBox(height: 8),
                  Row(children: [
                    Expanded(child: TextField(controller: code, keyboardType: TextInputType.number, autofocus: true, decoration: const InputDecoration(labelText: 'Mã 6 số', isDense: true), onSubmitted: (_) => _verify())),
                    const SizedBox(width: 8),
                    FilledButton(onPressed: busy ? null : _verify, child: const Text('Xác nhận')),
                  ]),
                ],
              ] else ...[
                TextField(controller: pw, obscureText: true, autofocus: true, decoration: const InputDecoration(labelText: 'Mật khẩu', isDense: true), onSubmitted: (_) => _unlock()),
                if (s.user['totp_enabled'] == true) ...[const SizedBox(height: 8), TextField(controller: totp, keyboardType: TextInputType.number, decoration: const InputDecoration(labelText: 'Mã xác thực 2 lớp', isDense: true), onSubmitted: (_) => _unlock())],
                const SizedBox(height: 12),
                Row(children: [
                  TextButton(onPressed: () => context.go('/'), child: const Text('Về ứng dụng')),
                  const Spacer(),
                  FilledButton(onPressed: busy ? null : _unlock, child: Text(busy ? 'Đang kiểm tra…' : 'Mở lại')),
                ]),
              ],
              if (error != null) Padding(padding: const EdgeInsets.only(top: 10), child: Text(error!, style: TextStyle(color: c.down, fontSize: 12.5))),
            ]),
          ),
        ),
      ),
    );
  }
}

/// Ctrl K: users, jobs, config keys, strategies.
Future<void> showAdminSearch(BuildContext context) async {
  final picked = await showDialog<Map<String, dynamic>>(context: context, barrierColor: Colors.black38, builder: (_) => const _AdminSearchDialog());
  if (picked != null && context.mounted) context.go(picked['route'].toString());
}

final _adminSearchProvider = FutureProvider.autoDispose.family<List<Map<String, dynamic>>, String>((ref, q) async {
  if (q.trim().length < 2) return const [];
  return asList(await ref.watch(apiProvider).get('/admin/search', query: {'q': q.trim()}));
});

class _AdminSearchDialog extends ConsumerStatefulWidget {
  const _AdminSearchDialog();
  @override
  ConsumerState<_AdminSearchDialog> createState() => _AdminSearchDialogState();
}

class _AdminSearchDialogState extends ConsumerState<_AdminSearchDialog> {
  String q = '';
  int sel = 0;
  @override
  Widget build(BuildContext context) {
    final c = context.vn;
    final res = ref.watch(_adminSearchProvider(q));
    final rows = res.value ?? const <Map<String, dynamic>>[];
    const icons = {'user': Icons.person_outline, 'job': Icons.schedule, 'config': Icons.tune, 'strategy': Icons.trending_up};
    return Dialog(
      alignment: Alignment.topCenter,
      insetPadding: const EdgeInsets.only(top: 70, left: 16, right: 16),
      child: ConstrainedBox(
        constraints: const BoxConstraints(maxWidth: 560),
        child: Column(mainAxisSize: MainAxisSize.min, children: [
          Padding(
            padding: const EdgeInsets.all(12),
            child: CallbackShortcuts(
              bindings: {
                const SingleActivator(LogicalKeyboardKey.arrowDown): () => setState(() => sel = (sel + 1).clamp(0, rows.isEmpty ? 0 : rows.length - 1)),
                const SingleActivator(LogicalKeyboardKey.arrowUp): () => setState(() => sel = (sel - 1).clamp(0, rows.isEmpty ? 0 : rows.length - 1)),
              },
              child: TextField(
                autofocus: true,
                decoration: const InputDecoration(prefixIcon: Icon(Icons.search), hintText: 'Tìm người dùng, tác vụ, cấu hình, chiến lược…'),
                onChanged: (v) => setState(() {
                  q = v;
                  sel = 0;
                }),
                onSubmitted: (_) => rows.isNotEmpty ? Navigator.pop(context, rows[sel.clamp(0, rows.length - 1)]) : null,
              ),
            ),
          ),
          if (res.isLoading) const LinearProgressIndicator(minHeight: 2),
          Flexible(
            child: ListView(shrinkWrap: true, children: [
              for (var i = 0; i < rows.length; i++)
                ListTile(
                  dense: true, selected: i == sel, selectedTileColor: c.accent.withValues(alpha: 0.08),
                  leading: Icon(icons[rows[i]['type']] ?? Icons.circle_outlined, size: 18),
                  title: Text(rows[i]['label'].toString(), style: const TextStyle(fontWeight: FontWeight.w600, fontSize: 13.5)),
                  subtitle: Text(rows[i]['detail']?.toString() ?? '', style: TextStyle(fontSize: 12, color: c.muted)),
                  onTap: () => Navigator.pop(context, rows[i]),
                ),
              if (rows.isEmpty && q.trim().length >= 2 && !res.isLoading) Padding(padding: const EdgeInsets.all(16), child: Text('Không tìm thấy', style: TextStyle(color: c.muted))),
            ]),
          ),
        ]),
      ),
    );
  }
}
