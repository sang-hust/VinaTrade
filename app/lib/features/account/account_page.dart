import 'package:flutter/material.dart';
import 'package:flutter/services.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:go_router/go_router.dart';
import 'package:qr_flutter/qr_flutter.dart';
import 'package:url_launcher/url_launcher.dart';

import '../../core/api.dart';
import '../../core/format.dart';
import '../../core/providers.dart';
import '../../core/responsive.dart';
import '../../core/session.dart';
import '../../core/theme.dart';
import '../../shared/widgets/common.dart';

class AccountPage extends ConsumerStatefulWidget {
  final String? section;
  const AccountPage({super.key, this.section});
  @override
  ConsumerState<AccountPage> createState() => _AccountPageState();
}

class _AccountPageState extends ConsumerState<AccountPage> {
  @override
  Widget build(BuildContext context) {
    final s = ref.watch(sessionProvider);
    final c = context.vn;
    final cards = [
      _Display(s),
      _RiskLimits(s),
      _Notify(s),
      _Security(s),
      _Coach(),
      AppCard(child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
        Row(children: [CircleAvatar(backgroundColor: c.accent.withValues(alpha: 0.25), child: Text((s.user['full_name']?.toString() ?? '?').characters.first.toUpperCase())), const SizedBox(width: 10), Expanded(child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [Text(s.user['full_name']?.toString() ?? '', style: const TextStyle(fontWeight: FontWeight.w700)), Text(s.user['email']?.toString() ?? '', style: TextStyle(color: c.muted, fontSize: 12.5))]))]),
        const SizedBox(height: 10),
        if (s.isAdmin) ListTile(contentPadding: EdgeInsets.zero, leading: const Icon(Icons.admin_panel_settings_outlined), title: const Text('Quản trị'), trailing: const Icon(Icons.chevron_right), onTap: () => context.go('/admin/overview')),
        ListTile(contentPadding: EdgeInsets.zero, leading: const Icon(Icons.logout), title: const Text('Đăng xuất'), onTap: () => ref.read(sessionProvider.notifier).logout()),
      ])),
    ];
    return PageBody(
      maxWidth: 1100,
      child: ListView(children: [
        Text('Tài khoản', style: Theme.of(context).textTheme.titleLarge),
        const SizedBox(height: 12),
        if (context.isDesktop)
          Row(crossAxisAlignment: CrossAxisAlignment.start, children: [
            Expanded(child: Column(children: [for (final (i, w) in cards.indexed) if (i.isEven) Padding(padding: const EdgeInsets.only(bottom: 16), child: w.stagger(context, i))])),
            const SizedBox(width: 16),
            Expanded(child: Column(children: [for (final (i, w) in cards.indexed) if (i.isOdd) Padding(padding: const EdgeInsets.only(bottom: 16), child: w.stagger(context, i))])),
          ])
        else
          for (final (i, w) in cards.indexed) Padding(padding: const EdgeInsets.only(bottom: 12), child: w.stagger(context, i)),
      ]),
    );
  }
}

class _Display extends ConsumerWidget {
  final SessionState s;
  const _Display(this.s);
  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final c = context.vn;
    final n = ref.read(sessionProvider.notifier);
    return AppCard(
      child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
        Text('Hiển thị', style: Theme.of(context).textTheme.titleMedium),
        const SizedBox(height: 10),
        Text('Mức chi tiết', style: TextStyle(color: c.faint, fontSize: 12)),
        const SizedBox(height: 4),
        Segmented<String>(options: const [('SIMPLE', 'Đơn giản'), ('STANDARD', 'Vừa đủ'), ('FULL', 'Đầy đủ')], value: s.uiDetail, onChanged: (v) => n.updateSettings({'ui_detail': v})),
        Padding(padding: const EdgeInsets.only(top: 4), child: Text({'SIMPLE': 'Thẻ khuyến nghị, kế hoạch mua bán, cảnh báo rủi ro; ẩn chỉ báo.', 'STANDARD': 'Thêm MA, RSI, MACD, điểm thành phần, cơ bản, lịch sử tín hiệu.', 'FULL': 'Mọi chỉ báo, bảng đợt tăng, dòng tiền, trình ghép bộ lọc nâng cao.'}[s.uiDetail] ?? '', style: TextStyle(color: c.muted, fontSize: 12))),
        const SizedBox(height: 12),
        Text('Khung đầu tư mặc định', style: TextStyle(color: c.faint, fontSize: 12)),
        const SizedBox(height: 4),
        Segmented<String>(options: const [('SHORT', 'Ngắn hạn'), ('MID', 'Trung hạn'), ('LONG', 'Dài hạn')], value: s.horizon, onChanged: (v) {
          n.updateSettings({'default_horizon': v});
          ref.read(horizonProvider.notifier).set(v);
        }),
        const SizedBox(height: 12),
        Text('Giao diện', style: TextStyle(color: c.faint, fontSize: 12)),
        const SizedBox(height: 4),
        Segmented<String>(options: const [('dark', 'Tối'), ('light', 'Sáng'), ('system', 'Theo hệ thống')], value: s.theme, onChanged: (v) => n.updateSettings({'theme': v})),
        SwitchListTile(contentPadding: EdgeInsets.zero, title: const Text('Giảm chuyển động'), value: s.reduceMotion, onChanged: (v) => n.updateSettings({'reduce_motion': v})),
      ]),
    );
  }
}

class _RiskLimits extends ConsumerStatefulWidget {
  final SessionState s;
  const _RiskLimits(this.s);
  @override
  ConsumerState<_RiskLimits> createState() => _RiskLimitsState();
}

class _RiskLimitsState extends ConsumerState<_RiskLimits> {
  late Map<String, dynamic> lim = {...widget.s.riskLimits};

  Future<void> _set(String k, num v) async {
    final old = lim[k];
    setState(() => lim[k] = v);
    try {
      final r = asMap(await ref.read(apiProvider).put('/me/risk-limits', data: {k: v}));
      ref.read(sessionProvider.notifier).patchLocal({'risk_limits': r});
    } on ApiException catch (e) {
      setState(() => lim[k] = old);
      if (mounted) showToast(context, e.message, error: true);
    }
  }

  Widget _stepper(String label, String key, num step, {String unit = '%', int decimals = 1, String? help}) {
    final v = asNum(lim[key]) ?? 0;
    final c = context.vn;
    return Padding(
      padding: const EdgeInsets.symmetric(vertical: 6),
      child: Row(children: [
        Expanded(child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [Text(label, style: const TextStyle(fontSize: 13.5)), if (help != null) Text(help, style: TextStyle(color: c.faint, fontSize: 11))])),
        IconButton(icon: const Icon(Icons.remove_circle_outline, size: 20), onPressed: () => _set(key, double.parse((v - step).clamp(0, 999).toStringAsFixed(decimals)))),
        SizedBox(width: 72, child: Text('${decimals == 0 ? v.round() : v.toStringAsFixed(decimals).replaceAll('.', ',')}$unit', textAlign: TextAlign.center, style: const TextStyle(fontWeight: FontWeight.w700))),
        IconButton(icon: const Icon(Icons.add_circle_outline, size: 20), onPressed: () => _set(key, double.parse((v + step).toStringAsFixed(decimals)))),
      ]),
    );
  }

  @override
  Widget build(BuildContext context) {
    final c = context.vn;
    return AppCard(
      child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
        Text('Giới hạn rủi ro', style: Theme.of(context).textTheme.titleMedium),
        Text('Chỉ đặt chặt hơn mặc định của quản trị viên. Mọi kiểm tra trước khi mua dùng các giới hạn này.', style: TextStyle(color: c.muted, fontSize: 12.5)),
        const SizedBox(height: 6),
        _stepper('Rủi ro mỗi lệnh', 'max_risk_per_trade_pct', 0.25, help: 'số tiền có thể lỗ nếu chạm cắt lỗ'),
        _stepper('Cắt lỗ mặc định', 'stop_loss_pct', 1),
        _stepper('Tỷ trọng một mã', 'max_position_pct', 5, decimals: 0),
        _stepper('Tỷ trọng một ngành', 'max_sector_pct', 5, decimals: 0),
        _stepper('Nhóm tương quan', 'max_correlated_group_pct', 5, decimals: 0),
        _stepper('Cầu dao: lỗ tuần', 'weekly_loss_limit_pct', 0.5),
        _stepper('Cầu dao: lỗ tháng', 'monthly_loss_limit_pct', 1),
        _stepper('Nghỉ sau khi cầu dao bật', 'cooldown_sessions', 1, unit: ' phiên', decimals: 0),
        _stepper('Lãi/lỗ tối thiểu', 'min_risk_reward', 0.5, unit: '×'),
      ]),
    );
  }
}

class _Notify extends ConsumerStatefulWidget {
  final SessionState s;
  const _Notify(this.s);
  @override
  ConsumerState<_Notify> createState() => _NotifyState();
}

class _NotifyState extends ConsumerState<_Notify> {
  Map<String, dynamic>? link;
  @override
  Widget build(BuildContext context) {
    final c = context.vn;
    final s = ref.watch(sessionProvider);
    final n = ref.read(sessionProvider.notifier);
    final st = s.settings;
    final tg = s.user['telegram_chat_id'];
    return AppCard(
      child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
        Text('Nhận cảnh báo', style: Theme.of(context).textTheme.titleMedium),
        SwitchListTile(contentPadding: EdgeInsets.zero, title: const Text('Thông báo đẩy'), subtitle: Text('Trên điện thoại / Windows', style: TextStyle(fontSize: 11.5, color: c.faint)), value: st['notify_push'] == true, onChanged: (v) => n.updateSettings({'notify_push': v})),
        SwitchListTile(contentPadding: EdgeInsets.zero, title: const Text('Telegram'), subtitle: Text(tg != null ? 'Đã liên kết' : 'Chưa liên kết', style: TextStyle(fontSize: 11.5, color: tg != null ? c.up : c.faint)), value: st['notify_telegram'] == true, onChanged: (v) => n.updateSettings({'notify_telegram': v})),
        Row(children: [
          if (tg == null)
            OutlinedButton.icon(onPressed: () async {
              final r = asMap(await ref.read(apiProvider).post('/me/telegram/link'));
              setState(() => link = asMap(r['data']));
            }, icon: const Icon(Icons.send, size: 16), label: const Text('Liên kết Telegram'))
          else
            TextButton(onPressed: () async {
              await ref.read(apiProvider).delete('/me/telegram/link');
              await n.refreshMe();
            }, child: const Text('Hủy liên kết')),
        ]),
        if (link != null)
          Container(
            margin: const EdgeInsets.only(top: 8), padding: const EdgeInsets.all(10),
            decoration: BoxDecoration(color: c.surface2, borderRadius: BorderRadius.circular(8)),
            child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
              Text(link!['instructions']?.toString() ?? '', style: const TextStyle(fontSize: 13)),
              const SizedBox(height: 6),
              Row(children: [
                SelectableText('/start ${link!['code']}', style: const TextStyle(fontWeight: FontWeight.w700, fontFamily: 'monospace')),
                IconButton(icon: const Icon(Icons.copy, size: 16), onPressed: () {
                  Clipboard.setData(ClipboardData(text: '/start ${link!['code']}'));
                  showToast(context, 'Đã sao chép');
                }),
                if (link!['deep_link'] != null) TextButton(onPressed: () => launchUrl(Uri.parse(link!['deep_link']), mode: LaunchMode.externalApplication), child: const Text('Mở Telegram')),
                TextButton(onPressed: () => n.refreshMe(), child: const Text('Đã gửi, kiểm tra')),
              ]),
              if (link!['bot_username'] == null) Text('Máy chủ chưa cấu hình bot Telegram. Quản trị viên cần đặt TELEGRAM_BOT_TOKEN.', style: TextStyle(color: c.ref, fontSize: 12)),
            ]),
          ),
        SwitchListTile(contentPadding: EdgeInsets.zero, title: const Text('Email'), subtitle: Text('Báo cáo cuối ngày, cuối tuần', style: TextStyle(fontSize: 11.5, color: c.faint)), value: st['notify_email'] == true, onChanged: (v) => n.updateSettings({'notify_email': v})),
        const Divider(),
        Row(children: [
          Expanded(child: Text('Giờ yên lặng: ${st['quiet_start'] ?? '—'} – ${st['quiet_end'] ?? '—'}', style: const TextStyle(fontSize: 13.5))),
          TextButton(onPressed: () async {
            final a = await showTimePicker(context: context, initialTime: const TimeOfDay(hour: 22, minute: 0), helpText: 'Bắt đầu yên lặng');
            if (a == null || !context.mounted) return;
            final b = await showTimePicker(context: context, initialTime: const TimeOfDay(hour: 7, minute: 0), helpText: 'Kết thúc yên lặng');
            if (b == null) return;
            String f(TimeOfDay t) => '${t.hour.toString().padLeft(2, '0')}:${t.minute.toString().padLeft(2, '0')}';
            n.updateSettings({'quiet_start': f(a), 'quiet_end': f(b)});
          }, child: const Text('Đổi')),
        ]),
        Text('Cảnh báo cắt lỗ (khẩn) luôn gửi, bỏ qua giờ yên lặng.', style: TextStyle(color: c.faint, fontSize: 11.5)),
        const SizedBox(height: 8),
        Text('Công ty chứng khoán đang dùng', style: TextStyle(color: c.faint, fontSize: 12)),
        Wrap(spacing: 6, children: [
          for (final b in const ['VCBS', 'Pinetree', 'FPTS', 'SSI', 'VPS', 'TCBS', 'VNDirect', 'MBS'])
            FilterChip(label: Text(b), selected: ((st['brokers'] as List?) ?? []).contains(b), onSelected: (v) {
              final cur = List<String>.from(((st['brokers'] as List?) ?? []).map((e) => e.toString()));
              v ? cur.add(b) : cur.remove(b);
              n.updateSettings({'brokers': cur});
            }),
        ]),
        Text('Vinatrade không lưu mật khẩu và không đặt lệnh thay bạn.', style: TextStyle(color: c.faint, fontSize: 11.5)),
      ]),
    );
  }
}

class _Security extends ConsumerStatefulWidget {
  final SessionState s;
  const _Security(this.s);
  @override
  ConsumerState<_Security> createState() => _SecurityState();
}

class _SecurityState extends ConsumerState<_Security> {
  Map<String, dynamic>? setup;
  final code = TextEditingController();
  @override
  Widget build(BuildContext context) {
    final c = context.vn;
    final s = ref.watch(sessionProvider);
    final devices = ref.watch(getListProvider('/me/devices'));
    final api = ref.read(apiProvider);
    return AppCard(
      child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
        Text('Bảo mật & thiết bị', style: Theme.of(context).textTheme.titleMedium),
        const SizedBox(height: 8),
        Row(children: [
          Expanded(child: Text('Xác thực 2 lớp: ${s.user['totp_enabled'] == true ? 'Đang bật' : 'Chưa bật'}', style: const TextStyle(fontSize: 13.5))),
          if (s.user['totp_enabled'] == true)
            TextButton(onPressed: () async {
              final v = await _askCode(context);
              if (v == null) return;
              try {
                await api.post('/auth/2fa/disable', data: {'code': v});
                await ref.read(sessionProvider.notifier).refreshMe();
              } on ApiException catch (e) {
                if (context.mounted) showToast(context, e.message, error: true);
              }
            }, child: const Text('Tắt'))
          else
            OutlinedButton(onPressed: () async {
              final r = asMap(await api.post('/auth/2fa/setup'));
              setState(() => setup = asMap(r['data']));
            }, child: const Text('Bật 2 lớp')),
        ]),
        if (setup != null)
          Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
            const SizedBox(height: 8),
            Text('Quét mã bằng Google Authenticator rồi nhập mã 6 số:', style: TextStyle(color: c.muted, fontSize: 12.5)),
            const SizedBox(height: 8),
            Container(color: Colors.white, padding: const EdgeInsets.all(8), child: QrImageView(data: setup!['otpauth_uri'].toString(), size: 160)),
            SelectableText('Khóa dự phòng: ${setup!['secret']}', style: TextStyle(fontSize: 11.5, color: c.faint)),
            Row(children: [
              SizedBox(width: 140, child: TextField(controller: code, keyboardType: TextInputType.number, decoration: const InputDecoration(labelText: 'Mã 6 số'))),
              const SizedBox(width: 8),
              FilledButton(onPressed: () async {
                try {
                  await api.post('/auth/2fa/verify', data: {'code': code.text.trim()});
                  setState(() => setup = null);
                  await ref.read(sessionProvider.notifier).refreshMe();
                  if (context.mounted) showToast(context, 'Đã bật xác thực 2 lớp');
                } on ApiException catch (e) {
                  if (context.mounted) showToast(context, e.message, error: true);
                }
              }, child: const Text('Xác nhận')),
            ]),
          ]),
        const Divider(),
        TextButton.icon(onPressed: () => _changePassword(context, api), icon: const Icon(Icons.lock_outline, size: 16), label: const Text('Đổi mật khẩu')),
        const Divider(),
        Text('Thiết bị đang đăng nhập (tối đa 3)', style: TextStyle(color: c.faint, fontSize: 12)),
        devices.when(
          loading: () => const Skeleton(),
          error: (e, _) => const SizedBox.shrink(),
          data: (rows) => Column(children: [
            for (final d in rows)
              ListTile(dense: true, contentPadding: EdgeInsets.zero, leading: Icon({'android': Icons.android, 'ios': Icons.phone_iphone, 'windows': Icons.desktop_windows, 'macos': Icons.laptop_mac}[d['platform']] ?? Icons.language), title: Text(d['name']?.toString() ?? d['platform'].toString(), maxLines: 1, overflow: TextOverflow.ellipsis), subtitle: Text('Hoạt động ${Fmt.relative(Fmt.parseDate(d['last_seen_at']))}', style: TextStyle(fontSize: 11.5, color: c.faint)),
                  trailing: IconButton(tooltip: 'Đăng xuất từ xa', icon: const Icon(Icons.logout, size: 18), onPressed: () async {
                    await api.delete('/me/devices/${d['id']}');
                    ref.invalidate(getProvider('/me/devices'));
                  })),
          ]),
        ),
      ]),
    );
  }

  Future<String?> _askCode(BuildContext context) {
    final ctl = TextEditingController();
    return showDialog<String>(context: context, builder: (ctx) => AlertDialog(title: const Text('Nhập mã xác thực'), content: TextField(controller: ctl, autofocus: true, keyboardType: TextInputType.number), actions: [TextButton(onPressed: () => Navigator.pop(ctx), child: const Text('Hủy')), FilledButton(onPressed: () => Navigator.pop(ctx, ctl.text.trim()), child: const Text('Xác nhận'))]));
  }

  Future<void> _changePassword(BuildContext context, ApiClient api) async {
    final cur = TextEditingController(), nw = TextEditingController();
    final ok = await showDialog<bool>(context: context, builder: (ctx) => AlertDialog(title: const Text('Đổi mật khẩu'), content: Column(mainAxisSize: MainAxisSize.min, children: [TextField(controller: cur, obscureText: true, decoration: const InputDecoration(labelText: 'Mật khẩu hiện tại')), const SizedBox(height: 8), TextField(controller: nw, obscureText: true, decoration: const InputDecoration(labelText: 'Mật khẩu mới (≥ 8 ký tự)'))]), actions: [TextButton(onPressed: () => Navigator.pop(ctx, false), child: const Text('Hủy')), FilledButton(onPressed: () => Navigator.pop(ctx, true), child: const Text('Đổi'))]));
    if (ok != true) return;
    try {
      await api.post('/auth/password/change', data: {'current_password': cur.text, 'new_password': nw.text});
      if (context.mounted) showToast(context, 'Đã đổi mật khẩu');
    } on ApiException catch (e) {
      if (context.mounted) showToast(context, e.message, error: true);
    }
  }
}

class _Coach extends ConsumerWidget {
  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final c = context.vn;
    final reports = ref.watch(getListProvider('/coach/reports?limit=8'));
    return AppCard(
      child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
        Row(children: [Expanded(child: Text('Huấn luyện viên AI', style: Theme.of(context).textTheme.titleMedium)), TextButton(onPressed: () => context.push('/account/coach/latest'), child: const Text('Tạo báo cáo ngay'))]),
        reports.when(
          loading: () => const Skeleton(),
          error: (e, _) => const SizedBox.shrink(),
          data: (rows) => rows.isEmpty
              ? Text('Mỗi sáng thứ Bảy, AI đọc nhật ký giao dịch và đưa 3 nhận xét kèm số liệu. Chưa có báo cáo.', style: TextStyle(color: c.muted, fontSize: 12.5))
              : Column(children: [for (final r in rows) ListTile(dense: true, contentPadding: EdgeInsets.zero, title: Text('Tuần ${Fmt.date(Fmt.parseDate(r['week_start']), year: true)}'), subtitle: Text(asList(r['insights']).firstOrNull?['text']?.toString() ?? '', maxLines: 1, overflow: TextOverflow.ellipsis), trailing: const Icon(Icons.chevron_right), onTap: () => context.push('/account/coach/${r['week_start']}'))]),
        ),
      ]),
    );
  }
}
