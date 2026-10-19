import 'dart:convert';

import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:go_router/go_router.dart';
import 'package:shared_preferences/shared_preferences.dart';

import '../../core/api.dart';
import '../../core/format.dart';
import '../../core/providers.dart';
import '../../core/theme.dart';
import '../../shared/widgets/common.dart';
import '../../shared/widgets/score.dart';

/// Shared bits of the admin console (UI spec part IV): labels, status pills, page header, config forms, job helpers.

const adminSections = [
  ('overview', 'Tổng quan hệ thống', Icons.monitor_heart_outlined),
  ('users', 'Người dùng', Icons.people_outline),
  ('strategies', 'Chiến lược & tín hiệu', Icons.trending_up),
  ('performance', 'Hiệu quả tín hiệu', Icons.bar_chart_outlined),
  ('config', 'Cấu hình chấm điểm', Icons.settings_outlined),
  ('risk', 'Giới hạn rủi ro & ký quỹ', Icons.shield_outlined),
  ('jobs', 'Dữ liệu & tác vụ', Icons.storage_outlined),
  ('broadcasts', 'Thông báo chung', Icons.campaign_outlined),
  ('audit', 'Nhật ký kiểm toán', Icons.receipt_long_outlined),
  ('ai', 'Chi phí AI', Icons.auto_awesome_outlined),
];

String sectionTitle(String section) => adminSections.firstWhere((s) => s.$1 == section, orElse: () => adminSections.first).$2;

const jobStatusVi = {'DONE': 'Thành công', 'WARN': 'Có cảnh báo', 'FAILED': 'Lỗi', 'RUNNING': 'Đang chạy', 'PENDING': 'Chưa chạy', 'NEVER': 'Chưa chạy'};
const signalTypeVi = {'BUY': 'Mua', 'SELL': 'Giảm tỷ trọng', 'TAKE_PROFIT': 'Chốt lời', 'STOP_LOSS': 'Cắt lỗ', 'WATCH': 'Theo dõi'};
const userStatusVi = {'ACTIVE': 'Đang hoạt động', 'PENDING': 'Chờ duyệt', 'LOCKED': 'Bị khóa', 'EXPIRED': 'Hết hạn', 'REJECTED': 'Từ chối'};
const regime3Vi = {'UP': 'Thị trường tăng', 'PRESSURE': 'Chịu áp lực', 'DOWN': 'Thị trường giảm'};
const auditActionVi = {
  'LOGIN': 'Đăng nhập', 'REGISTER': 'Đăng ký', 'USER_ACTIVE': 'Kích hoạt tài khoản', 'USER_LOCKED': 'Khóa tài khoản', 'USER_REJECTED': 'Từ chối tài khoản', 'USER_PATCH': 'Sửa tài khoản',
  'USER_DELETE': 'Xóa tài khoản', 'USER_CREATE': 'Tạo tài khoản', 'DEVICE_KICK': 'Đăng xuất thiết bị', 'INVITE_CREATE': 'Tạo mã mời', 'INVITE_DELETE': 'Xóa mã mời',
  'CONFIG_SET': 'Sửa cấu hình', 'CONFIG_RESET': 'Khôi phục cấu hình', 'STRATEGY_SET': 'Bật/tắt chiến lược', 'STRATEGY_DRAFT': 'Lưu bản nháp chiến lược', 'STRATEGY_DRAFT_DROP': 'Bỏ bản nháp',
  'STRATEGY_VERSION': 'Bật phiên bản chiến lược', 'JOB_RUN': 'Chạy tác vụ', 'JOB_STOP': 'Dừng tác vụ', 'SOURCE_SET': 'Sửa nguồn dữ liệu', 'PRICE_IMPORT': 'Nhập file giá',
  'BROADCAST': 'Gửi thông báo chung', 'MARGIN_LISTS': 'Sửa danh sách ký quỹ', 'STOCK_FLAGS': 'Đổi trạng thái mã', 'ADMIN_UNLOCK': 'Mở lại phiên quản trị', 'PASSWORD_CHANGE': 'Đổi mật khẩu',
  'TOTP_ENABLE': 'Bật 2 lớp', 'TOTP_DISABLE': 'Tắt 2 lớp', 'LOGOUT': 'Đăng xuất',
};

Color jobStatusColor(VNColors c, String? s) => switch (s) { 'DONE' => c.up, 'WARN' => c.ref, 'FAILED' => c.down, 'RUNNING' => c.accent, _ => c.faint };
Color winRateColor(VNColors c, num? wr) => wr == null ? c.faint : (wr >= 60 ? c.up : (wr >= 50 ? c.ref : c.down));

/// Admin frame state shared across pages: gate (2FA / idle lock) raised by the API client.
class AdminGate extends Notifier<String?> {
  @override
  String? build() => null;
  void set(String? code) => state = code;
}

final adminGateProvider = NotifierProvider<AdminGate, String?>(AdminGate.new);

/// Admin console theme (UI 15: light by default, can switch to dark). Stored per device, independent of the app theme.
class AdminTheme extends Notifier<Brightness> {
  static const _key = 'admin_theme';
  @override
  Brightness build() {
    SharedPreferences.getInstance().then((p) {
      if (p.getString(_key) == 'dark') state = Brightness.dark;
    }).catchError((_) {});
    return Brightness.light;
  }

  Future<void> toggle() async {
    state = state == Brightness.dark ? Brightness.light : Brightness.dark;
    try {
      (await SharedPreferences.getInstance()).setString(_key, state == Brightness.dark ? 'dark' : 'light');
    } catch (_) {}
  }
}

final adminThemeProvider = NotifierProvider<AdminTheme, Brightness>(AdminTheme.new);

/// Page header per UI spec 15: title, one-line description, actions on the right.
class AdminHeader extends StatelessWidget {
  final String title;
  final String? subtitle;
  final List<Widget> actions;
  const AdminHeader(this.title, {super.key, this.subtitle, this.actions = const []});
  @override
  Widget build(BuildContext context) {
    final c = context.vn;
    return Padding(
      padding: const EdgeInsets.only(bottom: 16),
      child: Wrap(crossAxisAlignment: WrapCrossAlignment.end, alignment: WrapAlignment.spaceBetween, runSpacing: 8, children: [
        Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
          Text(title, style: Theme.of(context).textTheme.headlineSmall?.copyWith(fontWeight: FontWeight.w700)),
          if (subtitle != null) Padding(padding: const EdgeInsets.only(top: 2), child: Text(subtitle!, style: TextStyle(color: c.muted, fontSize: 13.5))),
        ]),
        Wrap(spacing: 8, runSpacing: 8, children: actions),
      ]),
    );
  }
}

class StatusPill extends StatelessWidget {
  final String status;
  final String? label;
  const StatusPill(this.status, {super.key, this.label});
  @override
  Widget build(BuildContext context) {
    final c = context.vn;
    final col = jobStatusColor(c, status);
    return Row(mainAxisSize: MainAxisSize.min, children: [StatusDot(col, size: 8), const SizedBox(width: 6), Text(label ?? jobStatusVi[status] ?? status, style: TextStyle(color: col, fontWeight: FontWeight.w600, fontSize: 12.5))]);
  }
}

/// Compact table cell text.
Text cell(String s, {bool bold = false, Color? color, double size = 13}) => Text(s, style: TextStyle(fontWeight: bold ? FontWeight.w600 : FontWeight.w400, color: color, fontSize: size), maxLines: 1, overflow: TextOverflow.ellipsis);

String fmtDuration(num? ms) {
  if (ms == null) return '—';
  final s = ms / 1000;
  if (s < 60) return '${s.toStringAsFixed(s < 10 ? 1 : 0)} giây';
  final m = (s / 60).floor();
  return m < 60 ? '$m phút ${(s % 60).round()} giây' : '${(m / 60).floor()} giờ ${m % 60} phút';
}

String fmtHm(DateTime? d) => d == null ? '—' : '${d.toLocal().hour.toString().padLeft(2, '0')}:${d.toLocal().minute.toString().padLeft(2, '0')}';

/// Runs a named job (eod, eod.step, intraday…) with the trading-hours confirmation.
Future<void> runJob(BuildContext context, WidgetRef ref, String name, {List<String> refresh = const ['/admin/overview', '/admin/jobs?limit=60']}) async {
  try {
    final r = asMap(await ref.read(apiProvider).post('/admin/jobs/$name/run'));
    if (context.mounted) showToast(context, r['message']?.toString() ?? 'Đã xếp lịch');
  } on ApiException catch (e) {
    if (e.code == 'CONFIRM_REQUIRED') {
      if (!context.mounted) return;
      if (await confirmDialog(context, title: 'Chạy trong giờ giao dịch?', message: 'Tác vụ sẽ chạy ngay khi thị trường đang mở. Dữ liệu trong ngày có thể chưa đầy đủ.', confirmLabel: 'Chạy ngay')) {
        try {
          final r = asMap(await ref.read(apiProvider).post('/admin/jobs/$name/run', query: {'confirm': 1}));
          if (context.mounted) showToast(context, r['message']?.toString() ?? 'Đã xếp lịch');
        } on ApiException catch (e2) {
          if (context.mounted) showToast(context, e2.message, error: true);
        }
      }
    } else if (context.mounted) {
      showToast(context, e.message, error: true);
    }
  }
  Future.delayed(const Duration(seconds: 3), () {
    if (!context.mounted) return;
    for (final p in refresh) {
      ref.invalidate(getProvider(p));
    }
  });
}

/// Job run log dialog (A01 "bấm bước để xem log").
Future<void> showJobRun(BuildContext context, WidgetRef ref, int id) async {
  Map<String, dynamic> r;
  try {
    r = asMap(await ref.read(apiProvider).get('/admin/jobs/runs/$id'));
  } on ApiException catch (e) {
    if (context.mounted) showToast(context, e.message, error: true);
    return;
  }
  if (!context.mounted) return;
  final c = context.vn;
  await showDialog<void>(
    context: context,
    builder: (ctx) => AlertDialog(
      title: Row(children: [Expanded(child: Text(r['name'].toString())), StatusPill(r['status'].toString())]),
      content: SizedBox(
        width: 640,
        child: SingleChildScrollView(
          child: Column(crossAxisAlignment: CrossAxisAlignment.start, mainAxisSize: MainAxisSize.min, children: [
            Text('Bắt đầu ${Fmt.dateTime(Fmt.parseDate(r['started_at']))} · ${fmtDuration(asNum(r['duration_ms']))} · ${r['triggered_by'] ?? ''}', style: TextStyle(color: c.muted, fontSize: 12.5)),
            if (r['summary'] != null) Padding(padding: const EdgeInsets.only(top: 8), child: Text(r['summary'].toString())),
            if (r['meta'] != null) Padding(padding: const EdgeInsets.only(top: 8), child: SelectableText(const JsonEncoder.withIndent('  ').convert(r['meta']), style: const TextStyle(fontFamily: 'monospace', fontSize: 11.5))),
            if (r['error'] != null) Padding(padding: const EdgeInsets.only(top: 8), child: SelectableText(r['error'].toString(), style: TextStyle(fontFamily: 'monospace', fontSize: 11.5, color: c.down))),
          ]),
        ),
      ),
      actions: [TextButton(onPressed: () => Navigator.pop(ctx), child: const Text('Đóng'))],
    ),
  );
}

/// Before/after diff of an audit row (A07 "dạng so sánh").
class DiffView extends StatelessWidget {
  final dynamic before, after;
  final bool compact;
  const DiffView({super.key, this.before, this.after, this.compact = true});
  @override
  Widget build(BuildContext context) {
    final c = context.vn;
    final b = before is Map ? (before as Map).cast<String, dynamic>() : null;
    final a = after is Map ? (after as Map).cast<String, dynamic>() : null;
    if (b == null && a == null) return Text('—', style: TextStyle(color: c.faint));
    final bb = b != null && b.length == 1 && b.containsKey('value') && b['value'] is Map ? (b['value'] as Map).cast<String, dynamic>() : b;
    final aa = a != null && a.length == 1 && a.containsKey('value') && a['value'] is Map ? (a['value'] as Map).cast<String, dynamic>() : a;
    final keys = {...?bb?.keys, ...?aa?.keys}.toList();
    final rows = <Widget>[];
    for (final k in keys) {
      final x = bb?[k], y = aa?[k];
      if (bb != null && aa != null && jsonEncode(x) == jsonEncode(y)) continue;
      rows.add(RichText(maxLines: compact ? 1 : 4, overflow: TextOverflow.ellipsis, text: TextSpan(style: TextStyle(fontSize: 11.5, color: c.muted, fontFamily: 'monospace'), children: [
        TextSpan(text: '$k: ', style: TextStyle(color: c.text, fontWeight: FontWeight.w600)),
        if (bb != null && bb.containsKey(k)) TextSpan(text: _short(x), style: TextStyle(color: c.down, decoration: TextDecoration.lineThrough)),
        if (bb != null && bb.containsKey(k) && aa != null && aa.containsKey(k)) const TextSpan(text: ' → '),
        if (aa != null && aa.containsKey(k)) TextSpan(text: _short(y), style: TextStyle(color: c.up)),
      ])));
      if (compact && rows.length >= 3) break;
    }
    if (rows.isEmpty) return Text('Không đổi', style: TextStyle(color: c.faint, fontSize: 11.5));
    return Column(crossAxisAlignment: CrossAxisAlignment.start, mainAxisSize: MainAxisSize.min, children: rows);
  }

  static String _short(dynamic v) {
    final s = v is String ? v : jsonEncode(v);
    return s.length > 60 ? '${s.substring(0, 57)}…' : s;
  }
}

/// Config history dialog (A05 "lịch sử thay đổi").
Future<void> showConfigHistory(BuildContext context, WidgetRef ref, String key, String label) async {
  List<Map<String, dynamic>> rows;
  try {
    rows = asList(await ref.read(apiProvider).get('/admin/config/$key/history'));
  } on ApiException catch (e) {
    if (context.mounted) showToast(context, e.message, error: true);
    return;
  }
  if (!context.mounted) return;
  final c = context.vn;
  await showDialog<void>(
    context: context,
    builder: (ctx) => AlertDialog(
      title: Text('Lịch sử: $label'),
      content: SizedBox(
        width: 560,
        child: rows.isEmpty
            ? Text('Chưa có thay đổi nào. Giá trị đang là mặc định.', style: TextStyle(color: c.muted))
            : SingleChildScrollView(child: Column(mainAxisSize: MainAxisSize.min, children: [
                for (final r in rows)
                  ListTile(contentPadding: EdgeInsets.zero, dense: true,
                      title: Text('${Fmt.dateTime(Fmt.parseDate(r['created_at']))} · ${r['actor_email'] ?? '—'} · ${auditActionVi[r['action']] ?? r['action']}', style: const TextStyle(fontSize: 12.5, fontWeight: FontWeight.w600)),
                      subtitle: DiffView(before: r['before'], after: r['after'], compact: false)),
              ])),
      ),
      actions: [TextButton(onPressed: () => Navigator.pop(ctx), child: const Text('Đóng'))],
    ),
  );
}

/// One config key rendered as a labelled form (A05): fields with unit, default, last editor and history.
class ConfigCard extends ConsumerStatefulWidget {
  final Map<String, dynamic> row;
  final VoidCallback onChanged;
  final bool highlight;
  const ConfigCard({super.key, required this.row, required this.onChanged, this.highlight = false});
  @override
  ConsumerState<ConfigCard> createState() => _ConfigCardState();
}

class _ConfigCardState extends ConsumerState<ConfigCard> {
  late Map<String, dynamic> draft;
  final ctls = <String, TextEditingController>{};
  late final jsonCtl = TextEditingController(text: const JsonEncoder.withIndent('  ').convert(widget.row['value']));
  bool dirty = false, saving = false;

  @override
  void initState() {
    super.initState();
    _reset();
  }

  @override
  void didUpdateWidget(covariant ConfigCard old) {
    super.didUpdateWidget(old);
    if (jsonEncode(old.row['value']) != jsonEncode(widget.row['value'])) _reset();
  }

  void _reset() {
    final v = widget.row['value'];
    draft = v is Map ? v.cast<String, dynamic>() : {'_': v};
    for (final f in asList(widget.row['fields'])) {
      final k = f['key'].toString();
      ctls[k] = TextEditingController(text: _text(draft[k], f['type']?.toString()));
    }
    if (widget.row['kind'] == 'scalar') ctls['_'] = TextEditingController(text: _text(v, widget.row['type']?.toString()));
    if (widget.row['kind'] == 'list') ctls['_'] = TextEditingController(text: (v as List? ?? []).join('\n'));
    jsonCtl.text = const JsonEncoder.withIndent('  ').convert(v);
    dirty = false;
  }

  static String _text(dynamic v, String? type) => v == null ? '' : (type == 'range' && v is List ? v.join(' ; ') : v.toString());

  dynamic _parse(String s, String? type) {
    s = s.trim();
    switch (type) {
      case 'int':
        return int.tryParse(s.replaceAll('.', '').replaceAll(',', '')) ?? num.tryParse(s)?.toInt();
      case 'text':
        return s;
      case 'range':
        final parts = s.split(RegExp(r'[;,]')).map((x) => num.tryParse(x.trim())).toList();
        return parts.length == 2 && !parts.contains(null) ? parts : null;
      default:
        return num.tryParse(s.replaceAll(',', '.'));
    }
  }

  Future<void> _save(dynamic value) async {
    setState(() => saving = true);
    try {
      await ref.read(apiProvider).put('/admin/config/${widget.row['key']}', data: {'value': value});
      widget.onChanged();
      if (mounted) showToast(context, 'Đã lưu ${widget.row['label']}. Áp dụng từ lần xử lý tới.');
    } on ApiException catch (e) {
      if (mounted) showToast(context, e.message, error: true);
    } finally {
      if (mounted) setState(() => saving = false);
    }
  }

  @override
  Widget build(BuildContext context) {
    final c = context.vn;
    final r = widget.row;
    final kind = r['kind']?.toString() ?? 'json';
    final fields = asList(r['fields']);
    final def = r['default'];
    final isDefault = jsonEncode(r['value']) == jsonEncode(def);
    Widget body;
    switch (kind) {
      case 'form':
        body = Wrap(spacing: 16, runSpacing: 12, children: [
          for (final f in fields)
            SizedBox(
              width: f['type'] == 'text' ? 200 : 230,
              child: TextField(
                controller: ctls[f['key']],
                onChanged: (_) => setState(() => dirty = true),
                keyboardType: f['type'] == 'text' ? TextInputType.text : const TextInputType.numberWithOptions(decimal: true, signed: true),
                decoration: InputDecoration(
                  labelText: f['label'].toString(), suffixText: (f['unit']?.toString() ?? '').isEmpty ? null : f['unit'].toString(), isDense: true,
                  helperText: 'Mặc định ${_text((def is Map ? def[f['key']] : null), f['type']?.toString())}${f['help'] != null ? ' · ${f['help']}' : ''}', helperMaxLines: 2,
                ),
              ),
            ),
        ]);
      case 'scalar':
        body = SizedBox(width: 280, child: TextField(controller: ctls['_'], onChanged: (_) => setState(() => dirty = true), keyboardType: TextInputType.number,
            decoration: InputDecoration(labelText: r['label'].toString(), suffixText: r['unit']?.toString(), isDense: true, helperText: 'Mặc định ${Fmt.price(asNum(def))}')));
      case 'bool':
        body = SwitchListTile(contentPadding: EdgeInsets.zero, value: r['value'] == true, title: Text(r['description'].toString(), style: const TextStyle(fontSize: 13.5)), onChanged: saving ? null : (v) => _save(v));
      case 'list':
        body = TextField(controller: ctls['_'], minLines: 2, maxLines: 8, onChanged: (_) => setState(() => dirty = true), decoration: const InputDecoration(labelText: 'Mỗi dòng một mục', isDense: true));
      case 'weights':
        body = Row(children: [Expanded(child: Text('Chỉnh bằng thanh trượt ở màn Chiến lược & tín hiệu (tổng mỗi khung phải bằng 100%).', style: TextStyle(color: c.muted, fontSize: 13))), TextButton(onPressed: () => context.go('/admin/strategies'), child: const Text('Mở'))]);
      default:
        body = TextField(controller: jsonCtl, minLines: 3, maxLines: 16, onChanged: (_) => setState(() => dirty = true), style: const TextStyle(fontFamily: 'monospace', fontSize: 12), decoration: const InputDecoration(labelText: 'JSON', isDense: true));
    }
    return AppCard(
      borderColor: widget.highlight ? c.accent : null,
      child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
        Row(crossAxisAlignment: CrossAxisAlignment.start, children: [
          Expanded(child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
            Row(children: [Flexible(child: Text(r['label'].toString(), style: const TextStyle(fontWeight: FontWeight.w700, fontSize: 14.5))), const SizedBox(width: 8), if (isDefault) Pill('Mặc định', color: c.faint, fontSize: 10)]),
            Text(r['description']?.toString() ?? '', style: TextStyle(color: c.muted, fontSize: 12.5)),
            Text(r['updated_by'] != null ? 'Sửa lần cuối: ${r['updated_by']} · ${Fmt.relative(Fmt.parseDate(r['updated_at']))}' : 'Chưa ai sửa', style: TextStyle(color: c.faint, fontSize: 11.5)),
          ])),
          TextButton.icon(onPressed: () => showConfigHistory(context, ref, r['key'].toString(), r['label'].toString()), icon: const Icon(Icons.history, size: 16), label: const Text('Lịch sử')),
          if (!isDefault)
            TextButton(onPressed: () async {
              if (await confirmDialog(context, title: 'Khôi phục mặc định?', message: '${r['label']} sẽ về giá trị mặc định và ghi vào nhật ký kiểm toán.', confirmLabel: 'Khôi phục')) {
                await ref.read(apiProvider).post('/admin/config/${r['key']}/reset');
                widget.onChanged();
              }
            }, child: const Text('Mặc định')),
        ]),
        const SizedBox(height: 10),
        body,
        if (kind != 'bool' && kind != 'weights') ...[
          const SizedBox(height: 10),
          Row(children: [
            Text(r['key'].toString(), style: TextStyle(fontFamily: 'monospace', fontSize: 11, color: c.faint)),
            const Spacer(),
            if (dirty) TextButton(onPressed: () => setState(_reset), child: const Text('Hủy')),
            FilledButton(
              onPressed: !dirty || saving ? null : () {
                dynamic value;
                if (kind == 'form') {
                  value = <String, dynamic>{};
                  for (final f in fields) {
                    final v = _parse(ctls[f['key']]!.text, f['type']?.toString());
                    if (v == null) {
                      showToast(context, 'Giá trị "${f['label']}" không hợp lệ', error: true);
                      return;
                    }
                    final mn = asNum(f['min']), mx = asNum(f['max']);
                    if (v is num && ((mn != null && v < mn) || (mx != null && v > mx))) {
                      showToast(context, '"${f['label']}" phải trong khoảng ${mn ?? '…'} – ${mx ?? '…'}', error: true);
                      return;
                    }
                    value[f['key'].toString()] = v;
                  }
                } else if (kind == 'scalar') {
                  value = _parse(ctls['_']!.text, r['type']?.toString());
                  if (value == null) {
                    showToast(context, 'Giá trị không hợp lệ', error: true);
                    return;
                  }
                } else if (kind == 'list') {
                  value = ctls['_']!.text.split('\n').map((s) => s.trim()).where((s) => s.isNotEmpty).toList();
                } else {
                  try {
                    value = jsonDecode(jsonCtl.text);
                  } on FormatException {
                    showToast(context, 'JSON không hợp lệ', error: true);
                    return;
                  }
                }
                _save(value);
              },
              child: Text(saving ? 'Đang lưu…' : 'Lưu'),
            ),
          ]),
        ],
      ]),
    );
  }
}

/// Simple heat cell used by A10 tables.
class HeatCell extends StatelessWidget {
  final num? winRate;
  final int samples;
  final String? suffix;
  const HeatCell({super.key, required this.winRate, required this.samples, this.suffix});
  @override
  Widget build(BuildContext context) {
    final c = context.vn;
    if (winRate == null) return Text('—', style: TextStyle(color: c.faint));
    final col = winRateColor(c, winRate);
    return Opacity(
      opacity: samples < 30 ? 0.5 : 1,
      child: Container(
        padding: const EdgeInsets.symmetric(horizontal: 10, vertical: 6),
        decoration: BoxDecoration(color: col.withValues(alpha: 0.16), borderRadius: BorderRadius.circular(8)),
        child: RichText(text: TextSpan(style: TextStyle(fontSize: 13, color: c.text), children: [
          TextSpan(text: '${winRate!.toStringAsFixed(0)}%', style: TextStyle(fontWeight: FontWeight.w700, color: col)),
          TextSpan(text: ' (${Fmt.price(samples)} lần${suffix ?? ''})', style: TextStyle(color: c.muted, fontSize: 12)),
        ])),
      ),
    );
  }
}
