import 'dart:convert';

import 'package:file_picker/file_picker.dart';
import 'package:flutter/material.dart';
import 'package:flutter/services.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:go_router/go_router.dart';

import '../../core/api.dart';
import '../../core/format.dart';
import '../../core/providers.dart';
import '../../core/responsive.dart';
import '../../core/theme.dart';
import '../../shared/widgets/common.dart';
import '../../shared/widgets/score.dart';

const _sections = [
  ('overview', 'Tổng quan', Icons.dashboard_outlined),
  ('users', 'Người dùng', Icons.people_outline),
  ('strategies', 'Chiến lược & tín hiệu', Icons.tune),
  ('jobs', 'Dữ liệu & tác vụ', Icons.storage_outlined),
  ('performance', 'Hiệu quả tín hiệu', Icons.insights_outlined),
  ('config', 'Cấu hình', Icons.settings_outlined),
  ('risk', 'Giới hạn rủi ro & ký quỹ', Icons.shield_outlined),
  ('broadcasts', 'Thông báo chung', Icons.campaign_outlined),
  ('audit', 'Nhật ký kiểm toán', Icons.history),
  ('ai', 'Chi phí AI', Icons.auto_awesome),
];

/// Admin console: light theme, left menu, desktop-first (phone shows a scrollable menu).
class AdminShell extends ConsumerWidget {
  final String section;
  const AdminShell({super.key, required this.section});

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final light = buildTheme(Brightness.light);
    return Theme(
      data: light,
      child: Builder(builder: (context) {
        final c = context.vn;
        final body = switch (section) {
          'users' => const _Users(),
          'strategies' => const _Strategies(),
          'jobs' => const _Jobs(),
          'performance' => const _Performance(),
          'config' => const _Config(),
          'risk' => const _RiskAdmin(),
          'broadcasts' => const _Broadcasts(),
          'audit' => const _Audit(),
          'ai' => const _AiUsage(),
          _ => const _Overview(),
        };
        final menu = Material(type: MaterialType.transparency, child: ListView(padding: const EdgeInsets.symmetric(vertical: 8), children: [
          for (final s in _sections)
            ListTile(
              dense: true, selected: s.$1 == section, selectedTileColor: c.accent.withValues(alpha: 0.1), selectedColor: c.accent,
              leading: Icon(s.$3, size: 20), title: Text(s.$2, style: const TextStyle(fontSize: 13.5)), onTap: () => context.go('/admin/${s.$1}'),
            ),
          const Divider(),
          ListTile(dense: true, leading: const Icon(Icons.exit_to_app, size: 20), title: const Text('Mở ứng dụng', style: TextStyle(fontSize: 13.5)), onTap: () => context.go('/')),
        ]));
        return Scaffold(
          backgroundColor: c.bg,
          appBar: AppBar(
            title: Row(children: [Container(width: 28, height: 28, decoration: BoxDecoration(color: c.accent, borderRadius: BorderRadius.circular(8)), child: const Icon(Icons.show_chart, color: Colors.white, size: 16)), const SizedBox(width: 8), const Text('Vinatrade'), const SizedBox(width: 8), Pill('Quản trị', color: c.accent)]),
            actions: [TextButton.icon(onPressed: () => context.go('/'), icon: const Icon(Icons.exit_to_app, size: 18), label: const Text('Mở ứng dụng')), const SizedBox(width: 8)],
          ),
          drawer: context.isDesktop ? null : Drawer(child: menu),
          body: Row(children: [
            if (context.isDesktop) SizedBox(width: 240, child: Container(decoration: BoxDecoration(color: c.surface, border: Border(right: BorderSide(color: c.line))), child: menu)),
            Expanded(child: SingleChildScrollView(padding: const EdgeInsets.all(24), child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [Text(_sections.firstWhere((s) => s.$1 == section, orElse: () => _sections.first).$2, style: Theme.of(context).textTheme.titleLarge), const SizedBox(height: 16), body]))),
          ]),
        );
      }),
    );
  }
}

// ---------------------------------------------------------------- Overview (A01)
class _Overview extends ConsumerWidget {
  const _Overview();
  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final c = context.vn;
    final d = ref.watch(getMapProvider('/admin/overview'));
    return d.when(
      loading: () => const SkeletonList(),
      error: (e, _) => ErrorBox(e, onRetry: () => ref.invalidate(getProvider('/admin/overview'))),
      data: (o) {
        final k = asMap(o['kpis']);
        final health = o['health']?.toString();
        final steps = asList(o['eod_chain']);
        return Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
          Row(children: [Pill({'GREEN': 'Hệ thống ổn định', 'YELLOW': 'Cần chú ý', 'RED': 'Có lỗi'}[health] ?? '', color: c.levelColor(health), icon: Icons.circle), const SizedBox(width: 12), Text('EOD gần nhất: ${Fmt.relative(Fmt.parseDate(o['last_eod']))}', style: TextStyle(color: c.muted)), const Spacer(), IconButton(onPressed: () => ref.invalidate(getProvider('/admin/overview')), icon: const Icon(Icons.refresh))]),
          const SizedBox(height: 12),
          Wrap(spacing: 12, runSpacing: 12, children: [
            for (final t in [
              ('Người dùng hoạt động', '${k['users_active']}', '${k['active_7d']} trong 7 ngày · ${k['users_pending']} chờ duyệt'),
              ('Độ trễ cảnh báo p95', k['alert_latency_p95_ms'] != null ? '${((asNum(k['alert_latency_p95_ms']) ?? 0) / 1000).toStringAsFixed(1)} s' : '—', 'mục tiêu 60 s'),
              ('Cảnh báo 24h', '${k['alerts_sent_24h']}', '${k['alerts_failed_24h']} thất bại'),
              ('Tỷ lệ thắng tín hiệu mua (20 phiên)', k['signal_win_rate_20'] != null ? '${Fmt.num_(asNum(k['signal_win_rate_20']))}%' : '—', '120 ngày gần nhất'),
              ('Chi phí AI tháng', '\$${Fmt.num_(asNum(k['ai_cost_usd']), decimals: 2)}', 'ngân sách \$${k['ai_budget_usd']}'),
              ('Dung lượng CSDL', '${Fmt.num_(asNum(k['db_size_mb']), decimals: 0)} MB', ''),
            ])
              SizedBox(width: 220, child: KpiTile(label: t.$1, value: t.$2, note: t.$3)),
          ]),
          const SizedBox(height: 16),
          Row(crossAxisAlignment: CrossAxisAlignment.start, children: [
            Expanded(flex: 3, child: AppCard(child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
              Row(children: [Expanded(child: Text('Chuỗi xử lý cuối ngày', style: Theme.of(context).textTheme.titleMedium)), FilledButton.icon(onPressed: () => _run(context, ref, 'eod'), icon: const Icon(Icons.play_arrow, size: 16), label: const Text('Chạy toàn bộ'))]),
              const SizedBox(height: 8),
              for (final s in steps)
                ListTile(
                  dense: true, contentPadding: EdgeInsets.zero,
                  leading: Icon({'DONE': Icons.check_circle, 'WARN': Icons.warning_amber_rounded, 'FAILED': Icons.cancel, 'RUNNING': Icons.autorenew}[s['status']] ?? Icons.radio_button_unchecked, color: {'DONE': c.up, 'WARN': c.ref, 'FAILED': c.down, 'RUNNING': c.accent}[s['status']] ?? c.faint, size: 20),
                  title: Text(s['name'].toString().replaceFirst('eod.', ''), style: const TextStyle(fontWeight: FontWeight.w600, fontSize: 13)),
                  subtitle: Text('${s['summary'] ?? ''}${s['duration_ms'] != null ? ' · ${((asNum(s['duration_ms']) ?? 0) / 1000).toStringAsFixed(1)} s' : ''}${s['error'] != null ? '\n${s['error']}' : ''}', style: TextStyle(fontSize: 11.5, color: s['error'] != null ? c.down : c.muted), maxLines: 3, overflow: TextOverflow.ellipsis),
                  trailing: IconButton(tooltip: 'Chạy lại bước này', icon: const Icon(Icons.replay, size: 18), onPressed: () => _run(context, ref, s['name'].toString())),
                ),
            ]))),
            const SizedBox(width: 16),
            Expanded(flex: 2, child: Column(children: [
              AppCard(child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
                Text('Cần xử lý', style: Theme.of(context).textTheme.titleMedium),
                const SizedBox(height: 6),
                if (asList(o['todo']).isEmpty) Text('Không có việc cần Admin quyết định.', style: TextStyle(color: c.muted, fontSize: 13)),
                for (final t in asList(o['todo'])) ListTile(dense: true, contentPadding: EdgeInsets.zero, title: Text(t['text'].toString()), trailing: FilledButton(style: FilledButton.styleFrom(visualDensity: VisualDensity.compact), onPressed: () => context.go(t['route'].toString().replaceFirst('/admin/users?status=PENDING', '/admin/users')), child: Text(t['action'].toString()))),
              ])),
              const SizedBox(height: 16),
              AppCard(child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
                Text('Nguồn dữ liệu', style: Theme.of(context).textTheme.titleMedium),
                for (final s in asList(o['sources']))
                  ListTile(dense: true, contentPadding: EdgeInsets.zero, leading: StatusDot({'OK': c.up, 'DEGRADED': c.ref, 'DOWN': c.down}[s['status']] ?? c.faint, size: 10), title: Text('${s['name']} · ${s['role'] == 'PRIMARY' ? 'chính' : 'dự phòng'}'), subtitle: Text('${s['latency_ms'] != null ? '${s['latency_ms']} ms · ' : ''}cập nhật ${Fmt.relative(Fmt.parseDate(s['last_ok_at']))}${s['last_error'] != null ? ' · ${s['last_error']}' : ''}', style: TextStyle(fontSize: 11.5, color: c.muted))),
              ])),
            ])),
          ]),
        ]);
      },
    );
  }
}

Future<void> _run(BuildContext context, WidgetRef ref, String name) async {
  try {
    final r = asMap(await ref.read(apiProvider).post('/admin/jobs/$name/run', query: {'confirm': 1}));
    if (context.mounted) showToast(context, r['message']?.toString() ?? 'Đã xếp lịch');
    Future.delayed(const Duration(seconds: 3), () => ref.invalidate(getProvider('/admin/overview')));
  } on ApiException catch (e) {
    if (context.mounted) showToast(context, e.message, error: true);
  }
}

// ---------------------------------------------------------------- Users (A02)
class _Users extends ConsumerStatefulWidget {
  const _Users();
  @override
  ConsumerState<_Users> createState() => _UsersState();
}

class _UsersState extends ConsumerState<_Users> {
  String status = 'PENDING';
  String q = '';
  Map<String, dynamic>? drawer;

  @override
  Widget build(BuildContext context) {
    final c = context.vn;
    final path = '/admin/users?${status == 'ALL' ? '' : 'status=$status&'}q=$q&size=100';
    final data = ref.watch(getMapProvider(path));
    final invites = ref.watch(getListProvider('/admin/invitations'));
    return Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
      data.when(
        loading: () => const SkeletonCard(),
        error: (e, _) => ErrorBox(e),
        data: (d) {
          final counts = asMap(d['counts']);
          return Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
            Row(children: [
              Expanded(child: Wrap(spacing: 6, children: [for (final s in const [('PENDING', 'Chờ duyệt'), ('ACTIVE', 'Đang hoạt động'), ('LOCKED', 'Bị khóa'), ('EXPIRED', 'Hết hạn'), ('REJECTED', 'Từ chối'), ('ALL', 'Tất cả'), ('INVITES', 'Mã mời')]) ChoiceChip(label: Text('${s.$2}${counts[s.$1] != null ? ' · ${counts[s.$1]}' : ''}'), selected: status == s.$1, onSelected: (_) => setState(() => status = s.$1))])),
              SizedBox(width: 220, child: TextField(decoration: const InputDecoration(prefixIcon: Icon(Icons.search, size: 18), hintText: 'Tìm email, tên'), onSubmitted: (v) => setState(() => q = v))),
            ]),
            const SizedBox(height: 12),
            if (status == 'INVITES')
              _Invites(invites: invites)
            else
              Row(crossAxisAlignment: CrossAxisAlignment.start, children: [
                Expanded(
                  child: AppCard(
                    padding: EdgeInsets.zero,
                    child: SingleChildScrollView(
                      scrollDirection: Axis.horizontal,
                      child: DataTable(
                        columns: const [DataColumn(label: Text('Người dùng')), DataColumn(label: Text('Trạng thái')), DataColumn(label: Text('Đăng ký')), DataColumn(label: Text('Nguồn')), DataColumn(label: Text('Đăng nhập gần nhất')), DataColumn(label: Text('Thiết bị')), DataColumn(label: Text(''))],
                        rows: [
                          for (final u in asList(d['items']))
                            DataRow(
                              selected: drawer?['id'] == u['id'],
                              onSelectChanged: (_) => setState(() => drawer = u),
                              cells: [
                                DataCell(Column(mainAxisAlignment: MainAxisAlignment.center, crossAxisAlignment: CrossAxisAlignment.start, children: [Text(u['full_name'].toString(), style: const TextStyle(fontWeight: FontWeight.w600)), Text(u['email'].toString(), style: TextStyle(fontSize: 11.5, color: c.muted))])),
                                DataCell(Row(children: [StatusDot({'ACTIVE': c.up, 'PENDING': c.ref, 'LOCKED': c.down, 'EXPIRED': c.faint, 'REJECTED': c.down}[u['status']] ?? c.faint), const SizedBox(width: 6), Text({'ACTIVE': 'Hoạt động', 'PENDING': 'Chờ duyệt', 'LOCKED': 'Bị khóa', 'EXPIRED': 'Hết hạn', 'REJECTED': 'Từ chối'}[u['status']] ?? u['status'].toString()), if (u['role'] == 'ADMIN') ...[const SizedBox(width: 6), Pill('Admin', color: c.accent, fontSize: 10)]])),
                                DataCell(Text(Fmt.date(Fmt.parseDate(u['created_at']), year: true))),
                                DataCell(Text(u['invited_by_code'] != null ? 'Mã mời ${u['invited_by_code']}' : 'Tự đăng ký')),
                                DataCell(Text(Fmt.relative(Fmt.parseDate(u['last_login_at'])))),
                                DataCell(Text('${u['devices']}')),
                                DataCell(u['status'] == 'PENDING' ? FilledButton(style: FilledButton.styleFrom(visualDensity: VisualDensity.compact), onPressed: () => setState(() => drawer = u), child: const Text('Duyệt')) : TextButton(onPressed: () => setState(() => drawer = u), child: const Text('Chi tiết'))),
                              ],
                            ),
                        ],
                      ),
                    ),
                  ),
                ),
                if (drawer != null) ...[const SizedBox(width: 16), SizedBox(width: 360, child: _UserDrawer(user: drawer!, onClose: () => setState(() => drawer = null), onChanged: () => ref.invalidate(getProvider(path))))],
              ]),
          ]);
        },
      ),
    ]);
  }
}

class _UserDrawer extends ConsumerStatefulWidget {
  final Map<String, dynamic> user;
  final VoidCallback onClose, onChanged;
  const _UserDrawer({required this.user, required this.onClose, required this.onChanged});
  @override
  ConsumerState<_UserDrawer> createState() => _UserDrawerState();
}

class _UserDrawerState extends ConsumerState<_UserDrawer> {
  int? months = 12;
  int devices = 3;
  String role = 'MEMBER';
  final msg = TextEditingController();
  Map<String, dynamic>? detail;

  @override
  void initState() {
    super.initState();
    role = widget.user['role']?.toString() ?? 'MEMBER';
    _load();
  }

  @override
  void didUpdateWidget(covariant _UserDrawer old) {
    super.didUpdateWidget(old);
    if (old.user['id'] != widget.user['id']) _load();
  }

  Future<void> _load() async {
    detail = asMap(await ref.read(apiProvider).get('/admin/users/${widget.user['id']}'));
    if (mounted) setState(() {});
  }

  Future<void> _call(String path, {Object? data, Map<String, dynamic>? query, String? okMsg, String method = 'post'}) async {
    try {
      final api = ref.read(apiProvider);
      method == 'patch' ? await api.patch(path, data: data) : (method == 'delete' ? await api.delete(path) : await api.post(path, data: data, query: query));
      widget.onChanged();
      await _load();
      if (mounted && okMsg != null) showToast(context, okMsg);
    } on ApiException catch (e) {
      if (mounted) showToast(context, e.message, error: true);
    }
  }

  @override
  Widget build(BuildContext context) {
    final c = context.vn;
    final u = detail ?? widget.user;
    final pending = u['status'] == 'PENDING';
    return AppCard(
      child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
        Row(children: [Expanded(child: Text(u['full_name'].toString(), style: Theme.of(context).textTheme.titleMedium)), IconButton(onPressed: widget.onClose, icon: const Icon(Icons.close))]),
        Text('${u['email']}${u['phone'] != null ? ' · ${u['phone']}' : ''}', style: TextStyle(color: c.muted, fontSize: 12.5)),
        Text('Đăng ký ${Fmt.date(Fmt.parseDate(u['created_at']), year: true)} · ${u['invited_by_code'] != null ? 'mã mời ${u['invited_by_code']}' : 'tự đăng ký'}', style: TextStyle(color: c.faint, fontSize: 12)),
        const Divider(),
        if (pending) ...[
          Text('Kích hoạt tài khoản', style: TextStyle(fontWeight: FontWeight.w700, color: c.text)),
          const SizedBox(height: 6),
          DropdownButtonFormField<int?>(initialValue: months, decoration: const InputDecoration(labelText: 'Thời hạn'), items: const [DropdownMenuItem(value: 3, child: Text('3 tháng')), DropdownMenuItem(value: 6, child: Text('6 tháng')), DropdownMenuItem(value: 12, child: Text('12 tháng')), DropdownMenuItem(value: null, child: Text('Không giới hạn'))], onChanged: (v) => setState(() => months = v)),
          const SizedBox(height: 8),
          Row(children: [
            Expanded(child: DropdownButtonFormField<int>(initialValue: devices, decoration: const InputDecoration(labelText: 'Số thiết bị'), items: [for (final n in [1, 2, 3, 5]) DropdownMenuItem(value: n, child: Text('$n'))], onChanged: (v) => setState(() => devices = v ?? 3))),
            const SizedBox(width: 8),
            Expanded(child: DropdownButtonFormField<String>(initialValue: role, decoration: const InputDecoration(labelText: 'Vai trò'), items: const [DropdownMenuItem(value: 'MEMBER', child: Text('Thành viên')), DropdownMenuItem(value: 'ADMIN', child: Text('Admin'))], onChanged: (v) => setState(() => role = v ?? 'MEMBER'))),
          ]),
          const SizedBox(height: 8),
          TextField(controller: msg, minLines: 2, maxLines: 3, decoration: const InputDecoration(labelText: 'Lời nhắn kèm email (tùy chọn)')),
          const SizedBox(height: 10),
          Row(children: [
            OutlinedButton(onPressed: () => _call('/admin/users/${u['id']}/reject', okMsg: 'Đã từ chối'), child: const Text('Từ chối')),
            const Spacer(),
            FilledButton(onPressed: () => _call('/admin/users/${u['id']}/activate', data: {'valid_months': months, 'max_devices': devices, 'role': role, 'message': msg.text.trim().isEmpty ? null : msg.text.trim()}, okMsg: 'Đã kích hoạt ${u['email']}'), child: const Text('Kích hoạt tài khoản')),
          ]),
        ] else ...[
          Wrap(spacing: 14, runSpacing: 6, children: [LabeledValue('Trạng thái', u['status'].toString()), LabeledValue('Vai trò', u['role'].toString()), LabeledValue('Hết hạn', u['expires_at'] != null ? Fmt.date(Fmt.parseDate(u['expires_at']), year: true) : 'Không giới hạn'), LabeledValue('Quy tắc cảnh báo', '${u['alert_rules'] ?? '—'}'), LabeledValue('Mức chi tiết', u['ui_detail']?.toString() ?? '—')]),
          const SizedBox(height: 10),
          Text('Thiết bị', style: TextStyle(fontWeight: FontWeight.w700, color: c.text)),
          for (final d in asList(u['devices'] is List ? u['devices'] : [])) ListTile(dense: true, contentPadding: EdgeInsets.zero, title: Text(d['name']?.toString() ?? d['platform'].toString(), maxLines: 1, overflow: TextOverflow.ellipsis), subtitle: Text(Fmt.relative(Fmt.parseDate(d['last_seen_at'])), style: TextStyle(fontSize: 11.5, color: c.faint)), trailing: IconButton(icon: const Icon(Icons.logout, size: 18), onPressed: () => _call('/admin/users/${u['id']}/devices/${d['id']}', method: 'delete', okMsg: 'Đã đăng xuất thiết bị'))),
          Text('Lịch sử đăng nhập', style: TextStyle(fontWeight: FontWeight.w700, color: c.text)),
          for (final l in asList(u['logins']).take(5)) Text('${Fmt.dateTime(Fmt.parseDate(l['created_at']))} · ${l['action']} · ${l['ip'] ?? ''}', style: TextStyle(fontSize: 12, color: c.muted)),
          Text('Admin không xem được danh mục hay giao dịch của người dùng.', style: TextStyle(fontSize: 11.5, color: c.faint)),
          const Divider(),
          Wrap(spacing: 8, runSpacing: 8, children: [
            OutlinedButton(onPressed: () async {
              final m = await showDialog<int>(context: context, builder: (ctx) => SimpleDialog(title: const Text('Gia hạn thêm'), children: [for (final n in [3, 6, 12]) SimpleDialogOption(onPressed: () => Navigator.pop(ctx, n), child: Text('$n tháng'))]));
              if (m != null) {
                final base = Fmt.parseDate(u['expires_at']) ?? DateTime.now();
                await _call('/admin/users/${u['id']}', method: 'patch', data: {'expires_at': (base.isAfter(DateTime.now()) ? base : DateTime.now()).add(Duration(days: 30 * m)).toUtc().toIso8601String()}, okMsg: 'Đã gia hạn');
              }
            }, child: const Text('Gia hạn')),
            if (u['status'] == 'ACTIVE')
              OutlinedButton(style: OutlinedButton.styleFrom(foregroundColor: c.down), onPressed: () async {
                if (await confirmDialog(context, title: 'Khóa tài khoản ${u['full_name']}?', message: 'Người dùng bị đăng xuất khỏi mọi thiết bị ngay lập tức.', confirmLabel: 'Khóa tài khoản', danger: true)) await _call('/admin/users/${u['id']}/lock', okMsg: 'Đã khóa');
              }, child: const Text('Khóa'))
            else
              FilledButton(onPressed: () => _call('/admin/users/${u['id']}/unlock', okMsg: 'Đã mở khóa'), child: const Text('Mở khóa / kích hoạt')),
            OutlinedButton(onPressed: () async {
              try {
                final r = asMap(await ref.read(apiProvider).patch('/admin/users/${u['id']}', data: {'reset_password': true}));
                if (context.mounted) showDialog(context: context, builder: (ctx) => AlertDialog(title: const Text('Mật khẩu tạm'), content: SelectableText(r['temp_password']?.toString() ?? ''), actions: [TextButton(onPressed: () => Navigator.pop(ctx), child: const Text('Đóng'))]));
              } on ApiException catch (e) {
                if (context.mounted) showToast(context, e.message, error: true);
              }
            }, child: const Text('Đặt lại mật khẩu')),
            TextButton(style: TextButton.styleFrom(foregroundColor: c.down), onPressed: () async {
              if (await confirmDialog(context, title: 'Xóa tài khoản ${u['email']}?', message: 'Toàn bộ dữ liệu cá nhân (danh mục, cảnh báo) sẽ bị xóa, không hoàn tác.', confirmLabel: 'Xóa vĩnh viễn', danger: true)) {
                await _call('/admin/users/${u['id']}', method: 'delete', okMsg: 'Đã xóa');
                widget.onClose();
              }
            }, child: const Text('Xóa')),
          ]),
        ],
      ]),
    );
  }
}

class _Invites extends ConsumerWidget {
  final AsyncValue<List<Map<String, dynamic>>> invites;
  const _Invites({required this.invites});
  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final c = context.vn;
    return AppCard(
      child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
        Row(children: [
          Expanded(child: Text('Mã mời', style: Theme.of(context).textTheme.titleMedium)),
          FilledButton.icon(
            onPressed: () async {
              final email = TextEditingController(), note = TextEditingController();
              bool auto = false;
              int? months = 12;
              final ok = await showDialog<bool>(context: context, builder: (ctx) => StatefulBuilder(builder: (ctx, set) => AlertDialog(title: const Text('Tạo mã mời'), content: SizedBox(width: 360, child: Column(mainAxisSize: MainAxisSize.min, children: [
                TextField(controller: email, decoration: const InputDecoration(labelText: 'Email gắn kèm (tùy chọn)')), const SizedBox(height: 8),
                TextField(controller: note, decoration: const InputDecoration(labelText: 'Ghi chú')), const SizedBox(height: 8),
                DropdownButtonFormField<int?>(initialValue: months, decoration: const InputDecoration(labelText: 'Thời hạn tài khoản'), items: const [DropdownMenuItem(value: 3, child: Text('3 tháng')), DropdownMenuItem(value: 6, child: Text('6 tháng')), DropdownMenuItem(value: 12, child: Text('12 tháng')), DropdownMenuItem(value: null, child: Text('Không giới hạn'))], onChanged: (v) => set(() => months = v)),
                SwitchListTile(contentPadding: EdgeInsets.zero, value: auto, onChanged: (v) => set(() => auto = v), title: const Text('Tự kích hoạt, không cần duyệt')),
              ])), actions: [TextButton(onPressed: () => Navigator.pop(ctx, false), child: const Text('Hủy')), FilledButton(onPressed: () => Navigator.pop(ctx, true), child: const Text('Tạo'))])));
              if (ok != true) return;
              final r = asMap(await ref.read(apiProvider).post('/admin/invitations', data: {'email': email.text.trim().isEmpty ? null : email.text.trim(), 'note': note.text, 'auto_activate': auto, 'valid_months': months}));
              ref.invalidate(getProvider('/admin/invitations'));
              if (context.mounted) showToast(context, 'Đã tạo mã ${r['code']}', actionLabel: 'Sao chép liên kết', onAction: () => Clipboard.setData(ClipboardData(text: r['link'].toString())));
            },
            icon: const Icon(Icons.add, size: 16), label: const Text('Tạo mã'),
          ),
        ]),
        invites.when(
          loading: () => const Skeleton(),
          error: (e, _) => ErrorBox(e),
          data: (rows) => DataTable(
            columns: const [DataColumn(label: Text('Mã')), DataColumn(label: Text('Email')), DataColumn(label: Text('Trạng thái')), DataColumn(label: Text('Tự kích hoạt')), DataColumn(label: Text('Hết hạn')), DataColumn(label: Text(''))],
            rows: [for (final i in rows) DataRow(cells: [DataCell(SelectableText(i['code'].toString(), style: const TextStyle(fontWeight: FontWeight.w700))), DataCell(Text(i['email']?.toString() ?? '—')), DataCell(Text(i['status'].toString())), DataCell(Text(i['auto_activate'] == true ? 'Có' : 'Chờ duyệt')), DataCell(Text(Fmt.date(Fmt.parseDate(i['expires_at']), year: true))), DataCell(Row(children: [IconButton(tooltip: 'Sao chép liên kết', icon: const Icon(Icons.link, size: 18), onPressed: () {
              Clipboard.setData(ClipboardData(text: i['link'].toString()));
              showToast(context, 'Đã sao chép liên kết mời');
            }), IconButton(icon: const Icon(Icons.delete_outline, size: 18), onPressed: () async {
              await ref.read(apiProvider).delete('/admin/invitations/${i['code']}');
              ref.invalidate(getProvider('/admin/invitations'));
            })]))])],
          ),
        ),
        Text('Liên kết mời dạng {web}/register?invite=MÃ', style: TextStyle(color: c.faint, fontSize: 11.5)),
      ]),
    );
  }
}

// ---------------------------------------------------------------- Strategies (A03)
class _Strategies extends ConsumerStatefulWidget {
  const _Strategies();
  @override
  ConsumerState<_Strategies> createState() => _StrategiesState();
}

class _StrategiesState extends ConsumerState<_Strategies> {
  Map<String, Map<String, double>>? weights;

  @override
  Widget build(BuildContext context) {
    final c = context.vn;
    final strategies = ref.watch(getListProvider('/admin/strategies'));
    final config = ref.watch(getListProvider('/admin/config'));
    return Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
      AppCard(
        padding: EdgeInsets.zero,
        child: strategies.when(
          loading: () => const Padding(padding: EdgeInsets.all(16), child: Skeleton()),
          error: (e, _) => ErrorBox(e),
          data: (rows) => SingleChildScrollView(
            scrollDirection: Axis.horizontal,
            child: DataTable(
              columns: const [DataColumn(label: Text('Bật')), DataColumn(label: Text('Chiến lược')), DataColumn(label: Text('Loại')), DataColumn(label: Text('Khung')), DataColumn(label: Text('Phiên bản')), DataColumn(label: Text('Số lệnh')), DataColumn(label: Text('Tỷ lệ đúng')), DataColumn(label: Text('Lợi nhuận TB')), DataColumn(label: Text('Sụt giảm max'))],
              rows: [
                for (final s in rows)
                  DataRow(cells: [
                    DataCell(Switch(value: s['enabled'] == true, onChanged: (v) async {
                      if (v && !await confirmDialog(context, title: 'Bật chiến lược ${s['name']}?', message: 'Tín hiệu sẽ gửi tới người dùng từ phiên tới.', confirmLabel: 'Bật')) return;
                      try {
                        await ref.read(apiProvider).put('/admin/strategies/${s['code']}', data: {'enabled': v});
                        ref.invalidate(getProvider('/admin/strategies'));
                      } on ApiException catch (e) {
                        if (context.mounted) showToast(context, e.message, error: true);
                      }
                    })),
                    DataCell(Column(mainAxisAlignment: MainAxisAlignment.center, crossAxisAlignment: CrossAxisAlignment.start, children: [Text(s['name'].toString(), style: const TextStyle(fontWeight: FontWeight.w600)), Text(s['code'].toString(), style: TextStyle(fontSize: 11, color: c.faint))])),
                    DataCell(Pill(s['signal_type'].toString(), color: {'BUY': c.up, 'SELL': c.down, 'TAKE_PROFIT': c.ref}[s['signal_type']] ?? c.muted, fontSize: 10.5)),
                    DataCell(Text(horizonVi[s['horizon']] ?? '')),
                    DataCell(Text('v${s['version']}')),
                    DataCell(Text('${s['trades'] ?? '—'}')),
                    DataCell(Text(s['win_rate'] != null ? '${Fmt.num_(asNum(s['win_rate']))}%' : '—', style: TextStyle(color: (asNum(s['win_rate']) ?? 50) >= 55 ? c.up : null))),
                    DataCell(Text(Fmt.pct(asNum(s['avg_return'])))),
                    DataCell(Text(Fmt.pct(asNum(s['max_drawdown'])))),
                  ]),
              ],
            ),
          ),
        ),
      ),
      const SizedBox(height: 16),
      config.when(
        loading: () => const SkeletonCard(),
        error: (e, _) => ErrorBox(e),
        data: (rows) {
          final w = asMap(rows.firstWhere((r) => r['key'] == 'scoring.weights', orElse: () => {})['value']);
          weights ??= {for (final hz in ['SHORT', 'MID', 'LONG']) hz: {for (final k in ['tech', 'fund', 'sector', 'pattern']) k: (asNum(asMap(w[hz])[k]) ?? 25).toDouble()}};
          return AppCard(
            child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
              Text('Trọng số điểm tổng hợp', style: Theme.of(context).textTheme.titleMedium),
              Text('Kỹ thuật · Cơ bản · Ngành/vĩ mô · Nền giá & AI — tổng mỗi khung phải bằng 100%.', style: TextStyle(color: c.muted, fontSize: 12.5)),
              const SizedBox(height: 10),
              Row(crossAxisAlignment: CrossAxisAlignment.start, children: [
                for (final hz in ['SHORT', 'MID', 'LONG'])
                  Expanded(
                    child: Padding(
                      padding: const EdgeInsets.only(right: 12),
                      child: Builder(builder: (_) {
                        final sum = weights![hz]!.values.fold<double>(0, (a, b) => a + b);
                        return Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
                          Row(children: [Text(horizonVi[hz]!, style: const TextStyle(fontWeight: FontWeight.w700)), const Spacer(), Text('${sum.round()}%', style: TextStyle(color: (sum - 100).abs() > 0.5 ? c.down : c.up, fontWeight: FontWeight.w700))]),
                          for (final k in [('tech', 'Kỹ thuật'), ('fund', 'Cơ bản'), ('sector', 'Ngành'), ('pattern', 'Nền giá & AI')])
                            Row(children: [SizedBox(width: 90, child: Text(k.$2, style: const TextStyle(fontSize: 12))), Expanded(child: Slider(value: weights![hz]![k.$1]!, min: 0, max: 100, divisions: 20, label: '${weights![hz]![k.$1]!.round()}%', onChanged: (v) => setState(() => weights![hz]![k.$1] = v))), SizedBox(width: 36, child: Text('${weights![hz]![k.$1]!.round()}%', style: const TextStyle(fontSize: 12)))]),
                        ]);
                      }),
                    ),
                  ),
              ]),
              Row(children: [
                TextButton(onPressed: () async {
                  await ref.read(apiProvider).post('/admin/config/scoring.weights/reset');
                  setState(() => weights = null);
                  ref.invalidate(getProvider('/admin/config'));
                }, child: const Text('Khôi phục mặc định')),
                const Spacer(),
                FilledButton(onPressed: () async {
                  try {
                    await ref.read(apiProvider).put('/admin/config/scoring.weights', data: {'value': {for (final e in weights!.entries) e.key: {for (final k in e.value.entries) k.key: k.value.round()}}});
                    ref.invalidate(getProvider('/admin/config'));
                    if (context.mounted) showToast(context, 'Đã lưu trọng số. Áp dụng từ lần chấm điểm tới (chạy lại bước scores để thấy ngay).');
                  } on ApiException catch (e) {
                    if (context.mounted) showToast(context, e.message, error: true);
                  }
                }, child: const Text('Lưu trọng số')),
              ]),
            ]),
          );
        },
      ),
    ]);
  }
}

// ---------------------------------------------------------------- Jobs & data (A04)
class _Jobs extends ConsumerStatefulWidget {
  const _Jobs();
  @override
  ConsumerState<_Jobs> createState() => _JobsState();
}

class _JobsState extends ConsumerState<_Jobs> {
  Map<String, dynamic>? preview;
  bool importing = false;

  @override
  Widget build(BuildContext context) {
    final c = context.vn;
    final jobs = ref.watch(getMapProvider('/admin/jobs?limit=60'));
    final ds = ref.watch(getMapProvider('/admin/data-sources'));
    return Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
      ds.when(
        loading: () => const SkeletonCard(),
        error: (e, _) => ErrorBox(e),
        data: (d) => Row(crossAxisAlignment: CrossAxisAlignment.start, children: [
          Expanded(child: AppCard(child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
            Text('Nguồn dữ liệu', style: Theme.of(context).textTheme.titleMedium),
            for (final s in asList(d['sources']))
              ListTile(dense: true, contentPadding: EdgeInsets.zero, leading: StatusDot({'OK': c.up, 'DEGRADED': c.ref, 'DOWN': c.down}[s['status']] ?? c.faint, size: 10), title: Text('${s['name']} (${s['code']})'), subtitle: Text('${s['role'] == 'PRIMARY' ? 'Chính' : 'Dự phòng'} · ưu tiên ${s['priority']} · ${s['latency_ms'] ?? '—'} ms · lỗi liên tiếp ${s['consecutive_failures']}', style: TextStyle(fontSize: 11.5, color: c.muted)),
                  trailing: Switch(value: s['enabled'] == true, onChanged: (v) async {
                    await ref.read(apiProvider).put('/admin/data-sources/${s['code']}', query: {'enabled': v});
                    ref.invalidate(getProvider('/admin/data-sources'));
                  })),
            Text('Giá gần nhất: ${Fmt.date(Fmt.parseDate(asMap(d['coverage'])['last_price_date']), year: true)} · ${asMap(d['coverage'])['symbols_with_prices']} mã', style: TextStyle(color: c.faint, fontSize: 12)),
          ]))),
          const SizedBox(width: 16),
          Expanded(child: AppCard(child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
            Text('Chất lượng dữ liệu', style: Theme.of(context).textTheme.titleMedium),
            for (final q in asList(d['quality'])) ListTile(dense: true, contentPadding: EdgeInsets.zero, leading: Icon(q['ok'] == true ? Icons.check_circle_outline : Icons.warning_amber_rounded, color: q['ok'] == true ? c.up : c.ref, size: 20), title: Text(q['check'].toString()), trailing: Text('${q['value']}', style: const TextStyle(fontWeight: FontWeight.w700))),
          ]))),
        ]),
      ),
      const SizedBox(height: 16),
      AppCard(child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
        Row(children: [Expanded(child: Text('Nhập file giá dự phòng', style: Theme.of(context).textTheme.titleMedium)), FilledButton.icon(onPressed: importing ? null : _pick, icon: const Icon(Icons.upload_file, size: 16), label: const Text('Chọn CSV / TXT / Excel'))]),
        Text('Cột nhận dạng theo tên tiếng Việt hoặc Anh: mã, ngày, mở cửa, cao nhất, thấp nhất, đóng cửa, khối lượng. Tối đa 20 MB.', style: TextStyle(color: c.muted, fontSize: 12.5)),
        if (preview != null) ...[
          const SizedBox(height: 10),
          Wrap(spacing: 16, runSpacing: 6, children: [LabeledValue('Tệp', preview!['filename'].toString()), LabeledValue('Đơn vị', preview!['unit'].toString()), LabeledValue('Dòng hợp lệ', '${preview!['rows_ok']}'), LabeledValue('Dòng lỗi', '${preview!['rows_error']}', color: (asInt(preview!['rows_error']) ?? 0) > 0 ? c.down : null), LabeledValue('Phiên mới', '${preview!['new_sessions']}'), LabeledValue('Trùng', '${preview!['duplicate_sessions']}'), LabeledValue('Lệch > 0,5%', '${asList(preview!['mismatches']).length}')]),
          const SizedBox(height: 8),
          SingleChildScrollView(scrollDirection: Axis.horizontal, child: DataTable(columns: const [DataColumn(label: Text('Mã')), DataColumn(label: Text('Ngày')), DataColumn(label: Text('Mở')), DataColumn(label: Text('Cao')), DataColumn(label: Text('Thấp')), DataColumn(label: Text('Đóng')), DataColumn(label: Text('KL'))], rows: [for (final r in asList(preview!['preview'])) DataRow(cells: [DataCell(Text(r['symbol'].toString())), DataCell(Text(r['date'].toString())), DataCell(Text(Fmt.price(asNum(r['open'])))), DataCell(Text(Fmt.price(asNum(r['high'])))), DataCell(Text(Fmt.price(asNum(r['low'])))), DataCell(Text(Fmt.price(asNum(r['close'])))), DataCell(Text(Fmt.volume(asNum(r['volume']))))])])),
          if (asList(preview!['errors']).isNotEmpty) Padding(padding: const EdgeInsets.only(top: 6), child: Text('Lỗi: ${asList(preview!['errors']).take(10).map((e) => 'dòng ${e['row']}: ${e['error']}').join('; ')}', style: TextStyle(color: c.down, fontSize: 12))),
          if (asList(preview!['mismatches']).isNotEmpty) Padding(padding: const EdgeInsets.only(top: 6), child: Text('Lệch so với API: ${asList(preview!['mismatches']).take(8).map((m) => '${m['symbol']} ${m['date']} file ${Fmt.price(asNum(m['file']))} / API ${Fmt.price(asNum(m['api']))}').join('; ')}', style: TextStyle(color: c.ref, fontSize: 12))),
          const SizedBox(height: 8),
          Row(children: [FilledButton(onPressed: () => _commit('SKIP_EXISTING'), child: const Text('Ghi (bỏ qua trùng)')), const SizedBox(width: 8), OutlinedButton(onPressed: () => _commit('OVERWRITE'), child: const Text('Ghi đè')), const SizedBox(width: 8), TextButton(onPressed: () => setState(() => preview = null), child: const Text('Hủy'))]),
        ],
      ])),
      const SizedBox(height: 16),
      jobs.when(
        loading: () => const SkeletonCard(),
        error: (e, _) => ErrorBox(e),
        data: (j) => Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
          AppCard(child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
            Text('Lịch chạy', style: Theme.of(context).textTheme.titleMedium),
            for (final s in asList(j['schedule'])) ListTile(dense: true, contentPadding: EdgeInsets.zero, title: Text(s['name'].toString()), subtitle: Text('${s['trigger']} · lần tới ${Fmt.dateTime(Fmt.parseDate(s['next_run']))}', style: TextStyle(fontSize: 11.5, color: c.muted)), trailing: TextButton(onPressed: () => _run(context, ref, s['id'] == 'eod' ? 'eod' : s['id'].toString()), child: const Text('Chạy ngay'))),
            if (asList(j['schedule']).isEmpty) Text('Bộ lập lịch chưa chạy trong tiến trình này.', style: TextStyle(color: c.muted)),
          ])),
          const SizedBox(height: 16),
          AppCard(
            padding: EdgeInsets.zero,
            child: SingleChildScrollView(
              scrollDirection: Axis.horizontal,
              child: DataTable(
                columns: const [DataColumn(label: Text('Tác vụ')), DataColumn(label: Text('Trạng thái')), DataColumn(label: Text('Bắt đầu')), DataColumn(label: Text('Thời gian')), DataColumn(label: Text('Kết quả')), DataColumn(label: Text('Kích hoạt bởi')), DataColumn(label: Text(''))],
                rows: [
                  for (final r in asList(j['runs']))
                    DataRow(cells: [
                      DataCell(Text(r['name'].toString(), style: const TextStyle(fontWeight: FontWeight.w600))),
                      DataCell(Pill(r['status'].toString(), color: {'DONE': c.up, 'WARN': c.ref, 'FAILED': c.down, 'RUNNING': c.accent}[r['status']] ?? c.muted, fontSize: 10.5)),
                      DataCell(Text(Fmt.dateTime(Fmt.parseDate(r['started_at'])))),
                      DataCell(Text(r['duration_ms'] != null ? '${((asNum(r['duration_ms']) ?? 0) / 1000).toStringAsFixed(1)} s' : '—')),
                      DataCell(SizedBox(width: 360, child: Text((r['error'] ?? r['summary'])?.toString() ?? '', maxLines: 2, overflow: TextOverflow.ellipsis, style: TextStyle(fontSize: 12, color: r['error'] != null ? c.down : null)))),
                      DataCell(Text(r['triggered_by']?.toString() ?? '')),
                      DataCell(r['name'].toString().startsWith('eod.') ? IconButton(icon: const Icon(Icons.replay, size: 18), onPressed: () => _run(context, ref, r['name'].toString())) : const SizedBox()),
                    ]),
                ],
              ),
            ),
          ),
        ]),
      ),
    ]);
  }

  Future<void> _pick() async {
    final picked = await FilePicker.pickFiles(type: FileType.custom, allowedExtensions: ['csv', 'txt', 'xlsx']);
    if (picked.isEmpty) return;
    setState(() => importing = true);
    try {
      final bytes = await picked.first.xFile.readAsBytes();
      preview = asMap(await ref.read(apiProvider).upload('/admin/price-imports', bytes, picked.first.name));
    } on ApiException catch (e) {
      if (mounted) showToast(context, e.message, error: true);
    } finally {
      if (mounted) setState(() => importing = false);
    }
  }

  Future<void> _commit(String mode) async {
    try {
      final r = asMap(await ref.read(apiProvider).post('/admin/price-imports/${preview!['import_id']}/commit', query: {'mode': mode}));
      setState(() => preview = null);
      ref.invalidate(getProvider('/admin/jobs?limit=60'));
      if (mounted) showToast(context, 'Đã ghi ${r['rows']} dòng cho ${(r['symbols'] as List? ?? []).length} mã. Đang tính lại chỉ báo, điểm, tín hiệu.');
    } on ApiException catch (e) {
      if (mounted) showToast(context, e.message, error: true);
    }
  }
}

// ---------------------------------------------------------------- Performance (A10)
class _Performance extends ConsumerStatefulWidget {
  const _Performance();
  @override
  ConsumerState<_Performance> createState() => _PerformanceState();
}

class _PerformanceState extends ConsumerState<_Performance> {
  int months = 12, days = 20;
  @override
  Widget build(BuildContext context) {
    final c = context.vn;
    final d = ref.watch(getMapProvider('/admin/strategies/performance?months=$months&days=$days'));
    return Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
      Row(children: [
        Segmented<int>(options: const [(3, '3 tháng'), (12, '12 tháng'), (60, '5 năm')], value: months, onChanged: (v) => setState(() => months = v)),
        const SizedBox(width: 12),
        Segmented<int>(options: const [(10, '10 phiên'), (20, '20 phiên')], value: days, onChanged: (v) => setState(() => days = v)),
      ]),
      const SizedBox(height: 12),
      d.when(
        loading: () => const SkeletonList(),
        error: (e, _) => ErrorBox(e),
        data: (p) {
          final k = asMap(p['kpis']);
          final regimes = ['UPTREND', 'PRESSURE', 'CORRECTION', 'DOWNTREND'];
          final byStrat = <String, Map<String, Map<String, dynamic>>>{};
          for (final r in asList(p['by_strategy_regime'])) {
            byStrat.putIfAbsent('${r['strategy']} · ${horizonVi[r['horizon']] ?? ''}', () => {})[r['regime'].toString()] = r;
          }
          return Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
            Wrap(spacing: 12, runSpacing: 12, children: [
              SizedBox(width: 220, child: KpiTile(label: 'Tín hiệu mua đã phát', value: '${k['buy_signals']}')),
              SizedBox(width: 220, child: KpiTile(label: 'Đạt chốt lời 1 trước cắt lỗ', value: k['tp1_rate'] != null ? '${Fmt.num_(asNum(k['tp1_rate']))}%' : '—', note: 'mục tiêu ${k['target_tp1_rate']}%', valueColor: (asNum(k['tp1_rate']) ?? 0) >= 55 ? c.up : c.ref)),
              SizedBox(width: 220, child: KpiTile(label: 'Lợi nhuận TB sau phí', value: Fmt.pct(asNum(k['avg_return'])), valueColor: c.changeColor(asNum(k['avg_return'])))),
              SizedBox(width: 220, child: KpiTile(label: 'VN-Index cùng kỳ', value: Fmt.pct(asNum(k['vnindex_return'])), valueColor: c.changeColor(asNum(k['vnindex_return'])))),
            ]),
            const SizedBox(height: 16),
            if (asList(p['by_strategy_regime']).isEmpty) AppCard(child: Text('Chưa có kết quả tín hiệu để đánh giá (cần tối thiểu $days phiên sau khi phát). Số liệu sẽ tích lũy theo thời gian.', style: TextStyle(color: c.muted))),
            if (byStrat.isNotEmpty)
              AppCard(
                padding: EdgeInsets.zero,
                child: SingleChildScrollView(
                  scrollDirection: Axis.horizontal,
                  child: DataTable(
                    columns: [const DataColumn(label: Text('Chiến lược × thị trường')), for (final r in regimes) DataColumn(label: Text(regimeVi[r]!)), const DataColumn(label: Text('Gợi ý'))],
                    rows: [
                      for (final e in byStrat.entries)
                        DataRow(cells: [
                          DataCell(Text(e.key, style: const TextStyle(fontWeight: FontWeight.w600))),
                          for (final r in regimes)
                            DataCell(Builder(builder: (_) {
                              final x = e.value[r];
                              if (x == null) return Text('—', style: TextStyle(color: c.faint));
                              final n = asInt(x['samples']) ?? 0, wr = asNum(x['win_rate']) ?? 0;
                              return Opacity(opacity: n < 30 ? 0.45 : 1, child: Container(padding: const EdgeInsets.symmetric(horizontal: 8, vertical: 4), decoration: BoxDecoration(color: (wr >= 55 ? c.up : (wr >= 45 ? c.ref : c.down)).withValues(alpha: 0.18), borderRadius: BorderRadius.circular(6)), child: Text('${wr.toStringAsFixed(0)}% ($n)', style: const TextStyle(fontWeight: FontWeight.w600))));
                            })),
                          DataCell(Text(e.value.values.map((x) => x['suggestion']).firstWhere((s) => s == 'Tắt khi thị trường này', orElse: () => e.value.values.first['suggestion']).toString(), style: TextStyle(fontSize: 12, color: c.muted))),
                        ]),
                    ],
                  ),
                ),
              ),
            const SizedBox(height: 16),
            Row(crossAxisAlignment: CrossAxisAlignment.start, children: [
              Expanded(child: AppCard(child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [Text('Theo khuyến nghị', style: Theme.of(context).textTheme.titleMedium), for (final r in asList(p['by_rating'])) ListTile(dense: true, contentPadding: EdgeInsets.zero, title: Text(ratingVi[r['rating']] ?? r['rating'].toString()), trailing: Text('${r['samples']} tín hiệu · đúng ${Fmt.num_(asNum(r['win_rate']))}% · ${Fmt.pct(asNum(r['avg_return']))}'))]))),
              const SizedBox(width: 16),
              Expanded(child: AppCard(child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [Text('Theo ngành', style: Theme.of(context).textTheme.titleMedium), for (final r in asList(p['by_sector']).take(12)) ListTile(dense: true, contentPadding: EdgeInsets.zero, title: Text(r['name'].toString()), trailing: Pill('${Fmt.num_(asNum(r['win_rate']))}% (${r['samples']})', color: (asNum(r['win_rate']) ?? 0) >= 55 ? c.up : ((asNum(r['win_rate']) ?? 0) >= 45 ? c.ref : c.down)))]))),
            ]),
            const SizedBox(height: 16),
            AppCard(child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [Text('Theo tháng', style: Theme.of(context).textTheme.titleMedium), SingleChildScrollView(scrollDirection: Axis.horizontal, child: DataTable(columns: const [DataColumn(label: Text('Tháng')), DataColumn(label: Text('Tín hiệu')), DataColumn(label: Text('Tỷ lệ đúng')), DataColumn(label: Text('Lợi nhuận TB'))], rows: [for (final m in asList(p['monthly'])) DataRow(cells: [DataCell(Text(m['month'].toString())), DataCell(Text('${m['samples']}')), DataCell(Text('${Fmt.num_(asNum(m['win_rate']))}%')), DataCell(Text(Fmt.pct(asNum(m['avg_return'])), style: TextStyle(color: c.changeColor(asNum(m['avg_return'])))))])]))])),
          ]);
        },
      ),
    ]);
  }
}

// ---------------------------------------------------------------- Config (A05)
class _Config extends ConsumerWidget {
  const _Config();
  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final c = context.vn;
    final rows = ref.watch(getListProvider('/admin/config'));
    return rows.when(
      loading: () => const SkeletonList(),
      error: (e, _) => ErrorBox(e),
      data: (list) {
        final groups = <String, List<Map<String, dynamic>>>{};
        for (final r in list) {
          groups.putIfAbsent(r['group']?.toString() ?? 'khác', () => []).add(r);
        }
        return Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
          for (final g in groups.entries) ...[
            Text({'scoring': 'Chấm điểm', 'strategy': 'Chiến lược', 'risk': 'Rủi ro', 'market': 'Thông số sàn', 'alerts': 'Cảnh báo', 'ai': 'AI', 'macro': 'Vĩ mô'}[g.key] ?? g.key, style: Theme.of(context).textTheme.titleMedium),
            const SizedBox(height: 8),
            for (final r in g.value) _ConfigRow(r: r, onChanged: () => ref.invalidate(getProvider('/admin/config'))),
            const SizedBox(height: 12),
          ],
          Text('Mọi thay đổi được ghi vào nhật ký kiểm toán và áp dụng từ lần xử lý tới.', style: TextStyle(color: c.faint, fontSize: 12)),
        ]);
      },
    );
  }
}

class _ConfigRow extends ConsumerStatefulWidget {
  final Map<String, dynamic> r;
  final VoidCallback onChanged;
  const _ConfigRow({required this.r, required this.onChanged});
  @override
  ConsumerState<_ConfigRow> createState() => _ConfigRowState();
}

class _ConfigRowState extends ConsumerState<_ConfigRow> {
  late final ctl = TextEditingController(text: const JsonEncoder.withIndent('  ').convert(widget.r['value']));
  bool editing = false;
  @override
  Widget build(BuildContext context) {
    final c = context.vn;
    final r = widget.r;
    return AppCard(
      padding: const EdgeInsets.all(12),
      child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
        Row(children: [
          Expanded(child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [Text(r['key'].toString(), style: const TextStyle(fontWeight: FontWeight.w700, fontFamily: 'monospace', fontSize: 13)), Text(r['description']?.toString() ?? '', style: TextStyle(color: c.muted, fontSize: 12))])),
          if (r['updated_by'] != null) Text('${r['updated_by']} · ${Fmt.relative(Fmt.parseDate(r['updated_at']))}', style: TextStyle(color: c.faint, fontSize: 11)),
          TextButton(onPressed: () => setState(() => editing = !editing), child: Text(editing ? 'Đóng' : 'Sửa')),
          TextButton(onPressed: () async {
            if (await confirmDialog(context, title: 'Khôi phục mặc định?', message: r['key'].toString(), confirmLabel: 'Khôi phục')) {
              await ref.read(apiProvider).post('/admin/config/${r['key']}/reset');
              widget.onChanged();
            }
          }, child: const Text('Mặc định')),
        ]),
        if (!editing) Text(jsonEncode(r['value']), maxLines: 2, overflow: TextOverflow.ellipsis, style: TextStyle(fontFamily: 'monospace', fontSize: 11.5, color: c.muted)),
        if (editing) ...[
          TextField(controller: ctl, minLines: 2, maxLines: 14, style: const TextStyle(fontFamily: 'monospace', fontSize: 12)),
          const SizedBox(height: 6),
          Align(alignment: Alignment.centerRight, child: FilledButton(onPressed: () async {
            try {
              final v = jsonDecode(ctl.text);
              await ref.read(apiProvider).put('/admin/config/${r['key']}', data: {'value': v});
              setState(() => editing = false);
              widget.onChanged();
              if (context.mounted) showToast(context, 'Đã lưu ${r['key']}');
            } on FormatException {
              showToast(context, 'JSON không hợp lệ', error: true);
            } on ApiException catch (e) {
              if (context.mounted) showToast(context, e.message, error: true);
            }
          }, child: const Text('Lưu'))),
        ],
      ]),
    );
  }
}

// ---------------------------------------------------------------- Risk defaults (A09)
class _RiskAdmin extends ConsumerWidget {
  const _RiskAdmin();
  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final c = context.vn;
    final stats = ref.watch(getMapProvider('/admin/risk-stats'));
    final cfg = ref.watch(getListProvider('/admin/config'));
    return Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
      stats.when(
        loading: () => const SkeletonCard(),
        error: (e, _) => ErrorBox(e),
        data: (s) => Wrap(spacing: 12, runSpacing: 12, children: [
          for (final e in [('Cầu dao bật', 'GUARD_ON'), ('Hạ cắt lỗ', 'STOP_LOWERED'), ('Bình quân giá xuống', 'AVERAGE_DOWN'), ('Vượt rào Đỏ', 'RED_OVERRIDE')]) SizedBox(width: 200, child: KpiTile(label: '${e.$1} (${s['days']} ngày)', value: '${asMap(s['events'])[e.$2] ?? 0}')),
          for (final e in [('Kiểm tra Xanh', 'GREEN'), ('Vàng', 'YELLOW'), ('Đỏ', 'RED')]) SizedBox(width: 160, child: KpiTile(label: e.$1, value: '${asMap(s['pretrade'])[e.$2] ?? 0}', valueColor: c.levelColor(e.$2))),
        ]),
      ),
      const SizedBox(height: 16),
      Text('Thống kê toàn hệ thống, không xem chi tiết giao dịch cá nhân.', style: TextStyle(color: c.faint, fontSize: 12)),
      const SizedBox(height: 12),
      cfg.when(
        loading: () => const SkeletonCard(),
        error: (e, _) => ErrorBox(e),
        data: (rows) => Column(children: [for (final r in rows.where((r) => r['group'] == 'risk')) _ConfigRow(r: r, onChanged: () => ref.invalidate(getProvider('/admin/config')))]),
      ),
      const SizedBox(height: 12),
      _MarginLists(),
    ]);
  }
}

class _MarginLists extends ConsumerStatefulWidget {
  @override
  ConsumerState<_MarginLists> createState() => _MarginListsState();
}

class _MarginListsState extends ConsumerState<_MarginLists> {
  final ctl = TextEditingController();
  bool loaded = false;
  @override
  Widget build(BuildContext context) {
    final c = context.vn;
    final data = ref.watch(getMapProvider('/admin/margin-lists'));
    return data.when(
      loading: () => const Skeleton(),
      error: (e, _) => const SizedBox.shrink(),
      data: (m) {
        if (!loaded) {
          ctl.text = m.entries.map((e) => '${e.key}: ${(e.value as List).join(', ')}').join('\n');
          loaded = true;
        }
        return AppCard(child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
          Text('Danh sách mã cho vay ký quỹ theo công ty chứng khoán', style: Theme.of(context).textTheme.titleMedium),
          Text('Mỗi dòng: TÊN CTCK: MÃ1, MÃ2, …', style: TextStyle(color: c.muted, fontSize: 12.5)),
          const SizedBox(height: 8),
          TextField(controller: ctl, minLines: 3, maxLines: 10, style: const TextStyle(fontFamily: 'monospace', fontSize: 12)),
          const SizedBox(height: 8),
          Align(alignment: Alignment.centerRight, child: FilledButton(onPressed: () async {
            final body = <String, List<String>>{};
            for (final ln in ctl.text.split('\n')) {
              final i = ln.indexOf(':');
              if (i <= 0) continue;
              body[ln.substring(0, i).trim()] = ln.substring(i + 1).split(',').map((s) => s.trim().toUpperCase()).where((s) => s.isNotEmpty).toList();
            }
            await ref.read(apiProvider).put('/admin/margin-lists', data: body);
            if (context.mounted) showToast(context, 'Đã lưu danh sách ký quỹ');
          }, child: const Text('Lưu'))),
        ]));
      },
    );
  }
}

// ---------------------------------------------------------------- Broadcasts (A06)
class _Broadcasts extends ConsumerStatefulWidget {
  const _Broadcasts();
  @override
  ConsumerState<_Broadcasts> createState() => _BroadcastsState();
}

class _BroadcastsState extends ConsumerState<_Broadcasts> {
  final title = TextEditingController(), body = TextEditingController();
  final channels = {'push', 'telegram'};
  @override
  Widget build(BuildContext context) {
    final c = context.vn;
    final hist = ref.watch(getListProvider('/admin/broadcasts'));
    return Row(crossAxisAlignment: CrossAxisAlignment.start, children: [
      Expanded(child: AppCard(child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
        Text('Soạn thông báo', style: Theme.of(context).textTheme.titleMedium),
        const SizedBox(height: 8),
        TextField(controller: title, decoration: const InputDecoration(labelText: 'Tiêu đề'), onChanged: (_) => setState(() {})),
        const SizedBox(height: 8),
        TextField(controller: body, minLines: 3, maxLines: 6, decoration: const InputDecoration(labelText: 'Nội dung'), onChanged: (_) => setState(() {})),
        const SizedBox(height: 8),
        Wrap(spacing: 6, children: [for (final ch in const [('push', 'Thông báo đẩy'), ('telegram', 'Telegram'), ('email', 'Email')]) FilterChip(label: Text(ch.$2), selected: channels.contains(ch.$1), onSelected: (v) => setState(() => v ? channels.add(ch.$1) : channels.remove(ch.$1)))]),
        const SizedBox(height: 10),
        Align(alignment: Alignment.centerRight, child: FilledButton(onPressed: title.text.trim().isEmpty ? null : () async {
          if (!await confirmDialog(context, title: 'Gửi cho tất cả người dùng?', message: title.text, confirmLabel: 'Gửi')) return;
          try {
            final r = asMap(await ref.read(apiProvider).post('/admin/broadcasts', data: {'title': title.text.trim(), 'body': body.text.trim(), 'channels': channels.toList()}));
            title.clear();
            body.clear();
            ref.invalidate(getProvider('/admin/broadcasts'));
            if (context.mounted) showToast(context, 'Đã gửi tới ${r['sent_count']} người dùng');
          } on ApiException catch (e) {
            if (context.mounted) showToast(context, e.message, error: true);
          }
        }, child: const Text('Gửi thông báo'))),
      ]))),
      const SizedBox(width: 16),
      SizedBox(width: 320, child: Column(children: [
        AppCard(color: const Color(0xFF0B1119), child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [Text('Xem trước trên điện thoại', style: TextStyle(color: const Color(0xFF8E9BAC), fontSize: 11)), const SizedBox(height: 6), Text(title.text.isEmpty ? 'Tiêu đề' : title.text, style: const TextStyle(color: Color(0xFFE8EEF5), fontWeight: FontWeight.w700)), Text(body.text.isEmpty ? 'Nội dung thông báo…' : body.text, style: const TextStyle(color: Color(0xFFA3B0C0), fontSize: 13))])),
        const SizedBox(height: 16),
        AppCard(child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
          Text('Đã gửi', style: Theme.of(context).textTheme.titleMedium),
          hist.when(loading: () => const Skeleton(), error: (e, _) => const SizedBox.shrink(), data: (rows) => Column(children: [for (final b in rows) ListTile(dense: true, contentPadding: EdgeInsets.zero, title: Text(b['title'].toString(), maxLines: 1, overflow: TextOverflow.ellipsis), subtitle: Text('${Fmt.relative(Fmt.parseDate(b['created_at']))} · ${b['sent_count']} người', style: TextStyle(fontSize: 11.5, color: c.muted)))])),
        ])),
      ])),
    ]);
  }
}

// ---------------------------------------------------------------- Audit (A07)
class _Audit extends ConsumerStatefulWidget {
  const _Audit();
  @override
  ConsumerState<_Audit> createState() => _AuditState();
}

class _AuditState extends ConsumerState<_Audit> {
  String? action;
  String actor = '';
  @override
  Widget build(BuildContext context) {
    final c = context.vn;
    final d = ref.watch(getMapProvider('/admin/audit-logs?size=100${action != null ? '&action=$action' : ''}${actor.isNotEmpty ? '&actor=$actor' : ''}'));
    return d.when(
      loading: () => const SkeletonList(),
      error: (e, _) => ErrorBox(e),
      data: (a) => Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
        Row(children: [
          SizedBox(width: 240, child: DropdownButtonFormField<String?>(initialValue: action, decoration: const InputDecoration(labelText: 'Hành động'), items: [const DropdownMenuItem(value: null, child: Text('Tất cả')), for (final x in (a['actions'] as List? ?? [])) DropdownMenuItem(value: x.toString(), child: Text(x.toString()))], onChanged: (v) => setState(() => action = v))),
          const SizedBox(width: 12),
          SizedBox(width: 240, child: TextField(decoration: const InputDecoration(labelText: 'Người thực hiện'), onSubmitted: (v) => setState(() => actor = v))),
        ]),
        const SizedBox(height: 12),
        AppCard(
          padding: EdgeInsets.zero,
          child: SingleChildScrollView(
            scrollDirection: Axis.horizontal,
            child: DataTable(
              columns: const [DataColumn(label: Text('Thời gian')), DataColumn(label: Text('Người thực hiện')), DataColumn(label: Text('Hành động')), DataColumn(label: Text('Đối tượng')), DataColumn(label: Text('IP')), DataColumn(label: Text('Trước / sau'))],
              rows: [
                for (final r in asList(a['items']))
                  DataRow(cells: [
                    DataCell(Text(Fmt.dateTime(Fmt.parseDate(r['created_at'])))),
                    DataCell(Text(r['actor_email']?.toString() ?? '—')),
                    DataCell(Pill(r['action'].toString(), color: c.accent, fontSize: 10.5)),
                    DataCell(Text('${r['target_type'] ?? ''} ${r['target_id'] ?? ''}', style: TextStyle(fontSize: 12, color: c.muted))),
                    DataCell(Text(r['ip']?.toString() ?? '')),
                    DataCell(SizedBox(width: 420, child: Text('${r['before'] != null ? '− ${jsonEncode(r['before'])}\n' : ''}${r['after'] != null ? '+ ${jsonEncode(r['after'])}' : ''}', maxLines: 3, overflow: TextOverflow.ellipsis, style: TextStyle(fontFamily: 'monospace', fontSize: 11, color: c.muted)))),
                  ]),
              ],
            ),
          ),
        ),
      ]),
    );
  }
}

// ---------------------------------------------------------------- AI cost (A08)
class _AiUsage extends ConsumerWidget {
  const _AiUsage();
  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final c = context.vn;
    final d = ref.watch(getMapProvider('/admin/ai-usage?days=30'));
    return d.when(
      loading: () => const SkeletonList(),
      error: (e, _) => ErrorBox(e),
      data: (u) {
        final daily = asList(u['daily']);
        final total = daily.fold<double>(0, (a, r) => a + (asNum(r['cost_usd']) ?? 0));
        return Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
          Wrap(spacing: 12, runSpacing: 12, children: [
            SizedBox(width: 220, child: KpiTile(label: 'Chi phí 30 ngày', value: '\$${total.toStringAsFixed(2)}', note: 'ngân sách tháng \$${asMap(u['limits'])['monthly_budget_usd']}')),
            SizedBox(width: 220, child: KpiTile(label: 'Câu hỏi 30 ngày', value: '${daily.fold<int>(0, (a, r) => a + (asInt(r['questions']) ?? 0))}', note: 'hạn mức ${asMap(u['limits'])['daily_questions']}/người/ngày')),
            SizedBox(width: 220, child: KpiTile(label: 'Mô hình', value: u['model'].toString())),
          ]),
          const SizedBox(height: 16),
          Row(crossAxisAlignment: CrossAxisAlignment.start, children: [
            Expanded(child: AppCard(child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [Text('Theo ngày', style: Theme.of(context).textTheme.titleMedium), DataTable(columns: const [DataColumn(label: Text('Ngày')), DataColumn(label: Text('Câu hỏi')), DataColumn(label: Text('Token vào/ra')), DataColumn(label: Text('Chi phí'))], rows: [for (final r in daily.reversed) DataRow(cells: [DataCell(Text(Fmt.date(Fmt.parseDate(r['date']), year: true))), DataCell(Text('${r['questions']}')), DataCell(Text('${Fmt.volume(asNum(r['input_tokens']))} / ${Fmt.volume(asNum(r['output_tokens']))}')), DataCell(Text('\$${asNum(r['cost_usd'])?.toStringAsFixed(3)}'))])])]))),
            const SizedBox(width: 16),
            Expanded(child: AppCard(child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [Text('Theo người dùng', style: Theme.of(context).textTheme.titleMedium), for (final r in asList(u['by_user'])) ListTile(dense: true, contentPadding: EdgeInsets.zero, title: Text(r['email'].toString()), trailing: Text('${r['questions']} câu · \$${asNum(r['cost_usd'])?.toStringAsFixed(2)}', style: TextStyle(color: c.muted)))]))),
          ]),
          const SizedBox(height: 12),
          Text('Đặt ngân sách và hạn mức trong Cấu hình → ai.limits.', style: TextStyle(color: c.faint, fontSize: 12)),
        ]);
      },
    );
  }
}
