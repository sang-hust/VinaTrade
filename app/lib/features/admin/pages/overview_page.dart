import 'package:flutter/material.dart';
import 'package:flutter/services.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:go_router/go_router.dart';

import '../../../core/api.dart';
import '../../../core/format.dart';
import '../../../core/providers.dart';
import '../../../core/responsive.dart';
import '../../../core/theme.dart';
import '../../../shared/widgets/common.dart';
import '../../../shared/widgets/score.dart';
import '../admin_common.dart';

/// A01 – Tổng quan hệ thống: 5 KPI tiles, EOD chain with per-step log, "Cần xử lý", data sources, ops report export.
class OverviewPage extends ConsumerWidget {
  const OverviewPage({super.key});
  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final c = context.vn;
    final d = ref.watch(getMapProvider('/admin/overview'));
    return d.when(
      loading: () => const SkeletonList(),
      error: (e, _) => ErrorBox(e, onRetry: () => ref.invalidate(getProvider('/admin/overview'))),
      data: (o) {
        final k = asMap(o['kpis']);
        final steps = asList(o['eod_chain']);
        final sources = asList(o['sources']);
        final todo = asList(o['todo']);
        final p95 = asNum(k['alert_latency_p95_ms']);
        final aiCost = asNum(k['ai_cost_usd']) ?? 0, aiBudget = asNum(k['ai_budget_usd']) ?? 1;
        final wide = context.isDesktop;
        final chain = AppCard(child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
          Row(children: [
            Expanded(child: Text('Chuỗi xử lý cuối ngày', style: Theme.of(context).textTheme.titleMedium)),
            Text('Bắt đầu 15:05 · ${o['eod_done']} / ${o['eod_total']} bước xong', style: TextStyle(color: c.muted, fontSize: 12.5)),
            const SizedBox(width: 8),
            FilledButton.tonalIcon(onPressed: () => runJob(context, ref, 'eod'), icon: const Icon(Icons.play_arrow, size: 16), label: const Text('Chạy toàn bộ')),
          ]),
          const SizedBox(height: 8),
          for (final s in steps)
            InkWell(
              borderRadius: BorderRadius.circular(8),
              onTap: s['id'] != null ? () => showJobRun(context, ref, asInt(s['id'])!) : null,
              child: Padding(
                padding: const EdgeInsets.symmetric(vertical: 5, horizontal: 4),
                child: Row(children: [
                  SizedBox(width: 44, child: Text(s['at']?.toString() ?? '', style: TextStyle(color: c.muted, fontSize: 12.5, fontFeatures: const [FontFeature.tabularFigures()]))),
                  Icon({'DONE': Icons.check_circle, 'WARN': Icons.warning_amber_rounded, 'FAILED': Icons.cancel, 'RUNNING': Icons.autorenew}[s['status']] ?? Icons.radio_button_unchecked, color: jobStatusColor(c, s['status']?.toString()), size: 18),
                  const SizedBox(width: 10),
                  Expanded(child: Text(s['label']?.toString() ?? s['name'].toString(), style: const TextStyle(fontWeight: FontWeight.w600, fontSize: 13))),
                  Flexible(child: Text(s['error'] != null ? 'Lỗi: ${s['error'].toString().split('\n').last}' : (s['summary']?.toString() ?? (s['status'] == 'RUNNING' ? 'Đang chạy' : (s['status'] == 'PENDING' ? 'Chưa chạy' : ''))),
                      maxLines: 1, overflow: TextOverflow.ellipsis, textAlign: TextAlign.right, style: TextStyle(fontSize: 12, color: s['error'] != null ? c.down : (s['status'] == 'RUNNING' ? c.accent : c.muted)))),
                  if (s['status'] == 'FAILED' || s['status'] == 'WARN') ...[const SizedBox(width: 6), SizedBox(height: 28, child: OutlinedButton(style: OutlinedButton.styleFrom(visualDensity: VisualDensity.compact, padding: const EdgeInsets.symmetric(horizontal: 8)), onPressed: () => runJob(context, ref, s['name'].toString()), child: const Text('Chạy lại', style: TextStyle(fontSize: 12))))],
                ]),
              ),
            ),
          Text('Bấm một bước để xem log.', style: TextStyle(color: c.faint, fontSize: 11.5)),
        ]));
        final todoCard = AppCard(child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
          Text('Cần xử lý', style: Theme.of(context).textTheme.titleMedium),
          const SizedBox(height: 6),
          if (todo.isEmpty) Text('Không có việc cần Admin quyết định.', style: TextStyle(color: c.muted, fontSize: 13)),
          for (final t in todo)
            Padding(
              padding: const EdgeInsets.symmetric(vertical: 6),
              child: Row(children: [
                Container(width: 3, height: 36, decoration: BoxDecoration(color: t['kind'] == 'DRAFT_READY' ? c.accent : c.ref, borderRadius: BorderRadius.circular(2))),
                const SizedBox(width: 10),
                Expanded(child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [Text(t['text'].toString(), style: const TextStyle(fontWeight: FontWeight.w600, fontSize: 13.5)), if ((t['detail']?.toString() ?? '').isNotEmpty) Text(t['detail'].toString(), style: TextStyle(fontSize: 12, color: c.muted), maxLines: 2, overflow: TextOverflow.ellipsis)])),
                OutlinedButton(style: OutlinedButton.styleFrom(visualDensity: VisualDensity.compact), onPressed: () => context.go(t['route'].toString()), child: Text(t['action'].toString())),
              ]),
            ),
        ]));
        final sourcesCard = AppCard(child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
          Row(children: [Expanded(child: Text('Nguồn dữ liệu', style: Theme.of(context).textTheme.titleMedium)), TextButton(onPressed: () => context.go('/admin/jobs'), child: const Text('Quản lý nguồn'))]),
          for (final s in sources)
            ListTile(
              dense: true, contentPadding: EdgeInsets.zero,
              title: Text('${s['name']} (${s['role'] == 'PRIMARY' ? 'chính' : 'dự phòng'})', style: const TextStyle(fontWeight: FontWeight.w600, fontSize: 13.5)),
              subtitle: Text(s['last_error']?.toString() ?? (s['role'] == 'PRIMARY' ? 'Giá trong phiên, giá ngày' : 'Giá ngày, BCTC'), style: TextStyle(fontSize: 12, color: s['last_error'] != null ? c.down : c.muted), maxLines: 1, overflow: TextOverflow.ellipsis),
              trailing: Row(mainAxisSize: MainAxisSize.min, children: [
                StatusDot({'OK': c.up, 'DEGRADED': c.ref, 'DOWN': c.down}[s['status']] ?? c.faint, size: 8),
                const SizedBox(width: 6),
                Text(s['enabled'] != true ? 'Đã tắt' : '${{'OK': 'Hoạt động', 'DEGRADED': 'Chậm', 'DOWN': 'Lỗi'}[s['status']] ?? 'Chưa rõ'}${s['latency_ms'] != null ? ', ${((asNum(s['latency_ms']) ?? 0) / 1000).toStringAsFixed(1)} giây' : ''}', style: TextStyle(fontSize: 12.5, color: c.muted)),
              ]),
            ),
          if (o['last_eod'] != null) Text('EOD gần nhất: ${Fmt.dateTime(Fmt.parseDate(o['last_eod']))}', style: TextStyle(color: c.faint, fontSize: 11.5)),
        ]));
        return Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
          AdminHeader('Tổng quan hệ thống', subtitle: '${Fmt.dayLabel(DateTime.now())}. ${o['headline']}', actions: [
            IconButton(tooltip: 'Tải lại', onPressed: () => ref.invalidate(getProvider('/admin/overview')), icon: const Icon(Icons.refresh)),
            OutlinedButton.icon(onPressed: () => _exportReport(context, ref), icon: const Icon(Icons.description_outlined, size: 18), label: const Text('Xuất báo cáo vận hành')),
          ]),
          LayoutBuilder(builder: (ctx, box) {
            final w = ((box.maxWidth - 12 * 4) / 5).clamp(180.0, 400.0);
            final tw = box.maxWidth < 900 ? (box.maxWidth - 12) / 2 : w;
            return Wrap(spacing: 12, runSpacing: 12, children: [
              SizedBox(width: tw, child: KpiTile(label: 'Người dùng hoạt động hôm nay', value: '${k['active_today']} / ${k['users_total']}', note: '${k['users_pending']} tài khoản chờ duyệt · ${k['active_7d']} trong 7 ngày')),
              SizedBox(width: tw, child: KpiTile(label: 'Độ trễ cảnh báo p95', value: p95 != null ? '${(p95 / 1000).toStringAsFixed(p95 < 10000 ? 1 : 0)} giây' : '—', note: 'Mục tiêu ≤ ${k['alert_latency_target_s']} giây', valueColor: p95 == null ? null : (p95 <= 60000 ? c.up : c.down))),
              SizedBox(width: tw, child: KpiTile(label: 'Cảnh báo đã gửi (24 giờ)', value: Fmt.price(asNum(k['alerts_sent_24h'])), note: 'Thất bại ${k['alerts_failed_24h']} (${Fmt.percentOf(asNum(k['alerts_failed_24h']), (asNum(k['alerts_sent_24h']) ?? 0) + (asNum(k['alerts_failed_24h']) ?? 0))})')),
              SizedBox(width: tw, child: KpiTile(label: 'Tỷ lệ thắng tín hiệu 20 phiên', value: k['signal_win_rate_20'] != null ? '${Fmt.num_(asNum(k['signal_win_rate_20']))}%' : '—', note: k['signal_avg_return_20'] != null ? 'Lợi nhuận TB ${Fmt.pct(asNum(k['signal_avg_return_20']))}/tín hiệu' : '120 ngày gần nhất', valueColor: winRateColor(c, asNum(k['signal_win_rate_20'])))),
              SizedBox(width: tw, child: KpiTile(label: 'Chi phí AI tháng này', value: '\$${aiCost.toStringAsFixed(2)}', note: '${(aiCost / aiBudget * 100).toStringAsFixed(0)}% ngân sách \$${Fmt.num_(aiBudget, decimals: 0)}', valueColor: aiCost > aiBudget ? c.down : null)),
            ]);
          }),
          const SizedBox(height: 16),
          if (wide)
            Row(crossAxisAlignment: CrossAxisAlignment.start, children: [Expanded(flex: 3, child: chain), const SizedBox(width: 16), Expanded(flex: 2, child: Column(children: [todoCard, const SizedBox(height: 16), sourcesCard]))])
          else ...[todoCard, const SizedBox(height: 16), chain, const SizedBox(height: 16), sourcesCard],
        ]);
      },
    );
  }

  Future<void> _exportReport(BuildContext context, WidgetRef ref) async {
    try {
      final txt = (await ref.read(apiProvider).get('/admin/overview/report')).toString();
      if (!context.mounted) return;
      await showDialog<void>(
        context: context,
        builder: (ctx) => AlertDialog(
          title: const Text('Báo cáo vận hành'),
          content: SizedBox(width: 680, child: SingleChildScrollView(child: SelectableText(txt, style: const TextStyle(fontFamily: 'monospace', fontSize: 12)))),
          actions: [
            TextButton(onPressed: () => Navigator.pop(ctx), child: const Text('Đóng')),
            FilledButton.icon(onPressed: () {
              Clipboard.setData(ClipboardData(text: txt));
              Navigator.pop(ctx);
              showToast(context, 'Đã sao chép báo cáo');
            }, icon: const Icon(Icons.copy, size: 16), label: const Text('Sao chép')),
          ],
        ),
      );
    } on ApiException catch (e) {
      if (context.mounted) showToast(context, e.message, error: true);
    }
  }
}
