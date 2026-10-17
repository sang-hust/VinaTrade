import 'package:fl_chart/fl_chart.dart';
import 'package:flutter/material.dart';
import 'package:flutter_animate/flutter_animate.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:go_router/go_router.dart';
import 'package:url_launcher/url_launcher.dart';

import '../../core/api.dart';
import '../../core/format.dart';
import '../../core/providers.dart';
import '../../core/responsive.dart';
import '../../core/theme.dart';
import '../../shared/widgets/common.dart';

/// Sentiment chip for a news item or a 7-day average (−1..1).
class SentimentPill extends StatelessWidget {
  final num? score;
  final String? label;
  const SentimentPill({super.key, this.score, this.label});
  @override
  Widget build(BuildContext context) {
    final c = context.vn;
    final l = label ?? (score == null ? null : (score! >= 0.25 ? 'POSITIVE' : (score! <= -0.25 ? 'NEGATIVE' : 'NEUTRAL')));
    if (l == null) return const SizedBox.shrink();
    final (text, color, icon) = switch (l) {
      'POSITIVE' => ('Tích cực', c.upText, Icons.trending_up),
      'NEGATIVE' => ('Tiêu cực', c.downText, Icons.trending_down),
      _ => ('Trung tính', c.muted, Icons.remove),
    };
    return Pill(text, color: color, icon: icon, fontSize: 11);
  }
}

Future<void> openUrl(String? url) async {
  if (url == null || url.isEmpty) return;
  final u = Uri.tryParse(url);
  if (u != null) await launchUrl(u, mode: LaunchMode.externalApplication);
}

/// List of news items (from /news or the analysis payload).
class NewsList extends StatelessWidget {
  final List<Map<String, dynamic>> items;
  final bool showSymbols;
  final int? max;
  const NewsList({super.key, required this.items, this.showSymbols = false, this.max});
  @override
  Widget build(BuildContext context) {
    final c = context.vn;
    if (items.isEmpty) return Padding(padding: const EdgeInsets.all(8), child: Text('Chưa có tin nào trong 120 ngày qua.', style: TextStyle(color: c.muted)));
    final list = max != null ? items.take(max!).toList() : items;
    return Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
      for (var i = 0; i < list.length; i++)
        InkWell(
          borderRadius: BorderRadius.circular(8),
          onTap: () => openUrl(list[i]['url']?.toString()),
          child: Padding(
            padding: const EdgeInsets.symmetric(vertical: 8, horizontal: 4),
            child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
              Text(list[i]['title'].toString(), maxLines: 2, overflow: TextOverflow.ellipsis, style: TextStyle(fontWeight: FontWeight.w600, fontSize: 13.5, color: c.text)),
              if ((list[i]['summary'] ?? '').toString().isNotEmpty)
                Padding(padding: const EdgeInsets.only(top: 3), child: Text(list[i]['summary'].toString(), maxLines: 2, overflow: TextOverflow.ellipsis, style: TextStyle(color: c.muted, fontSize: 12.5))),
              const SizedBox(height: 4),
              Wrap(spacing: 8, runSpacing: 4, crossAxisAlignment: WrapCrossAlignment.center, children: [
                Text('${list[i]['source']} · ${Fmt.relative(Fmt.parseDate(list[i]['published_at']))}', style: TextStyle(color: c.faint, fontSize: 11.5)),
                SentimentPill(label: list[i]['sentiment_label']?.toString()),
                if (showSymbols)
                  for (final s in ((list[i]['symbols'] as List?) ?? const []).take(4))
                    InkWell(onTap: () => context.push('/stocks/$s'), child: Text(s.toString(), style: TextStyle(color: c.link, fontWeight: FontWeight.w700, fontSize: 12))),
              ]),
            ]),
          ),
        ).animate().fadeIn(delay: (i * 40).ms, duration: 250.ms).slideY(begin: 0.06, end: 0),
      Text('Bấm để mở bài gốc. Tóm tắt và đánh giá cảm xúc do AI tạo từ tiêu đề, chỉ để tham khảo.', style: TextStyle(color: c.faint, fontSize: 11)),
    ]);
  }
}

/// Net flow bar chart (green buy, red sell) over the last N sessions.
class FlowBars extends StatelessWidget {
  final List<Map<String, dynamic>> series;
  final String field;
  const FlowBars({super.key, required this.series, this.field = 'foreign_net'});
  @override
  Widget build(BuildContext context) {
    final c = context.vn;
    final pts = series.where((e) => e[field] != null).toList();
    if (pts.isEmpty) return const SizedBox.shrink();
    final maxAbs = pts.map((e) => (asNum(e[field]) ?? 0).abs()).fold<num>(1, (a, b) => a > b ? a : b);
    return SizedBox(
      height: 120,
      child: BarChart(
        BarChartData(
          maxY: maxAbs.toDouble() * 1.1,
          minY: -maxAbs.toDouble() * 1.1,
          gridData: FlGridData(show: true, drawVerticalLine: false, horizontalInterval: maxAbs.toDouble(), getDrawingHorizontalLine: (_) => FlLine(color: c.line, strokeWidth: 0.6)),
          borderData: FlBorderData(show: false),
          titlesData: const FlTitlesData(show: false),
          barTouchData: BarTouchData(
            touchTooltipData: BarTouchTooltipData(
              getTooltipColor: (_) => c.surface2,
              getTooltipItem: (g, _, rod, __) => BarTooltipItem('${Fmt.date(Fmt.parseDate(pts[g.x]['date']))}\n${Fmt.money(rod.toY, full: false)}', TextStyle(color: c.text, fontSize: 11)),
            ),
          ),
          barGroups: [
            for (var i = 0; i < pts.length; i++)
              BarChartGroupData(x: i, barRods: [
                BarChartRodData(toY: (asNum(pts[i][field]) ?? 0).toDouble(), width: 6, borderRadius: BorderRadius.circular(2), color: (asNum(pts[i][field]) ?? 0) >= 0 ? c.up : c.down),
              ]),
          ],
        ),
        duration: context.reduceMotion ? Duration.zero : 600.ms,
      ),
    );
  }
}

Widget _kv(BuildContext context, String k, String v, {Color? color}) => Padding(
      padding: const EdgeInsets.symmetric(vertical: 4),
      child: Row(children: [Expanded(child: Text(k, style: TextStyle(color: context.vn.muted, fontSize: 13))), Text(v, style: TextStyle(fontWeight: FontWeight.w600, fontSize: 13, color: color))]),
    );

String signedMoney(num? v) => v == null ? Fmt.dash : '${v >= 0 ? '+' : '−'}${Fmt.money(v.abs())}';

/// Tab "Dòng tiền & nội bộ": foreign/proprietary flows, insider deals, broker consensus.
class FlowsInsidersPanel extends ConsumerWidget {
  final String symbol;
  final Map<String, dynamic> d;
  const FlowsInsidersPanel({super.key, required this.symbol, required this.d});
  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final c = context.vn;
    final f = asMap(d['flows']);
    final ins = asMap(d['insiders']);
    final cons = asMap(d['consensus']);
    final flows = ref.watch(getMapProvider('/stocks/$symbol/flows?days=30'));
    Color? col(num? v) => v == null ? null : c.changeColor(v);
    return Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
      Text('Khối ngoại & tự doanh', style: TextStyle(fontWeight: FontWeight.w700, color: c.text)),
      Wrap(spacing: 24, runSpacing: 0, children: [
        SizedBox(width: 300, child: Column(children: [
          _kv(context, 'Khối ngoại hôm nay', signedMoney(asNum(f['foreign_net_today'])), color: col(asNum(f['foreign_net_today']))),
          _kv(context, 'Khối ngoại 5 phiên', signedMoney(asNum(f['foreign_net_5d'])), color: col(asNum(f['foreign_net_5d']))),
          _kv(context, 'Khối ngoại 20 phiên', signedMoney(asNum(f['foreign_net_20d'])), color: col(asNum(f['foreign_net_20d']))),
        ])),
        SizedBox(width: 300, child: Column(children: [
          _kv(context, 'Tự doanh 5 phiên', signedMoney(asNum(f['prop_net_5d'])), color: col(asNum(f['prop_net_5d']))),
          _kv(context, 'Room ngoại còn lại', f['foreign_room_pct'] == null ? Fmt.dash : '${Fmt.num_(asNum(f['foreign_room_pct']))}% số CP'),
        ])),
      ]),
      flows.when(
        loading: () => const Skeleton(height: 110),
        error: (_, __) => const SizedBox.shrink(),
        data: (x) => Padding(padding: const EdgeInsets.only(top: 6), child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
          Text('Khối ngoại mua/bán ròng 30 phiên', style: TextStyle(color: c.faint, fontSize: 11.5)),
          FlowBars(series: asList(x['series'])),
        ])),
      ),
      const SizedBox(height: 14),
      Row(children: [
        Expanded(child: Text('Giao dịch nội bộ', style: TextStyle(fontWeight: FontWeight.w700, color: c.text))),
        if (ins['net_90d'] != null) Text('Ròng 90 ngày ${signedMoney(asNum(ins['net_90d']))}', style: TextStyle(fontSize: 12.5, fontWeight: FontWeight.w600, color: col(asNum(ins['net_90d'])))),
      ]),
      if ((asNum(ins['pending_sell_shares']) ?? 0) > 0)
        Padding(padding: const EdgeInsets.only(top: 4), child: Pill('Đang đăng ký bán ${Fmt.qty(asNum(ins['pending_sell_shares']))} cp', color: c.downText, icon: Icons.warning_amber_rounded)),
      if (asList(ins['items']).isEmpty) Padding(padding: const EdgeInsets.only(top: 4), child: Text('Chưa có giao dịch nội bộ được công bố.', style: TextStyle(color: c.muted, fontSize: 13))),
      for (final i in asList(ins['items']))
        Padding(
          padding: const EdgeInsets.symmetric(vertical: 5),
          child: Row(crossAxisAlignment: CrossAxisAlignment.start, children: [
            Pill(i['side_vi'].toString(), color: i['side'] == 'BUY' ? c.upText : c.downText, fontSize: 11),
            const SizedBox(width: 8),
            Expanded(child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
              Text('${i['person'] ?? '—'} · ${Fmt.qty(asNum(i['quantity_done'] ?? i['quantity']))} cp', style: const TextStyle(fontSize: 13, fontWeight: FontWeight.w600)),
              Text([i['relation'], i['status_vi'], Fmt.date(Fmt.parseDate(i['announce_date']), year: true), if (i['value_est'] != null) '≈ ${Fmt.money(asNum(i['value_est']))}'].where((e) => e != null && e.toString().isNotEmpty).join(' · '),
                  style: TextStyle(color: c.muted, fontSize: 12)),
            ])),
          ]),
        ),
      const SizedBox(height: 14),
      Row(children: [
        Expanded(child: Text('Khuyến nghị công ty chứng khoán', style: TextStyle(fontWeight: FontWeight.w700, color: c.text))),
        if (cons['target'] != null) Text('TB ${Fmt.price(asNum(cons['target']))} (${Fmt.pct(asNum(cons['upside_pct']), decimals: 0)})', style: TextStyle(fontSize: 12.5, fontWeight: FontWeight.w600, color: col(asNum(cons['upside_pct'])))),
      ]),
      if (asList(cons['items']).isEmpty) Padding(padding: const EdgeInsets.only(top: 4), child: Text('Chưa có báo cáo khuyến nghị trong dữ liệu.', style: TextStyle(color: c.muted, fontSize: 13))),
      for (final r in asList(cons['items']))
        _kv(context, '${r['firm']} · ${Fmt.date(Fmt.parseDate(r['report_date']), year: true)}', '${r['rec_type'] ?? ''} ${Fmt.price(asNum(r['target_price']))}'),
      Padding(padding: const EdgeInsets.only(top: 6), child: Text('Nguồn: VNDirect (khối ngoại, tự doanh, khuyến nghị), Vietcap (giao dịch nội bộ).', style: TextStyle(color: c.faint, fontSize: 11))),
    ]);
  }
}

const _eventIcon = {
  'CASH_DIVIDEND': Icons.payments_outlined, 'STOCK_DIVIDEND': Icons.card_giftcard, 'BONUS': Icons.card_giftcard, 'ISSUE': Icons.add_chart, 'AGM': Icons.groups_outlined,
  'AGM_RECORD': Icons.how_to_vote_outlined, 'POLL': Icons.how_to_vote_outlined,
};

/// Tab "Sự kiện": upcoming rights, recent events, exchange alerts.
class EventsPanel extends ConsumerWidget {
  final String symbol;
  const EventsPanel({super.key, required this.symbol});
  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final c = context.vn;
    final ev = ref.watch(getMapProvider('/stocks/$symbol/corporate-events'));
    Widget item(Map<String, dynamic> e, {bool upcoming = false}) => Padding(
          padding: const EdgeInsets.symmetric(vertical: 5),
          child: Row(crossAxisAlignment: CrossAxisAlignment.start, children: [
            Icon(e['is_alert'] == true ? Icons.report_gmailerrorred : (_eventIcon[e['kind']] ?? Icons.event), size: 18, color: e['is_alert'] == true ? c.downText : (upcoming ? c.link : c.muted)),
            const SizedBox(width: 8),
            Expanded(child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
              Text('${e['kind_vi']} · ${Fmt.date(Fmt.parseDate(e['date']), year: true)}', style: TextStyle(fontWeight: FontWeight.w600, fontSize: 13, color: e['is_alert'] == true ? c.downText : c.text)),
              if ((e['note'] ?? '').toString().isNotEmpty) Text(e['note'].toString(), maxLines: 3, overflow: TextOverflow.ellipsis, style: TextStyle(color: c.muted, fontSize: 12)),
            ])),
          ]),
        );
    return ev.when(
      loading: () => const Skeleton(height: 90),
      error: (e, _) => ErrorBox(e),
      data: (x) => Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
        Text('Sắp tới', style: TextStyle(fontWeight: FontWeight.w700, color: c.text)),
        if (asList(x['upcoming']).isEmpty) Padding(padding: const EdgeInsets.only(top: 4), child: Text('Không có sự kiện quyền sắp tới.', style: TextStyle(color: c.muted, fontSize: 13))),
        for (final e in asList(x['upcoming'])) item(e, upcoming: true),
        if (asList(x['alerts']).isNotEmpty) ...[
          const SizedBox(height: 10),
          Text('Diện cảnh báo / kiểm soát', style: TextStyle(fontWeight: FontWeight.w700, color: c.downText)),
          for (final e in asList(x['alerts'])) item(e),
        ],
        const SizedBox(height: 10),
        Text('Gần đây', style: TextStyle(fontWeight: FontWeight.w700, color: c.text)),
        for (final e in asList(x['recent']).where((e) => e['is_alert'] != true).take(10)) item(e),
        Padding(padding: const EdgeInsets.only(top: 6), child: Text('Ngày ghi là ngày giao dịch không hưởng quyền (GDKHQ) hoặc ngày họp. Nguồn: VNDirect.', style: TextStyle(color: c.faint, fontSize: 11))),
      ]),
    );
  }
}

/// Chip for the next corporate event on the recommendation card.
class NextEventChip extends StatelessWidget {
  final Map<String, dynamic>? ev;
  const NextEventChip({super.key, this.ev});
  @override
  Widget build(BuildContext context) {
    if (ev == null || ev!.isEmpty || ev!['date'] == null) return const SizedBox.shrink();
    final d = Fmt.parseDate(ev!['date']);
    final days = d == null ? null : d.difference(DateTime.now()).inDays + 1;
    final soon = days != null && days <= 7;
    return Pill('${ev!['title'] ?? 'Sự kiện'} ${Fmt.date(d)}${days != null && days >= 0 ? ' (còn $days ngày)' : ''}', color: soon ? context.vn.ref : context.vn.muted, icon: Icons.event, fontSize: 11.5);
  }
}

/// Market screen card: foreign/proprietary net today + top net buy/sell.
class MarketFlowsCard extends ConsumerWidget {
  const MarketFlowsCard({super.key});
  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final c = context.vn;
    final x = ref.watch(getMapProvider('/market/flows?top=5'));
    return AppCard(
      child: x.when(
        loading: () => const Skeleton(height: 140),
        error: (e, _) => ErrorBox(e),
        data: (m) => Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
          Row(children: [
            Expanded(child: Text('Khối ngoại & tự doanh', style: Theme.of(context).textTheme.titleMedium)),
            if (m['date'] != null) Text(Fmt.date(Fmt.parseDate(m['date'])), style: TextStyle(color: c.faint, fontSize: 12)),
          ]),
          const SizedBox(height: 6),
          Wrap(spacing: 16, runSpacing: 4, children: [
            Text('Khối ngoại ${signedMoney(asNum(m['foreign_net']))}', style: TextStyle(fontWeight: FontWeight.w700, color: c.changeColor(asNum(m['foreign_net'])))),
            Text('Tự doanh ${signedMoney(asNum(m['prop_net']))}', style: TextStyle(fontWeight: FontWeight.w700, color: c.changeColor(asNum(m['prop_net'])))),
          ]),
          FlowBars(series: asList(m['series'])),
          Row(crossAxisAlignment: CrossAxisAlignment.start, children: [
            Expanded(child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
              Text('Mua ròng nhiều nhất', style: TextStyle(color: c.faint, fontSize: 11.5)),
              for (final r in asList(m['top_buy']))
                InkWell(onTap: () => context.push('/stocks/${r['symbol']}'), child: Padding(padding: const EdgeInsets.symmetric(vertical: 2), child: Text('${r['symbol']}  ${signedMoney(asNum(r['foreign_net']))}', style: TextStyle(color: c.upText, fontSize: 12.5, fontWeight: FontWeight.w600)))),
            ])),
            Expanded(child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
              Text('Bán ròng nhiều nhất', style: TextStyle(color: c.faint, fontSize: 11.5)),
              for (final r in asList(m['top_sell']))
                InkWell(onTap: () => context.push('/stocks/${r['symbol']}'), child: Padding(padding: const EdgeInsets.symmetric(vertical: 2), child: Text('${r['symbol']}  ${signedMoney(asNum(r['foreign_net']))}', style: TextStyle(color: c.downText, fontSize: 12.5, fontWeight: FontWeight.w600)))),
            ])),
          ]),
        ]),
      ),
    );
  }
}

/// Market screen card: latest market news.
class MarketNewsCard extends StatelessWidget {
  final List<Map<String, dynamic>> items;
  const MarketNewsCard({super.key, required this.items});
  @override
  Widget build(BuildContext context) => AppCard(
        child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
          Text('Tin thị trường', style: Theme.of(context).textTheme.titleMedium),
          const SizedBox(height: 4),
          NewsList(items: items, showSymbols: true, max: 6),
        ]),
      );
}
