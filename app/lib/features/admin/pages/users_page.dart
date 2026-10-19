import 'package:flutter/material.dart';
import 'package:flutter/services.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../../../core/api.dart';
import '../../../core/format.dart';
import '../../../core/providers.dart';
import '../../../core/responsive.dart';
import '../../../core/theme.dart';
import '../../../shared/widgets/common.dart';
import '../../../shared/widgets/score.dart';
import '../admin_common.dart';

/// A02 – Người dùng: tabs by status, multi-select bulk activation, row actions, activation / detail drawer, invite codes.
class UsersPage extends ConsumerStatefulWidget {
  final Map<String, String> query;
  const UsersPage({super.key, this.query = const {}});
  @override
  ConsumerState<UsersPage> createState() => _UsersPageState();
}

class _UsersPageState extends ConsumerState<UsersPage> {
  String status = 'PENDING';
  String q = '';
  Map<String, dynamic>? drawer;
  final selected = <String>{};
  late final searchCtl = TextEditingController(text: widget.query['q'] ?? '');

  @override
  void initState() {
    super.initState();
    q = widget.query['q'] ?? '';
    if (q.isNotEmpty) status = 'ALL';
    if (widget.query['status'] != null) status = widget.query['status']!.toUpperCase();
  }

  String get path => '/admin/users?${status == 'ALL' ? '' : 'status=$status&'}q=$q&size=100';

  void _refresh() {
    ref.invalidate(getProvider(path));
    ref.invalidate(getProvider('/admin/status'));
  }

  @override
  Widget build(BuildContext context) {
    final c = context.vn;
    final data = ref.watch(getMapProvider(path));
    final counts = asMap(data.value?['counts']);
    final total = asInt(counts['ALL']);
    final tabs = [('PENDING', 'Chờ duyệt'), ('ACTIVE', 'Đang hoạt động'), ('LOCKED', 'Bị khóa'), ('EXPIRED', 'Hết hạn'), ('REJECTED', 'Từ chối'), ('ALL', 'Tất cả'), ('INVITES', 'Mã mời')];
    return Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
      AdminHeader('Người dùng', subtitle: '${total != null ? '$total tài khoản. ' : ''}Chỉ tài khoản đang hoạt động mới xem được dữ liệu phân tích.', actions: [
        OutlinedButton.icon(onPressed: () => _createInvite(context), icon: const Icon(Icons.vpn_key_outlined, size: 18), label: const Text('Tạo mã mời')),
        FilledButton.icon(onPressed: () => _createUser(context), icon: const Icon(Icons.person_add_alt_1, size: 18), label: const Text('Thêm người dùng')),
      ]),
      Row(children: [
        Expanded(
          child: SingleChildScrollView(
            scrollDirection: Axis.horizontal,
            child: Row(children: [
              for (final t in tabs)
                InkWell(
                  onTap: () => setState(() {
                    status = t.$1;
                    selected.clear();
                    drawer = null;
                  }),
                  child: Container(
                    padding: const EdgeInsets.symmetric(horizontal: 14, vertical: 10),
                    decoration: BoxDecoration(border: Border(bottom: BorderSide(color: status == t.$1 ? c.accent : Colors.transparent, width: 2))),
                    child: Text('${t.$2}${counts[t.$1] != null ? ' (${counts[t.$1]})' : ''}', style: TextStyle(fontWeight: status == t.$1 ? FontWeight.w700 : FontWeight.w500, color: status == t.$1 ? c.accent : c.muted, fontSize: 14)),
                  ),
                ),
            ]),
          ),
        ),
        if (status != 'INVITES') SizedBox(width: 240, child: TextField(controller: searchCtl, decoration: InputDecoration(prefixIcon: const Icon(Icons.search, size: 18), hintText: 'Tìm email, tên', isDense: true, suffixIcon: q.isNotEmpty ? IconButton(icon: const Icon(Icons.clear, size: 16), onPressed: () => setState(() {
                q = '';
                searchCtl.clear();
              })) : null), onSubmitted: (v) => setState(() => q = v.trim()))),
      ]),
      Divider(height: 1, color: c.line),
      const SizedBox(height: 12),
      if (status == 'INVITES')
        _Invites(onCreate: () => _createInvite(context))
      else
        data.when(
          loading: () => const SkeletonCard(),
          error: (e, _) => ErrorBox(e, onRetry: _refresh),
          data: (d) {
            final items = asList(d['items']);
            final pendingIds = items.where((u) => u['status'] == 'PENDING').map((u) => u['id'].toString()).toList();
            final table = AppCard(
              padding: EdgeInsets.zero,
              child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
                if (selected.isNotEmpty)
                  Container(
                    padding: const EdgeInsets.symmetric(horizontal: 16, vertical: 8),
                    decoration: BoxDecoration(color: c.accent.withValues(alpha: 0.08), borderRadius: const BorderRadius.vertical(top: Radius.circular(14))),
                    child: Row(children: [
                      Text('Đã chọn ${selected.length}', style: const TextStyle(fontWeight: FontWeight.w600, fontSize: 13)),
                      const Spacer(),
                      TextButton(onPressed: () => setState(selected.clear), child: const Text('Bỏ chọn')),
                      FilledButton(onPressed: () => _bulkActivate(context), child: Text('Kích hoạt ${selected.length} tài khoản')),
                    ]),
                  ),
                SingleChildScrollView(
                  scrollDirection: Axis.horizontal,
                  child: ConstrainedBox(
                    constraints: BoxConstraints(minWidth: context.isDesktop ? 760 : 0),
                    child: DataTable(
                      showCheckboxColumn: pendingIds.isNotEmpty,
                      headingTextStyle: TextStyle(fontSize: 12.5, color: c.muted, fontWeight: FontWeight.w600),
                      columns: const [DataColumn(label: Text('Người dùng')), DataColumn(label: Text('Trạng thái')), DataColumn(label: Text('Đăng ký')), DataColumn(label: Text('Nguồn')), DataColumn(label: Text('Đăng nhập gần nhất')), DataColumn(label: Text('Thiết bị')), DataColumn(label: Text('Thao tác'))],
                      rows: [
                        for (final u in items)
                          DataRow(
                            selected: selected.contains(u['id'].toString()) || drawer?['id'] == u['id'],
                            onSelectChanged: u['status'] == 'PENDING' ? (v) => setState(() => v == true ? selected.add(u['id'].toString()) : selected.remove(u['id'].toString())) : null,
                            cells: [
                              DataCell(InkWell(onTap: () => setState(() => drawer = u), child: Column(mainAxisAlignment: MainAxisAlignment.center, crossAxisAlignment: CrossAxisAlignment.start, children: [Row(children: [Text(u['full_name'].toString(), style: const TextStyle(fontWeight: FontWeight.w600)), if (u['role'] == 'ADMIN') ...[const SizedBox(width: 6), Pill('Admin', color: c.accent, fontSize: 10)]]), Text(u['email'].toString(), style: TextStyle(fontSize: 11.5, color: c.muted))]))),
                              DataCell(Row(children: [StatusDot({'ACTIVE': c.up, 'PENDING': c.ref, 'LOCKED': c.down, 'EXPIRED': c.faint, 'REJECTED': c.down}[u['status']] ?? c.faint, size: 8), const SizedBox(width: 6), Text(userStatusVi[u['status']] ?? u['status'].toString(), style: TextStyle(color: {'ACTIVE': c.up, 'PENDING': c.ref, 'LOCKED': c.down}[u['status']] ?? c.muted, fontWeight: FontWeight.w600, fontSize: 12.5))])),
                              DataCell(cell(Fmt.dateTime(Fmt.parseDate(u['created_at'])))),
                              DataCell(cell(u['invited_by_code'] != null ? 'Mã mời ${u['invited_by_code']}' : 'Tự đăng ký')),
                              DataCell(cell(u['last_login_at'] != null ? Fmt.dateTime(Fmt.parseDate(u['last_login_at'])) : '—')),
                              DataCell(cell(u['status'] == 'PENDING' ? '—' : '${u['devices']} / ${u['max_devices'] ?? 3}')),
                              DataCell(_rowActions(context, u)),
                            ],
                          ),
                      ],
                    ),
                  ),
                ),
                if (items.isEmpty) Padding(padding: const EdgeInsets.all(24), child: Text('Không có tài khoản nào ở mục này.', style: TextStyle(color: c.muted))),
              ]),
            );
            final dr = drawer == null ? null : _UserDrawer(key: ValueKey(drawer!['id']), user: drawer!, onClose: () => setState(() => drawer = null), onChanged: _refresh);
            if (!context.isDesktop) {
              return Column(children: [if (dr != null) ...[dr, const SizedBox(height: 12)], table]);
            }
            return Row(crossAxisAlignment: CrossAxisAlignment.start, children: [Expanded(child: table), if (dr != null) ...[const SizedBox(width: 16), SizedBox(width: 400, child: dr)]]);
          },
        ),
    ]);
  }

  Widget _rowActions(BuildContext context, Map<String, dynamic> u) {
    final c = context.vn;
    final id = u['id'].toString();
    ButtonStyle small([Color? fg]) => OutlinedButton.styleFrom(visualDensity: VisualDensity.compact, padding: const EdgeInsets.symmetric(horizontal: 10), foregroundColor: fg, textStyle: const TextStyle(fontSize: 12.5));
    switch (u['status']) {
      case 'PENDING':
        return Row(mainAxisSize: MainAxisSize.min, children: [
          OutlinedButton(style: small(), onPressed: () => _quick(context, '/admin/users/$id/reject', 'Đã từ chối', confirm: ('Từ chối ${u['full_name']}?', 'Người dùng nhận email thông báo yêu cầu chưa được chấp nhận.')), child: const Text('Từ chối')),
          const SizedBox(width: 6),
          FilledButton(style: FilledButton.styleFrom(visualDensity: VisualDensity.compact, padding: const EdgeInsets.symmetric(horizontal: 10), textStyle: const TextStyle(fontSize: 12.5)), onPressed: () => setState(() => drawer = u), child: const Text('Kích hoạt')),
        ]);
      case 'ACTIVE':
        return OutlinedButton(style: small(c.down), onPressed: () => _quick(context, '/admin/users/$id/lock', 'Đã khóa', confirm: ('Khóa tài khoản ${u['full_name']}?', 'Người dùng bị đăng xuất khỏi mọi thiết bị ngay lập tức.')), child: const Text('Khóa'));
      case 'LOCKED':
      case 'REJECTED':
        return OutlinedButton(style: small(), onPressed: () => _quick(context, '/admin/users/$id/unlock', 'Đã mở khóa'), child: const Text('Mở khóa'));
      case 'EXPIRED':
        return OutlinedButton(style: small(), onPressed: () => _extend(context, u), child: const Text('Gia hạn'));
      default:
        return TextButton(onPressed: () => setState(() => drawer = u), child: const Text('Chi tiết'));
    }
  }

  Future<void> _quick(BuildContext context, String p, String ok, {(String, String)? confirm}) async {
    if (confirm != null && !await confirmDialog(context, title: confirm.$1, message: confirm.$2, confirmLabel: 'Đồng ý', danger: true)) return;
    try {
      await ref.read(apiProvider).post(p);
      _refresh();
      if (context.mounted) showToast(context, ok);
    } on ApiException catch (e) {
      if (context.mounted) showToast(context, e.message, error: true);
    }
  }

  Future<void> _extend(BuildContext context, Map<String, dynamic> u) async {
    final m = await showDialog<int>(context: context, builder: (ctx) => SimpleDialog(title: Text('Gia hạn ${u['full_name']}'), children: [for (final n in [3, 6, 12]) SimpleDialogOption(onPressed: () => Navigator.pop(ctx, n), child: Text('Thêm $n tháng'))]));
    if (m == null) return;
    final base = Fmt.parseDate(u['expires_at']) ?? DateTime.now();
    try {
      await ref.read(apiProvider).patch('/admin/users/${u['id']}', data: {'expires_at': (base.isAfter(DateTime.now()) ? base : DateTime.now()).add(Duration(days: 30 * m)).toUtc().toIso8601String()});
      _refresh();
      if (context.mounted) showToast(context, 'Đã gia hạn $m tháng');
    } on ApiException catch (e) {
      if (context.mounted) showToast(context, e.message, error: true);
    }
  }

  Future<void> _bulkActivate(BuildContext context) async {
    int? months = 12;
    int devices = 3;
    final ok = await showDialog<bool>(context: context, builder: (ctx) => StatefulBuilder(builder: (ctx, set) => AlertDialog(
      title: Text('Kích hoạt ${selected.length} tài khoản'),
      content: SizedBox(width: 360, child: Column(mainAxisSize: MainAxisSize.min, children: [
        DropdownButtonFormField<int?>(initialValue: months, decoration: const InputDecoration(labelText: 'Thời hạn sử dụng'), items: const [DropdownMenuItem(value: 3, child: Text('3 tháng')), DropdownMenuItem(value: 6, child: Text('6 tháng')), DropdownMenuItem(value: 12, child: Text('1 năm')), DropdownMenuItem(value: null, child: Text('Không giới hạn'))], onChanged: (v) => set(() => months = v)),
        const SizedBox(height: 8),
        DropdownButtonFormField<int>(initialValue: devices, decoration: const InputDecoration(labelText: 'Số thiết bị tối đa'), items: [for (final n in [1, 2, 3, 5]) DropdownMenuItem(value: n, child: Text('$n'))], onChanged: (v) => set(() => devices = v ?? 3)),
      ])),
      actions: [TextButton(onPressed: () => Navigator.pop(ctx, false), child: const Text('Hủy')), FilledButton(onPressed: () => Navigator.pop(ctx, true), child: const Text('Kích hoạt'))],
    )));
    if (ok != true) return;
    try {
      final r = asMap(await ref.read(apiProvider).post('/admin/users/bulk-activate', data: {'ids': selected.toList(), 'valid_months': months, 'max_devices': devices}));
      selected.clear();
      _refresh();
      if (context.mounted) showToast(context, r['message'].toString());
    } on ApiException catch (e) {
      if (context.mounted) showToast(context, e.message, error: true);
    }
  }

  Future<void> _createUser(BuildContext context) async {
    final email = TextEditingController(), name = TextEditingController(), phone = TextEditingController();
    String role = 'MEMBER';
    int? months = 12;
    final ok = await showDialog<bool>(context: context, builder: (ctx) => StatefulBuilder(builder: (ctx, set) => AlertDialog(
      title: const Text('Thêm người dùng'),
      content: SizedBox(width: 380, child: Column(mainAxisSize: MainAxisSize.min, children: [
        TextField(controller: name, decoration: const InputDecoration(labelText: 'Họ tên')), const SizedBox(height: 8),
        TextField(controller: email, decoration: const InputDecoration(labelText: 'Email'), keyboardType: TextInputType.emailAddress), const SizedBox(height: 8),
        TextField(controller: phone, decoration: const InputDecoration(labelText: 'Số điện thoại (tùy chọn)')), const SizedBox(height: 8),
        Row(children: [
          Expanded(child: DropdownButtonFormField<String>(initialValue: role, decoration: const InputDecoration(labelText: 'Vai trò'), items: const [DropdownMenuItem(value: 'MEMBER', child: Text('Thành viên')), DropdownMenuItem(value: 'ADMIN', child: Text('Admin'))], onChanged: (v) => set(() => role = v ?? 'MEMBER'))),
          const SizedBox(width: 8),
          Expanded(child: DropdownButtonFormField<int?>(initialValue: months, decoration: const InputDecoration(labelText: 'Thời hạn'), items: const [DropdownMenuItem(value: 3, child: Text('3 tháng')), DropdownMenuItem(value: 6, child: Text('6 tháng')), DropdownMenuItem(value: 12, child: Text('1 năm')), DropdownMenuItem(value: null, child: Text('Không giới hạn'))], onChanged: (v) => set(() => months = v))),
        ]),
        const SizedBox(height: 8),
        Text('Tài khoản được kích hoạt ngay. Mật khẩu tạm hiện một lần và gửi qua email.', style: TextStyle(fontSize: 12, color: context.vn.muted)),
      ])),
      actions: [TextButton(onPressed: () => Navigator.pop(ctx, false), child: const Text('Hủy')), FilledButton(onPressed: () => Navigator.pop(ctx, true), child: const Text('Tạo tài khoản'))],
    )));
    if (ok != true) return;
    try {
      final r = asMap(await ref.read(apiProvider).post('/admin/users', data: {'email': email.text.trim(), 'full_name': name.text.trim(), 'phone': phone.text.trim().isEmpty ? null : phone.text.trim(), 'role': role, 'valid_months': months}));
      _refresh();
      if (!context.mounted) return;
      await showDialog<void>(context: context, builder: (ctx) => AlertDialog(title: const Text('Đã tạo tài khoản'), content: Column(mainAxisSize: MainAxisSize.min, crossAxisAlignment: CrossAxisAlignment.start, children: [Text(r['email'].toString()), const SizedBox(height: 8), const Text('Mật khẩu tạm (chỉ hiện một lần):'), SelectableText(r['temp_password'].toString(), style: const TextStyle(fontFamily: 'monospace', fontSize: 16, fontWeight: FontWeight.w700))]),
          actions: [TextButton(onPressed: () => Clipboard.setData(ClipboardData(text: r['temp_password'].toString())), child: const Text('Sao chép')), FilledButton(onPressed: () => Navigator.pop(ctx), child: const Text('Đóng'))]));
    } on ApiException catch (e) {
      if (context.mounted) showToast(context, e.message, error: true);
    }
  }

  Future<void> _createInvite(BuildContext context) async {
    final email = TextEditingController(), note = TextEditingController();
    bool auto = false;
    int? months = 12;
    final ok = await showDialog<bool>(context: context, builder: (ctx) => StatefulBuilder(builder: (ctx, set) => AlertDialog(title: const Text('Tạo mã mời'), content: SizedBox(width: 360, child: Column(mainAxisSize: MainAxisSize.min, children: [
      TextField(controller: email, decoration: const InputDecoration(labelText: 'Email gắn kèm (tùy chọn)')), const SizedBox(height: 8),
      TextField(controller: note, decoration: const InputDecoration(labelText: 'Ghi chú')), const SizedBox(height: 8),
      DropdownButtonFormField<int?>(initialValue: months, decoration: const InputDecoration(labelText: 'Thời hạn tài khoản'), items: const [DropdownMenuItem(value: 3, child: Text('3 tháng')), DropdownMenuItem(value: 6, child: Text('6 tháng')), DropdownMenuItem(value: 12, child: Text('1 năm')), DropdownMenuItem(value: null, child: Text('Không giới hạn'))], onChanged: (v) => set(() => months = v)),
      SwitchListTile(contentPadding: EdgeInsets.zero, value: auto, onChanged: (v) => set(() => auto = v), title: const Text('Tự kích hoạt, không cần duyệt')),
    ])), actions: [TextButton(onPressed: () => Navigator.pop(ctx, false), child: const Text('Hủy')), FilledButton(onPressed: () => Navigator.pop(ctx, true), child: const Text('Tạo'))])));
    if (ok != true) return;
    try {
      final r = asMap(await ref.read(apiProvider).post('/admin/invitations', data: {'email': email.text.trim().isEmpty ? null : email.text.trim(), 'note': note.text, 'auto_activate': auto, 'valid_months': months}));
      ref.invalidate(getProvider('/admin/invitations'));
      if (context.mounted) showToast(context, 'Đã tạo mã ${r['code']}', actionLabel: 'Sao chép liên kết', onAction: () => Clipboard.setData(ClipboardData(text: r['link'].toString())));
    } on ApiException catch (e) {
      if (context.mounted) showToast(context, e.message, error: true);
    }
  }
}

class _UserDrawer extends ConsumerStatefulWidget {
  final Map<String, dynamic> user;
  final VoidCallback onClose, onChanged;
  const _UserDrawer({super.key, required this.user, required this.onClose, required this.onChanged});
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
    devices = asInt(widget.user['max_devices']) ?? 3;
    _load();
  }

  Future<void> _load() async {
    try {
      detail = asMap(await ref.read(apiProvider).get('/admin/users/${widget.user['id']}'));
    } on ApiException catch (_) {}
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
    final reg = asMap(u['registered_device']);
    Widget kv(String k, String v) => Padding(padding: const EdgeInsets.symmetric(vertical: 3), child: Row(crossAxisAlignment: CrossAxisAlignment.start, children: [SizedBox(width: 130, child: Text(k, style: TextStyle(color: c.muted, fontSize: 12.5))), Expanded(child: Text(v, style: const TextStyle(fontSize: 13, fontWeight: FontWeight.w600)))]));
    return AppCard(
      child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
        Row(children: [Expanded(child: Text(pending ? 'Kích hoạt tài khoản' : 'Chi tiết tài khoản', style: Theme.of(context).textTheme.titleMedium)), IconButton(onPressed: widget.onClose, icon: const Icon(Icons.close, size: 20))]),
        Row(children: [
          CircleAvatar(radius: 20, backgroundColor: c.accent.withValues(alpha: 0.12), child: Text(u['full_name'].toString().characters.first.toUpperCase(), style: TextStyle(color: c.accent, fontWeight: FontWeight.w700))),
          const SizedBox(width: 10),
          Expanded(child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [Text(u['full_name'].toString(), style: const TextStyle(fontWeight: FontWeight.w700, fontSize: 15)), Text('${u['email']}${u['phone'] != null ? ', ${u['phone']}' : ''}', style: TextStyle(color: c.muted, fontSize: 12.5))])),
        ]),
        const SizedBox(height: 10),
        kv('Đăng ký lúc', Fmt.dateTime(Fmt.parseDate(u['created_at']))),
        kv('Mã mời', u['invited_by_code']?.toString() ?? 'Tự đăng ký'),
        if (reg.isNotEmpty) kv('Thiết bị đăng ký', '${reg['name'] ?? reg['platform']}'),
        if (pending) ...[
          const SizedBox(height: 8),
          Text('Vai trò', style: TextStyle(color: c.muted, fontSize: 12.5)),
          const SizedBox(height: 4),
          Segmented<String>(options: const [('MEMBER', 'Thành viên'), ('ADMIN', 'Admin')], value: role, onChanged: (v) => setState(() => role = v)),
          const SizedBox(height: 10),
          Text('Thời hạn sử dụng', style: TextStyle(color: c.muted, fontSize: 12.5)),
          const SizedBox(height: 4),
          Segmented<int?>(options: const [(3, '3 tháng'), (6, '6 tháng'), (12, '1 năm'), (null, 'Không giới hạn')], value: months, onChanged: (v) => setState(() => months = v)),
          const SizedBox(height: 10),
          SizedBox(width: 160, child: DropdownButtonFormField<int>(initialValue: devices, decoration: const InputDecoration(labelText: 'Số thiết bị tối đa', isDense: true), items: [for (final n in [1, 2, 3, 5]) DropdownMenuItem(value: n, child: Text('$n'))], onChanged: (v) => setState(() => devices = v ?? 3))),
          const SizedBox(height: 10),
          TextField(controller: msg, minLines: 2, maxLines: 3, decoration: InputDecoration(labelText: 'Lời nhắn kèm email kích hoạt (không bắt buộc)', hintText: 'Chào ${u['full_name'].toString().split(' ').last}, tài khoản Vinatrade của bạn đã sẵn sàng…', isDense: true)),
          const SizedBox(height: 12),
          Row(children: [
            Expanded(child: OutlinedButton(style: OutlinedButton.styleFrom(foregroundColor: c.down), onPressed: () => _call('/admin/users/${u['id']}/reject', okMsg: 'Đã từ chối'), child: const Text('Từ chối'))),
            const SizedBox(width: 8),
            Expanded(flex: 2, child: FilledButton(onPressed: () => _call('/admin/users/${u['id']}/activate', data: {'valid_months': months, 'max_devices': devices, 'role': role, 'message': msg.text.trim().isEmpty ? null : msg.text.trim()}, okMsg: 'Đã kích hoạt ${u['email']}'), child: const Text('Kích hoạt tài khoản'))),
          ]),
          const SizedBox(height: 8),
          Text('Thao tác được ghi vào nhật ký kiểm toán. Người dùng nhận email và thông báo đẩy ngay sau khi kích hoạt.', style: TextStyle(fontSize: 11.5, color: c.faint)),
        ] else ...[
          kv('Trạng thái', userStatusVi[u['status']] ?? u['status'].toString()),
          kv('Vai trò', u['role'] == 'ADMIN' ? 'Admin' : 'Thành viên'),
          kv('Hết hạn', u['expires_at'] != null ? Fmt.date(Fmt.parseDate(u['expires_at']), year: true) : 'Không giới hạn'),
          kv('Quy tắc cảnh báo', '${u['alert_rules'] ?? '—'}'),
          kv('Mức chi tiết', {'SIMPLE': 'Đơn giản', 'STANDARD': 'Vừa đủ', 'FULL': 'Đầy đủ'}[u['ui_detail']] ?? '—'),
          const Divider(),
          Text('Thiết bị (${asList(u['devices'] is List ? u['devices'] : []).length} / ${u['max_devices'] ?? 3})', style: const TextStyle(fontWeight: FontWeight.w700, fontSize: 13)),
          for (final d in asList(u['devices'] is List ? u['devices'] : []))
            ListTile(dense: true, contentPadding: EdgeInsets.zero, title: Text(d['name']?.toString() ?? d['platform'].toString(), maxLines: 1, overflow: TextOverflow.ellipsis, style: const TextStyle(fontSize: 13)), subtitle: Text('${d['platform']} · ${Fmt.relative(Fmt.parseDate(d['last_seen_at']))}', style: TextStyle(fontSize: 11.5, color: c.faint)),
                trailing: TextButton(onPressed: () => _call('/admin/users/${u['id']}/devices/${d['id']}', method: 'delete', okMsg: 'Đã đăng xuất thiết bị'), child: const Text('Đăng xuất', style: TextStyle(fontSize: 12)))),
          if (asList(u['devices'] is List ? u['devices'] : []).isEmpty) Text('Chưa đăng nhập thiết bị nào.', style: TextStyle(color: c.faint, fontSize: 12)),
          const SizedBox(height: 6),
          const Text('Lịch sử đăng nhập', style: TextStyle(fontWeight: FontWeight.w700, fontSize: 13)),
          for (final l in asList(u['logins']).take(5)) Text('${Fmt.dateTime(Fmt.parseDate(l['created_at']))} · ${auditActionVi[l['action']] ?? l['action']} · ${l['ip'] ?? ''}', style: TextStyle(fontSize: 12, color: c.muted)),
          const SizedBox(height: 6),
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
              FilledButton(onPressed: () => _call('/admin/users/${u['id']}/unlock', okMsg: 'Đã mở khóa'), child: const Text('Mở khóa')),
            OutlinedButton(onPressed: () async {
              try {
                final r = asMap(await ref.read(apiProvider).patch('/admin/users/${u['id']}', data: {'reset_password': true}));
                if (context.mounted) showDialog(context: context, builder: (ctx) => AlertDialog(title: const Text('Mật khẩu tạm'), content: SelectableText(r['temp_password']?.toString() ?? '', style: const TextStyle(fontFamily: 'monospace', fontSize: 16)), actions: [TextButton(onPressed: () => Navigator.pop(ctx), child: const Text('Đóng'))]));
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
  final VoidCallback onCreate;
  const _Invites({required this.onCreate});
  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final c = context.vn;
    final invites = ref.watch(getListProvider('/admin/invitations'));
    return AppCard(
      padding: EdgeInsets.zero,
      child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
        invites.when(
          loading: () => const Padding(padding: EdgeInsets.all(16), child: Skeleton()),
          error: (e, _) => ErrorBox(e),
          data: (rows) => rows.isEmpty
              ? Padding(padding: const EdgeInsets.all(24), child: Text('Chưa có mã mời. Bấm "Tạo mã mời" ở góc trên.', style: TextStyle(color: c.muted)))
              : SingleChildScrollView(
                  scrollDirection: Axis.horizontal,
                  child: DataTable(
                    headingTextStyle: TextStyle(fontSize: 12.5, color: c.muted, fontWeight: FontWeight.w600),
                    columns: const [DataColumn(label: Text('Mã')), DataColumn(label: Text('Email')), DataColumn(label: Text('Ghi chú')), DataColumn(label: Text('Trạng thái')), DataColumn(label: Text('Kích hoạt')), DataColumn(label: Text('Hết hạn')), DataColumn(label: Text(''))],
                    rows: [
                      for (final i in rows)
                        DataRow(cells: [
                          DataCell(SelectableText(i['code'].toString(), style: const TextStyle(fontWeight: FontWeight.w700, fontFamily: 'monospace'))),
                          DataCell(cell(i['email']?.toString() ?? '—')),
                          DataCell(cell(i['note']?.toString() ?? '')),
                          DataCell(Text(i['status'].toString(), style: TextStyle(color: i['status'] == 'Còn hiệu lực' ? c.up : c.muted, fontWeight: FontWeight.w600, fontSize: 12.5))),
                          DataCell(cell(i['auto_activate'] == true ? 'Tự kích hoạt' : 'Chờ duyệt')),
                          DataCell(cell(Fmt.date(Fmt.parseDate(i['expires_at']), year: true))),
                          DataCell(Row(children: [
                            IconButton(tooltip: 'Sao chép liên kết mời', icon: const Icon(Icons.link, size: 18), onPressed: () {
                              Clipboard.setData(ClipboardData(text: i['link'].toString()));
                              showToast(context, 'Đã sao chép liên kết mời');
                            }),
                            IconButton(tooltip: 'Xóa mã', icon: const Icon(Icons.delete_outline, size: 18), onPressed: () async {
                              await ref.read(apiProvider).delete('/admin/invitations/${i['code']}');
                              ref.invalidate(getProvider('/admin/invitations'));
                            }),
                          ])),
                        ]),
                    ],
                  ),
                ),
        ),
        Padding(padding: const EdgeInsets.all(12), child: Text('Liên kết mời dạng {web}/register?invite=MÃ. Mã hết hạn sau 30 ngày nếu chưa dùng.', style: TextStyle(color: c.faint, fontSize: 11.5))),
      ]),
    );
  }
}
