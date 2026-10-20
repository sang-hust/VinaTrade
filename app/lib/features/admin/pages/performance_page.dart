import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../../../core/format.dart';
import '../../../core/providers.dart';
import '../../../core/responsive.dart';
import '../../../core/theme.dart';
import '../../../shared/widgets/common.dart';
import '../../../shared/widgets/score.dart';
import '../admin_common.dart';

/// A10 – Hiệu quả tín hiệu (v1.2): period picker, 4 KPIs, by rating / by sector tables, strategy × market-state heat
/// table (3 states, cells under 30 samples dimmed) and a monthly heat strip.
class PerformancePage extends ConsumerStatefulWidget {
  const PerformancePage({super.key});
  @override
  ConsumerState<PerformancePage> createState() => _PerformancePageState();
}

class _PerformancePageState extends ConsumerState<PerformancePage> {
  int months = 12, days = 20;
  @override
  Widget build(BuildContext context) {
    final c = context.vn;
    final d = ref.watch(getMapProvider('/admin/strategies/performance?months=$months&days=$days'));
    return Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
      const AdminHeader('Hiệu quả tín hiệu', subtitle: 'Kết quả thật của tín hiệu đã phát, sau phí và thuế. Dùng để chỉnh trọng số, bật tắt chiến lược và tính độ tin cậy hiện cho người dùng.'),
      Wrap(spacing: 12, runSpacing: 8, children: [
        Segmented<int>(options: const [(3, '3 tháng'), (12, '12 tháng'), (60, '5 năm')], value: months, onChanged: (v) => setState(() => months = v)),
        Segmented<int>(options: const [(10, '10 phiên'), (20, '20 phiên')], value: days, onChanged: (v) => setState(() => days = v)),
      ]),
      const SizedBox(height: 12),
      d.when(
        loading: () => const SkeletonList(),
        error: (e, _) => ErrorBox(e),
        data: (p) {
          final k = asMap(p['kpis']);
          final regimes = (p['regimes'] as List? ?? ['UP', 'PRESSURE', 'DOWN']).cast<String>();
          final strat = asList(p['by_strategy_regime']);
          final byRating = asList(p['by_rating']);
          final order = ['STRONG_BUY', 'BUY', 'HOLD', 'REDUCE', 'SELL'];
          byRating.sort((a, b) => order.indexOf(a['rating'].toString()).compareTo(order.indexOf(b['rating'].toString())));
          final monthly = asList(p['monthly']);
          final excess = asNum(k['excess_vs_index']);
          final heat = AppCard(
            padding: EdgeInsets.zero,
            child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
              Padding(padding: const EdgeInsets.fromLTRB(16, 14, 16, 4), child: Wrap(alignment: WrapAlignment.spaceBetween, crossAxisAlignment: WrapCrossAlignment.center, children: [
                Text('Tỷ lệ đúng theo chiến lược và trạng thái thị trường', style: Theme.of(context).textTheme.titleMedium),
                Text('Đây là nguồn của dòng "đúng 66% khi thị trường tăng (312 lần)" trên ứng dụng. Ô dưới 30 lần hiện mờ.', style: TextStyle(color: c.muted, fontSize: 12)),
              ])),
              if (strat.isEmpty) Padding(padding: const EdgeInsets.all(16), child: Text('Chưa có kết quả tín hiệu để đánh giá (cần tối thiểu $days phiên sau khi phát). Số liệu sẽ tích lũy theo thời gian.', style: TextStyle(color: c.muted))),
              if (strat.isNotEmpty)
                SingleChildScrollView(
                  scrollDirection: Axis.horizontal,
                  child: DataTable(
                    headingTextStyle: TextStyle(fontSize: 12.5, color: c.muted, fontWeight: FontWeight.w600),
                    columnSpacing: 22,
                    columns: [const DataColumn(label: Text('Chiến lược')), for (final r in regimes) DataColumn(label: Text(regime3Vi[r] ?? r)), const DataColumn(label: Text('Gợi ý'))],
                    rows: [
                      for (final e in strat)
                        DataRow(cells: [
                          DataCell(Column(mainAxisAlignment: MainAxisAlignment.center, crossAxisAlignment: CrossAxisAlignment.start, children: [Text('${e['name']}', style: const TextStyle(fontWeight: FontWeight.w600)), Text('${signalTypeVi[e['signal_type']] ?? ''} · ${horizonVi[e['horizon']] ?? ''}', style: TextStyle(fontSize: 11, color: c.faint))])),
                          for (final r in regimes)
                            DataCell(Builder(builder: (_) {
                              final x = asMap(asMap(e['cells'])[r]);
                              return HeatCell(winRate: asNum(x['win_rate']), samples: asInt(x['samples']) ?? 0, suffix: x['gated'] == true ? ' · tự tắt' : null);
                            })),
                          DataCell(Text(e['suggestion'].toString(), style: TextStyle(fontSize: 12.5, color: switch (e['suggestion'].toString()) { 'Hiệu quả ở mọi trạng thái' => c.up, 'Giữ nguyên' => c.up, 'Tắt khi thị trường giảm' => c.down, _ => e['suggestion'].toString().startsWith('Tự đứng ngoài') ? c.down : c.ref }))),
                        ]),
                    ],
                  ),
                ),
              Padding(padding: const EdgeInsets.fromLTRB(16, 6, 16, 12), child: Row(children: [for (final l in [(c.up, 'Từ 60%'), (c.ref, '50–59%'), (c.down, 'Dưới 50%: ứng dụng khuyên đứng ngoài')]) Padding(padding: const EdgeInsets.only(right: 14), child: Row(children: [Container(width: 12, height: 12, decoration: BoxDecoration(color: l.$1.withValues(alpha: 0.3), borderRadius: BorderRadius.circular(3))), const SizedBox(width: 5), Text(l.$2, style: TextStyle(fontSize: 11.5, color: c.muted))]))])),
            ]),
          );
          final ratingCard = AppCard(
            padding: EdgeInsets.zero,
            child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
              Padding(padding: const EdgeInsets.fromLTRB(16, 14, 16, 4), child: Text('Theo khuyến nghị', style: Theme.of(context).textTheme.titleMedium)),
              SingleChildScrollView(
                scrollDirection: Axis.horizontal,
                child: DataTable(
                  headingTextStyle: TextStyle(fontSize: 12.5, color: c.muted, fontWeight: FontWeight.w600),
                  columns: const [DataColumn(label: Text('Khuyến nghị')), DataColumn(label: Text('Số tín hiệu'), numeric: true), DataColumn(label: Text('Tỷ lệ đúng'), numeric: true), DataColumn(label: Text('Lợi nhuận TB'), numeric: true), DataColumn(label: Text('So với VN-Index'), numeric: true)],
                  rows: [
                    for (final r in byRating)
                      DataRow(cells: [
                        DataCell(cell(ratingVi[r['rating']] ?? r['rating'].toString(), bold: true)),
                        DataCell(cell(Fmt.price(asNum(r['samples'])))),
                        DataCell(cell('${Fmt.num_(asNum(r['win_rate']))}%', bold: true, color: winRateColor(c, asNum(r['win_rate'])))),
                        DataCell(cell(Fmt.pct(asNum(r['avg_return'])), color: c.changeColor(asNum(r['avg_return'])))),
                        DataCell(cell(r['excess'] != null ? '${Fmt.signed(asNum(r['excess']), decimals: 1)} điểm %' : '—', color: c.changeColor(asNum(r['excess'])))),
                      ]),
                  ],
                ),
              ),
              Padding(padding: const EdgeInsets.fromLTRB(16, 6, 16, 12), child: Text('Với Giảm tỷ trọng và Bán, "đúng" là giá giảm trong kỳ đo; lợi nhuận là phần lỗ tránh được.', style: TextStyle(color: c.faint, fontSize: 11.5))),
            ]),
          );
          final sectorCard = AppCard(
            padding: EdgeInsets.zero,
            child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
              Padding(padding: const EdgeInsets.fromLTRB(16, 14, 16, 4), child: Text('Theo ngành', style: Theme.of(context).textTheme.titleMedium)),
              SingleChildScrollView(
                scrollDirection: Axis.horizontal,
                child: DataTable(
                  headingTextStyle: TextStyle(fontSize: 12.5, color: c.muted, fontWeight: FontWeight.w600),
                  columns: const [DataColumn(label: Text('Ngành')), DataColumn(label: Text('Tín hiệu mua'), numeric: true), DataColumn(label: Text('Tỷ lệ đúng'), numeric: true)],
                  rows: [for (final r in asList(p['by_sector']).take(12)) DataRow(cells: [DataCell(cell(r['name'].toString())), DataCell(cell(Fmt.price(asNum(r['samples'])))), DataCell(cell('${Fmt.num_(asNum(r['win_rate']))}%', bold: true, color: winRateColor(c, asNum(r['win_rate']))))])],
                ),
              ),
              const SizedBox(height: 8),
            ]),
          );
          return Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
            LayoutBuilder(builder: (ctx, box) {
              final tw = box.maxWidth < 800 ? (box.maxWidth - 12) / 2 : (box.maxWidth - 36) / 4;
              return Wrap(spacing: 12, runSpacing: 12, children: [
                SizedBox(width: tw, child: KpiTile(label: 'Tín hiệu mua đã phát', value: Fmt.price(asNum(k['buy_signals'])), note: 'Mua mạnh và Tích lũy')),
                SizedBox(width: tw, child: KpiTile(label: 'Đạt chốt lời 1 trước cắt lỗ', value: k['tp1_rate'] != null ? '${Fmt.num_(asNum(k['tp1_rate']))}%' : '—', note: 'Mục tiêu từ ${k['target_tp1_rate']}%', valueColor: k['tp1_rate'] == null ? null : ((asNum(k['tp1_rate']) ?? 0) >= 55 ? c.up : c.ref))),
                SizedBox(width: tw, child: KpiTile(label: 'Lợi nhuận TB mỗi tín hiệu mua', value: Fmt.pct(asNum(k['avg_return'])), note: p['fee_note']?.toString() ?? 'Sau phí và thuế', valueColor: c.changeColor(asNum(k['avg_return'])))),
                SizedBox(width: tw, child: KpiTile(label: 'Vượt VN-Index trung bình', value: excess != null ? '${Fmt.signed(excess, decimals: 1)} điểm %' : '—', note: k['vnindex_return'] != null ? 'VN-Index cùng kỳ đo ${Fmt.pct(asNum(k['vnindex_return']))}' : 'Cùng kỳ đo', valueColor: c.changeColor(excess))),
              ]);
            }),
            const SizedBox(height: 16),
            if (context.isDesktop) Row(crossAxisAlignment: CrossAxisAlignment.start, children: [Expanded(flex: 5, child: ratingCard), const SizedBox(width: 16), Expanded(flex: 4, child: sectorCard)]) else ...[ratingCard, const SizedBox(height: 16), sectorCard],
            const SizedBox(height: 16),
            heat,
            const SizedBox(height: 16),
            const _AvoidedCard(),
            const SizedBox(height: 16),
            AppCard(child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
              Text('Bảng nhiệt theo tháng (tín hiệu mua)', style: Theme.of(context).textTheme.titleMedium),
              const SizedBox(height: 10),
              if (monthly.isEmpty) Text('Chưa có dữ liệu.', style: TextStyle(color: c.muted)),
              Wrap(spacing: 6, runSpacing: 6, children: [
                for (final m in monthly)
                  Tooltip(
                    message: '${m['month']}: ${m['samples']} tín hiệu · đúng ${Fmt.num_(asNum(m['win_rate']))}% · LN TB ${Fmt.pct(asNum(m['avg_return']))}${m['excess'] != null ? ' · so với VN-Index ${Fmt.signed(asNum(m['excess']), decimals: 1)} điểm %' : ''}',
                    child: Container(
                      width: 78, padding: const EdgeInsets.symmetric(vertical: 8),
                      decoration: BoxDecoration(color: winRateColor(c, asNum(m['win_rate'])).withValues(alpha: 0.08 + 0.3 * (((asNum(m['win_rate']) ?? 0) / 100).clamp(0.0, 1.0))), borderRadius: BorderRadius.circular(8)),
                      child: Column(children: [
                        Text(m['month'].toString().substring(2).replaceFirst('-', '/'), style: TextStyle(fontSize: 11, color: c.muted)),
                        Text('${Fmt.num_(asNum(m['win_rate']), decimals: 0)}%', style: TextStyle(fontWeight: FontWeight.w700, color: winRateColor(c, asNum(m['win_rate'])))),
                        Text('${m['samples']}', style: TextStyle(fontSize: 10.5, color: c.faint)),
                      ]),
                    ),
                  ),
              ]),
            ])),
            const SizedBox(height: 8),
            Text('Dữ liệu: GET /admin/strategies/performance · bảng signal_reliability', style: TextStyle(color: c.faint, fontSize: 11)),
          ]);
        },
      ),
    ]);
  }
}


/// "Rủi ro tránh được": what happened after RED checks, circuit breakers and stop breaches (system-wide, 180 days).
class _AvoidedCard extends ConsumerWidget {
  const _AvoidedCard();
  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final c = context.vn;
    final d = ref.watch(getMapProvider('/admin/risk-avoided?days=180'));
    return d.when(
      loading: () => const SkeletonCard(),
      error: (e, _) => ErrorBox(e),
      data: (a) {
        final b = asMap(a['red_blocked']), ov = asMap(a['red_overridden']), g = asMap(a['guard']), ss = asMap(a['stop_sold']), sh = asMap(a['stop_held']), dd = asMap(a['drawdown']);
        String ret(dynamic v) => v == null ? '—' : Fmt.pct(asNum(v), decimals: 1);
        return AppCard(child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
          Text('Rủi ro tránh được (toàn hệ thống, ${a['days']} ngày)', style: Theme.of(context).textTheme.titleMedium),
          Text('Điều gì đã xảy ra sau mỗi quyết định kỷ luật — bằng chứng cho triết lý "gợi ý ít rủi ro nhất". Giá đo sau ${a['hold_sessions']} phiên.', style: TextStyle(color: c.muted, fontSize: 12.5)),
          const SizedBox(height: 12),
          Wrap(spacing: 12, runSpacing: 12, children: [
            SizedBox(width: 230, child: KpiTile(label: 'Kiểm tra Đỏ đã chặn', value: '${b['n'] ?? 0} lệnh', note: b['n'] != null && (asInt(b['n']) ?? 0) > 0 ? 'mã sau đó TB ${ret(b['avg_return'])} · ${Fmt.num_(asNum(b['pct_fell']), decimals: 0)}% giảm · tránh ${Fmt.money(asNum(b['avoided_vnd']))}' : 'chưa có', valueColor: c.up)),
            SizedBox(width: 230, child: KpiTile(label: 'Vượt rào Đỏ', value: '${ov['n'] ?? 0} lần', note: (asInt(ov['n']) ?? 0) > 0 ? 'mã sau đó TB ${ret(ov['avg_return'])}' : 'không ai vượt rào', valueColor: (asInt(ov['n']) ?? 0) > 0 ? c.ref : c.up)),
            SizedBox(width: 230, child: KpiTile(label: 'Cầu dao bật', value: '${g['n'] ?? 0} lần', note: g['avg_index_during'] != null ? 'VN-Index trong lúc nghỉ TB ${ret(g['avg_index_during'])} · ${Fmt.num_(asNum(g['pct_index_fell']), decimals: 0)}% lần giảm' : 'chưa bật lần nào')),
            SizedBox(width: 230, child: KpiTile(label: 'Thủng cắt lỗ: bán / giữ', value: '${ss['n'] ?? 0} / ${sh['n'] ?? 0}', note: 'bán đúng hạn: mã sau đó ${ret(ss['avg_return'])} · giữ lại: ${ret(sh['avg_return'])}')),
            SizedBox(width: 230, child: KpiTile(label: 'Sụt giảm 90 ngày: người dùng vs VN-Index', value: dd['median_portfolio_mdd'] != null ? '${ret(dd['median_portfolio_mdd'])} / ${ret(dd['vnindex_mdd'])}' : '—', note: dd['users'] != null && (asInt(dd['users']) ?? 0) > 0 ? '${dd['users']} danh mục · ${Fmt.num_(asNum(dd['pct_better_than_index']), decimals: 0)}% tốt hơn chỉ số' : 'chưa có danh mục thật')),
          ]),
          const SizedBox(height: 10),
          Text(a['headline']?.toString() ?? '', style: TextStyle(color: c.text, fontSize: 13, height: 1.4)),
          if (asList(b['items']).isNotEmpty) ...[
            const SizedBox(height: 8),
            Text('Lệnh bị chặn, mã giảm mạnh nhất sau đó:', style: TextStyle(color: c.muted, fontSize: 12)),
            for (final it in asList(b['items']).take(5)) Text('${it['symbol']} ${Fmt.date(Fmt.parseDate(it['date']))}: ${ret(it['return_20'])} · ${(it['reasons'] as List? ?? []).join(', ')}', style: TextStyle(fontSize: 12, color: (asNum(it['return_20']) ?? 0) < 0 ? c.up : c.muted)),
          ],
        ]));
      },
    );
  }
}
