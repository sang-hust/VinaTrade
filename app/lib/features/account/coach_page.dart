import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:go_router/go_router.dart';

import '../../core/api.dart';
import '../../core/format.dart';
import '../../core/responsive.dart';
import '../../core/theme.dart';
import '../../shared/widgets/common.dart';

class CoachPage extends ConsumerStatefulWidget {
  final String week;
  const CoachPage({super.key, required this.week});
  @override
  ConsumerState<CoachPage> createState() => _CoachPageState();
}

class _CoachPageState extends ConsumerState<CoachPage> {
  Map<String, dynamic>? r;
  String? err;
  bool busy = false;

  @override
  void initState() {
    super.initState();
    _load();
  }

  Future<void> _load() async {
    try {
      r = asMap(await ref.read(apiProvider).get('/coach/reports/${widget.week}'));
    } on ApiException catch (e) {
      err = e.message;
    }
    if (mounted) setState(() {});
  }

  Future<void> _generate() async {
    setState(() => busy = true);
    try {
      r = asMap(await ref.read(apiProvider).post('/coach/reports/generate'));
      err = null;
    } on ApiException catch (e) {
      err = e.message;
    } finally {
      if (mounted) setState(() => busy = false);
    }
  }

  @override
  Widget build(BuildContext context) {
    final c = context.vn;
    final rep = r;
    return PageBody(
      maxWidth: 900,
      child: ListView(children: [
        Row(children: [IconButton(onPressed: () => context.canPop() ? context.pop() : context.go('/account'), icon: const Icon(Icons.arrow_back)), Expanded(child: Text('Huấn luyện viên tuần', style: Theme.of(context).textTheme.titleLarge)), FilledButton(onPressed: busy ? null : _generate, child: Text(busy ? 'Đang tạo…' : 'Tạo báo cáo ngay'))]),
        const SizedBox(height: 12),
        if (rep == null && err == null) const SkeletonList(count: 3),
        if (rep == null && err != null) EmptyState(icon: Icons.sports, message: err!, actionLabel: 'Tạo báo cáo ngay', onAction: _generate),
        if (rep != null) ...[
          Text('Tuần từ ${Fmt.date(Fmt.parseDate(rep['week_start']), year: true)} · 12 tuần dữ liệu', style: TextStyle(color: c.faint, fontSize: 12)),
          const SizedBox(height: 10),
          Row(children: [
            for (final e in [('Danh mục', asNum(asMap(rep['benchmark'])['portfolio_pct'])), ('VN-Index', asNum(asMap(rep['benchmark'])['vnindex_pct'])), ('Tiết kiệm', asNum(asMap(rep['benchmark'])['savings_pct']))])
              Expanded(child: Padding(padding: const EdgeInsets.only(right: 8), child: KpiTile(label: e.$1, value: Fmt.pct(e.$2), valueColor: c.changeColor(e.$2)))),
          ]),
          SizedBox(height: context.gap),
          AppCard(child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
            Text('3 điều cần chú ý', style: Theme.of(context).textTheme.titleMedium),
            const SizedBox(height: 8),
            for (final (i, ins) in asList(rep['insights']).indexed) Padding(padding: const EdgeInsets.only(bottom: 8), child: Row(crossAxisAlignment: CrossAxisAlignment.start, children: [CircleAvatar(radius: 11, backgroundColor: c.ai.withValues(alpha: 0.25), child: Text('${i + 1}', style: TextStyle(fontSize: 11, color: c.ai, fontWeight: FontWeight.w700))), const SizedBox(width: 10), Expanded(child: Text(ins['text'].toString(), style: const TextStyle(fontSize: 14)))])),
            if (rep['rule'] != null) Container(margin: const EdgeInsets.only(top: 6), padding: const EdgeInsets.all(10), decoration: BoxDecoration(color: c.ai.withValues(alpha: 0.12), borderRadius: BorderRadius.circular(8)), child: Row(children: [Icon(Icons.flag_outlined, color: c.ai, size: 18), const SizedBox(width: 8), Expanded(child: Text('Quy tắc gợi ý tuần tới: ${rep['rule']}', style: TextStyle(color: c.text, fontWeight: FontWeight.w600)))])),
          ])),
          SizedBox(height: context.gap),
          if (rep['summary'] != null) AppCard(child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [Row(children: [Icon(Icons.auto_awesome, size: 16, color: c.ai), const SizedBox(width: 6), Text('Nhận xét của huấn luyện viên', style: Theme.of(context).textTheme.titleMedium)]), const SizedBox(height: 8), Text(rep['summary'].toString(), style: const TextStyle(height: 1.5))])),
          SizedBox(height: context.gap),
          AppCard(child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
            Text('Số liệu', style: Theme.of(context).textTheme.titleMedium),
            const SizedBox(height: 8),
            Wrap(spacing: 18, runSpacing: 10, children: [
              for (final e in [('Số lệnh đã đóng', 'trades'), ('Tỷ lệ thắng', 'win_rate'), ('Lãi TB (%)', 'avg_win_pct'), ('Lỗ TB (%)', 'avg_loss_pct'), ('Giữ lệnh lãi (ngày)', 'avg_hold_win'), ('Giữ lệnh lỗ (ngày)', 'avg_hold_loss'), ('Vượt rào Đỏ', 'red_overrides'), ('Bình quân giá xuống', 'average_down'), ('Hạ cắt lỗ', 'stop_lowered'), ('Cầu dao bật', 'guard_on')])
                LabeledValue(e.$1, asMap(rep['metrics'])[e.$2]?.toString() ?? Fmt.dash),
            ]),
          ])),
          const DisclaimerText(),
        ],
      ]),
    );
  }
}
