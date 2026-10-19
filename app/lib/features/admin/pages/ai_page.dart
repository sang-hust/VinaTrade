import 'package:fl_chart/fl_chart.dart';
import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../../../core/format.dart';
import '../../../core/providers.dart';
import '../../../core/responsive.dart';
import '../../../core/theme.dart';
import '../../../shared/widgets/common.dart';
import '../admin_common.dart';

/// A08 – Chi phí AI: tokens and cost by day, by user, by task; monthly budget and per-user daily question cap.
class AiPage extends ConsumerStatefulWidget {
  const AiPage({super.key});
  @override
  ConsumerState<AiPage> createState() => _AiPageState();
}

class _AiPageState extends ConsumerState<AiPage> {
  int days = 30;
  @override
  Widget build(BuildContext context) {
    final c = context.vn;
    final d = ref.watch(getMapProvider('/admin/ai-usage?days=$days'));
    final cfg = ref.watch(getListProvider('/admin/config'));
    return Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
      AdminHeader('Chi phí AI', subtitle: 'Token và chi phí theo ngày, theo người dùng, theo tác vụ. Đặt ngân sách tháng và hạn mức câu hỏi mỗi người mỗi ngày.', actions: [
        Segmented<int>(options: const [(7, '7 ngày'), (30, '30 ngày'), (90, '90 ngày')], value: days, onChanged: (v) => setState(() => days = v)),
      ]),
      d.when(
        loading: () => const SkeletonList(),
        error: (e, _) => ErrorBox(e),
        data: (u) {
          final daily = asList(u['daily']);
          final total = daily.fold<double>(0, (a, r) => a + (asNum(r['cost_usd']) ?? 0));
          final questions = daily.fold<int>(0, (a, r) => a + (asInt(r['questions']) ?? 0));
          final budget = asNum(asMap(u['limits'])['monthly_budget_usd']) ?? 50;
          final byTask = asList(u['by_task'])..sort((a, b) => (asNum(b['cost_usd']) ?? 0).compareTo(asNum(a['cost_usd']) ?? 0));
          final chart = AppCard(child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
            Text('Chi phí theo ngày (USD)', style: Theme.of(context).textTheme.titleMedium),
            const SizedBox(height: 10),
            SizedBox(
              height: 170,
              child: daily.isEmpty
                  ? Center(child: Text('Chưa có lượt dùng AI trong kỳ.', style: TextStyle(color: c.faint, fontSize: 12.5)))
                  : BarChart(BarChartData(
                      gridData: const FlGridData(show: false), borderData: FlBorderData(show: false),
                      barTouchData: BarTouchData(touchTooltipData: BarTouchTooltipData(getTooltipItem: (g, gi, rod, ri) => BarTooltipItem('${Fmt.date(Fmt.parseDate(daily[gi]['date']))}: \$${rod.toY.toStringAsFixed(3)} · ${daily[gi]['questions']} câu', TextStyle(color: c.text, fontSize: 12)))),
                      titlesData: FlTitlesData(
                        leftTitles: AxisTitles(sideTitles: SideTitles(showTitles: true, reservedSize: 36, getTitlesWidget: (v, _) => Text(v.toStringAsFixed(2), style: TextStyle(fontSize: 10, color: c.faint)))),
                        rightTitles: const AxisTitles(), topTitles: const AxisTitles(),
                        bottomTitles: AxisTitles(sideTitles: SideTitles(showTitles: true, reservedSize: 22, getTitlesWidget: (v, _) {
                          final i = v.toInt();
                          if (i < 0 || i >= daily.length || (daily.length > 10 && i % (daily.length ~/ 6 + 1) != 0)) return const SizedBox.shrink();
                          return Text(Fmt.date(Fmt.parseDate(daily[i]['date'])), style: TextStyle(fontSize: 10, color: c.faint));
                        })),
                      ),
                      barGroups: [for (var i = 0; i < daily.length; i++) BarChartGroupData(x: i, barRods: [BarChartRodData(toY: (asNum(daily[i]['cost_usd']) ?? 0).toDouble(), color: c.ai, width: daily.length > 40 ? 4 : 10, borderRadius: BorderRadius.circular(2))])],
                    )),
            ),
          ]));
          final taskCard = AppCard(padding: EdgeInsets.zero, child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
            Padding(padding: const EdgeInsets.fromLTRB(16, 14, 16, 4), child: Text('Theo tác vụ', style: Theme.of(context).textTheme.titleMedium)),
            SingleChildScrollView(scrollDirection: Axis.horizontal, child: DataTable(headingTextStyle: TextStyle(fontSize: 12.5, color: c.muted, fontWeight: FontWeight.w600), columns: const [DataColumn(label: Text('Tác vụ')), DataColumn(label: Text('Lượt'), numeric: true), DataColumn(label: Text('Token vào / ra'), numeric: true), DataColumn(label: Text('Chi phí'), numeric: true)],
                rows: [for (final r in byTask) DataRow(cells: [DataCell(cell(r['task'].toString(), bold: true)), DataCell(cell(Fmt.price(asNum(r['questions'])))), DataCell(cell('${Fmt.volume(asNum(r['input_tokens']))} / ${Fmt.volume(asNum(r['output_tokens']))}')), DataCell(cell('\$${(asNum(r['cost_usd']) ?? 0).toStringAsFixed(3)}'))])])),
            if (byTask.isEmpty) Padding(padding: const EdgeInsets.all(16), child: Text('Chưa có dữ liệu.', style: TextStyle(color: c.muted))),
            const SizedBox(height: 8),
          ]));
          final userCard = AppCard(child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
            Text('Theo người dùng', style: Theme.of(context).textTheme.titleMedium),
            for (final r in asList(u['by_user'])) ListTile(dense: true, contentPadding: EdgeInsets.zero, title: Text(r['email'].toString(), style: const TextStyle(fontSize: 13)), trailing: Text('${r['questions']} câu · \$${(asNum(r['cost_usd']) ?? 0).toStringAsFixed(2)}', style: TextStyle(color: c.muted, fontSize: 12.5))),
            if (asList(u['by_user']).isEmpty) Text('Chưa ai hỏi AI trong kỳ.', style: TextStyle(color: c.muted, fontSize: 13)),
          ]));
          return Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
            Wrap(spacing: 12, runSpacing: 12, children: [
              SizedBox(width: 230, child: KpiTile(label: 'Chi phí $days ngày', value: '\$${total.toStringAsFixed(2)}', note: 'Ngân sách tháng \$${Fmt.num_(budget, decimals: 0)}', valueColor: total > budget ? c.down : null)),
              SizedBox(width: 230, child: KpiTile(label: 'Câu hỏi $days ngày', value: Fmt.price(questions), note: 'Hạn mức ${asMap(u['limits'])['daily_questions']} câu/người/ngày')),
              SizedBox(width: 230, child: KpiTile(label: 'Mô hình', value: u['model'].toString(), note: 'Giá tham chiếu \$5 / \$25 mỗi triệu token')),
            ]),
            const SizedBox(height: 16),
            chart,
            const SizedBox(height: 16),
            if (context.isDesktop) Row(crossAxisAlignment: CrossAxisAlignment.start, children: [Expanded(child: taskCard), const SizedBox(width: 16), Expanded(child: userCard)]) else ...[taskCard, const SizedBox(height: 16), userCard],
            const SizedBox(height: 16),
            cfg.when(
              loading: () => const SizedBox.shrink(),
              error: (e, _) => const SizedBox.shrink(),
              data: (rows) {
                final r = rows.where((x) => x['key'] == 'ai.limits').firstOrNull;
                return r == null ? const SizedBox.shrink() : ConfigCard(key: const ValueKey('ai.limits'), row: r, onChanged: () {
                  ref.invalidate(getProvider('/admin/config'));
                  ref.invalidate(getProvider('/admin/ai-usage?days=$days'));
                });
              },
            ),
          ]);
        },
      ),
    ]);
  }
}
