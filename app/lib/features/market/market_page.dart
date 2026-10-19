import 'package:flutter/material.dart';
import 'package:flutter_animate/flutter_animate.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:go_router/go_router.dart';

import '../../core/api.dart';
import '../../core/format.dart';
import '../../core/providers.dart';
import '../../core/responsive.dart';
import '../../core/theme.dart';
import '../stock/insights_widgets.dart';
import '../../shared/widgets/common.dart';
import '../../shared/widgets/score.dart';
import '../../shared/widgets/stock_rows.dart';
import '../ai/ai_panel.dart';
import '../pretrade/pretrade_sheet.dart';

final _overviewProvider = FutureProvider.autoDispose.family<Map<String, dynamic>, String>((ref, hz) async => asMap(await ref.watch(apiProvider).get('/market/overview', query: {'horizon': hz})));

class MarketPage extends ConsumerWidget {
  const MarketPage({super.key});

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final hz = ref.watch(horizonProvider);
    final data = ref.watch(_overviewProvider(hz));
    final c = context.vn;
    return RefreshIndicator(
      onRefresh: () async => ref.invalidate(_overviewProvider(hz)),
      child: data.when(
        loading: () => const PageBody(child: SkeletonList(count: 4)),
        error: (e, _) => PageBody(child: ErrorBox(e, onRetry: () => ref.invalidate(_overviewProvider(hz)))),
        data: (d) => PageBody(
          child: ListView(children: [
            _Headline(d).stagger(context, 0),
            SizedBox(height: context.gap),
            if (context.isDesktop)
              Row(crossAxisAlignment: CrossAxisAlignment.start, children: [
                Expanded(flex: 5, child: Column(children: [_Signals(d, hz).stagger(context, 1), SizedBox(height: context.gap), MarketNewsCard(items: asList(d['news'])).stagger(context, 2), SizedBox(height: context.gap), _Events(d).stagger(context, 3)])),
                SizedBox(width: context.gap),
                Expanded(flex: 3, child: Column(children: [if (d['coach'] != null) ...[_Coach(d['coach']).stagger(context, 1), SizedBox(height: context.gap)], const MarketFlowsCard().stagger(context, 2), SizedBox(height: context.gap), _Sectors(d).stagger(context, 2), SizedBox(height: context.gap), _RatingChanges(d).stagger(context, 3)])),
              ])
            else ...[
              if (d['coach'] != null) ...[_Coach(d['coach']).stagger(context, 1), SizedBox(height: context.gap)],
              _Signals(d, hz).stagger(context, 2),
              SizedBox(height: context.gap),
              const MarketFlowsCard().stagger(context, 3),
              SizedBox(height: context.gap),
              MarketNewsCard(items: asList(d['news'])).stagger(context, 3),
              SizedBox(height: context.gap),
              _Sectors(d).stagger(context, 3),
              SizedBox(height: context.gap),
              _RatingChanges(d).stagger(context, 4),
              SizedBox(height: context.gap),
              _Events(d).stagger(context, 5),
            ],
            const DisclaimerText(),
            Text(d['session']?.toString() ?? '', style: TextStyle(color: c.faint, fontSize: 11.5)),
          ]),
        ),
      ),
    );
  }
}

class _Headline extends ConsumerWidget {
  final Map<String, dynamic> d;
  const _Headline(this.d);
  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final c = context.vn;
    final regime = d['regime']?.toString();
    final word = regimeVi[regime] ?? '';
    final headline = d['headline']?.toString() ?? '';
    final br = asMap(d['breadth']);
    final big = context.isPhone ? 26.0 : 36.0;
    return AppCard(
      child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
        Row(children: [
          Expanded(child: Text('${d['date'] != null ? Fmt.date(Fmt.parseDate(d['date']), year: true) : ''} · ${d['session'] ?? ''}', style: TextStyle(color: c.faint, fontSize: 12))),
          if (context.isPhone) AskAiButton(compact: true, onPressed: () => openAi(context, {'screen': 'market'})),
        ]),
        const SizedBox(height: 6),
        RichText(text: TextSpan(style: TextStyle(fontSize: big, fontWeight: FontWeight.w700, color: c.text, height: 1.15), children: [
          const TextSpan(text: 'Thị trường đang '),
          TextSpan(text: word.isEmpty ? '…' : word, style: TextStyle(color: c.regimeColor(regime))),
        ])),
        const SizedBox(height: 10),
        Text(headline, style: TextStyle(fontSize: 15, color: c.muted, height: 1.4)),
        const SizedBox(height: 12),
        Wrap(spacing: 8, runSpacing: 8, children: [
          if (br['advances'] != null) _chip(context, 'Độ rộng', '${br['advances']} tăng · ${br['declines']} giảm', c.text),
          if (br['pct_above_ma50'] != null) _chip(context, 'Trên MA50', '${Fmt.num_(asNum(br['pct_above_ma50']), decimals: 0)}% mã', c.text),
          if (d['max_equity_pct'] != null) _chip(context, 'Tỷ trọng cổ phiếu tối đa', '${d['max_equity_pct']}%', c.regimeColor(regime)),
          if (br['liquidity_ratio'] != null) _chip(context, 'Thanh khoản', '${Fmt.num_(asNum(br['liquidity_ratio']), decimals: 2)}× TB20', c.text),
          if (br['distribution_days'] != null) _chip(context, 'Phiên phân phối', '${br['distribution_days']}/25', (asNum(br['distribution_days']) ?? 0) >= 5 ? c.downText : c.text),
        ]),
        if (context.isPhone) ...[
          const SizedBox(height: 12),
          Wrap(spacing: 14, runSpacing: 6, children: [
            for (final i in asList(d['indexes']))
              Row(mainAxisSize: MainAxisSize.min, children: [Text(i['label'].toString(), style: TextStyle(color: c.faint, fontSize: 12)), const SizedBox(width: 5), Text(Fmt.index(asNum(i['value'])), style: TextStyle(fontWeight: FontWeight.w700, color: c.changeColor(asNum(i['change_pct'])))), const SizedBox(width: 3), Text(Fmt.pct(asNum(i['change_pct'])), style: TextStyle(fontSize: 11.5, color: c.changeColor(asNum(i['change_pct']))))]),
          ]),
        ],
      ]),
    );
  }

  Widget _chip(BuildContext ctx, String label, String value, Color color) => Container(
        padding: const EdgeInsets.symmetric(horizontal: 10, vertical: 6),
        decoration: BoxDecoration(color: ctx.vn.surface2, borderRadius: BorderRadius.circular(8)),
        child: Row(mainAxisSize: MainAxisSize.min, children: [Text('$label  ', style: TextStyle(color: ctx.vn.faint, fontSize: 11.5)), Text(value, style: TextStyle(color: color, fontSize: 12.5, fontWeight: FontWeight.w700))]),
      );
}

class _Signals extends ConsumerWidget {
  final Map<String, dynamic> d;
  final String hz;
  const _Signals(this.d, this.hz);

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final c = context.vn;
    final sig = asMap(d['signals']);
    final buy = asList(sig['buy']), sell = asList(sig['sell']), watch = asList(sig['watch']);
    Widget section(String title, List<Map<String, dynamic>> rows, Color color, {bool showBuy = false}) {
      if (rows.isEmpty) return const SizedBox.shrink();
      return Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
        Padding(padding: const EdgeInsets.only(top: 12, bottom: 6), child: Row(children: [StatusDot(color), const SizedBox(width: 8), Text(title, style: TextStyle(fontWeight: FontWeight.w700, color: c.text)), const SizedBox(width: 6), Text('${rows.length}', style: TextStyle(color: c.faint))])),
        StockTable(
          rows: rows, subtitleKey: 'event', minWidth: 760,
          columns: const [StockCol('price', 'Giá (VNĐ)', width: 90, build: priceCell), StockCol('change_pct', '+/−', width: 70, build: changeCell), StockCol('trend3', 'N·T·D', width: 70, build: _trend), StockCol('score', 'Điểm', width: 110, build: _score), StockCol('rating', 'Khuyến nghị', width: 120, build: _rating), StockCol('risk', 'Rủi ro', width: 96, build: riskCell), StockCol('rel', 'Độ tin cậy', width: 110, build: _rel)],
          trailing: showBuy ? (ctx, r) => BuyButton(onPressed: () => showPretradeSheet(ctx, symbol: r['symbol'], horizon: hz)) : null,
        ),
      ]);
    }
    return AppCard(
      child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
        Row(children: [
          Expanded(child: Text('Tín hiệu hôm nay', style: Theme.of(context).textTheme.titleMedium)),
          Segmented<String>(options: const [('SHORT', 'Ngắn'), ('MID', 'Trung'), ('LONG', 'Dài')], value: hz, onChanged: (v) => ref.read(horizonProvider.notifier).set(v)),
        ]),
        if (buy.isEmpty && sell.isEmpty && watch.isEmpty)
          EmptyState(icon: Icons.radar, message: 'Chưa có tín hiệu ${horizonVi[hz]?.toLowerCase()} trong phiên gần nhất. Thị trường ${regimeVi[d['regime']] ?? ''} nên hệ thống hạn chế tín hiệu mua.', actionLabel: 'Xem cơ hội toàn thị trường', onAction: () => context.go('/watch?tab=market&hz=$hz')),
        section('Mua nổi bật', buy, c.up, showBuy: true),
        section('Bán / chốt lời', sell, c.down),
        section('Theo dõi', watch, c.ref),
        const SizedBox(height: 10),
        Row(children: [
          TextButton(onPressed: () => context.go('/watch?tab=market&hz=$hz'), child: const Text('Xem tất cả cơ hội →')),
          TextButton(onPressed: () => context.go('/screener?preset=HIGH_RISK'), child: const Text('Bộ lọc Nên tránh')),
        ]),
      ]),
    );
  }

  static Widget _trend(BuildContext ctx, Map<String, dynamic> r) => TrendChips(r['trend3']?.toString());
  static Widget _score(BuildContext ctx, Map<String, dynamic> r) => ScoreGauge(score: asNum(r['score']), compact: true);
  static Widget _rating(BuildContext ctx, Map<String, dynamic> r) => Align(alignment: Alignment.centerLeft, child: RatingChip(r['rating']?.toString()));
  static Widget _rel(BuildContext ctx, Map<String, dynamic> r) {
    final p = asNum(r['reliability_pct']);
    if (r['stand_aside'] == true) return Pill('Đứng ngoài', color: ctx.vn.down, fontSize: 10.5);
    if (p == null) return Text('chưa đủ mẫu', style: TextStyle(color: ctx.vn.faint, fontSize: 11.5));
    return Text('đúng ${Fmt.num_(p, decimals: 0)}% (${r['reliability_samples']})', style: TextStyle(color: ctx.vn.muted, fontSize: 12));
  }
}

class _Coach extends StatelessWidget {
  final dynamic coach;
  const _Coach(this.coach);
  @override
  Widget build(BuildContext context) {
    final c = context.vn;
    final m = asMap(coach);
    final b = asMap(m['benchmark']);
    Widget tile(String l, num? v) => Expanded(child: Container(padding: const EdgeInsets.all(8), decoration: BoxDecoration(color: c.surface2, borderRadius: BorderRadius.circular(8)), child: Column(children: [Text(l, style: TextStyle(color: c.faint, fontSize: 11)), Text(Fmt.pct(v), style: TextStyle(fontWeight: FontWeight.w700, color: c.changeColor(v)))])));
    return AppCard(
      child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
        Row(children: [Icon(Icons.sports, size: 18, color: c.ai), const SizedBox(width: 6), Text('Huấn luyện tuần', style: Theme.of(context).textTheme.titleMedium)]),
        const SizedBox(height: 10),
        Row(children: [tile('Danh mục', asNum(b['portfolio_pct'])), const SizedBox(width: 6), tile('VN-Index', asNum(b['vnindex_pct'])), const SizedBox(width: 6), tile('Tiết kiệm', asNum(b['savings_pct']))]),
        const SizedBox(height: 10),
        for (final i in asList(m['insights'])) Padding(padding: const EdgeInsets.only(bottom: 6), child: Row(crossAxisAlignment: CrossAxisAlignment.start, children: [Text('• ', style: TextStyle(color: c.ai)), Expanded(child: Text(i['text']?.toString() ?? '', style: const TextStyle(fontSize: 13)))])),
        if (m['rule'] != null) Padding(padding: const EdgeInsets.only(top: 4), child: Text('Quy tắc tuần tới: ${m['rule']}', style: TextStyle(color: c.ai, fontSize: 12.5, fontWeight: FontWeight.w600))),
        Align(alignment: Alignment.centerRight, child: TextButton(onPressed: () => context.push('/account/coach/${m['week_start']}'), child: const Text('Xem báo cáo →'))),
      ]),
    );
  }
}

class _Sectors extends StatelessWidget {
  final Map<String, dynamic> d;
  const _Sectors(this.d);
  @override
  Widget build(BuildContext context) {
    final c = context.vn;
    final rows = asList(d['sectors']);
    final top = rows.take(3).toList();
    return AppCard(
      child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
        Text('Nhóm ngành', style: Theme.of(context).textTheme.titleMedium),
        const SizedBox(height: 8),
        if (rows.isEmpty) Text('Chưa có điểm ngành.', style: TextStyle(color: c.muted)),
        for (final s in rows.take(10))
          InkWell(
            onTap: () => context.push('/screener?industry=${s['code']}'),
            child: Padding(
              padding: const EdgeInsets.symmetric(vertical: 5),
              child: Row(children: [
                SizedBox(width: 150, child: Text(s['name'].toString(), maxLines: 1, overflow: TextOverflow.ellipsis, style: const TextStyle(fontSize: 13))),
                Expanded(child: ClipRRect(borderRadius: BorderRadius.circular(3), child: TweenAnimationBuilder<double>(tween: Tween(begin: 0, end: (asNum(s['score']) ?? 0) / 100), duration: 700.ms, builder: (_, v, __) => LinearProgressIndicator(value: v, minHeight: 7, color: c.scoreColor(asNum(s['score'])), backgroundColor: c.surface2)))),
                const SizedBox(width: 8),
                SizedBox(width: 30, child: Text(Fmt.score(asNum(s['score'])), textAlign: TextAlign.right, style: const TextStyle(fontWeight: FontWeight.w700, fontSize: 12.5))),
                SizedBox(width: 56, child: Text(Fmt.pct(asNum(s['perf_1m']), decimals: 1), textAlign: TextAlign.right, style: TextStyle(fontSize: 12, color: c.changeColor(asNum(s['perf_1m']))))),
              ]),
            ),
          ),
        if (top.isNotEmpty) ...[
          const Divider(height: 20),
          Text('Ngành hưởng lợi', style: TextStyle(fontWeight: FontWeight.w700, color: c.text)),
          for (final s in top)
            Padding(
              padding: const EdgeInsets.only(top: 8),
              child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
                Text(s['name'].toString(), style: const TextStyle(fontWeight: FontWeight.w600, fontSize: 13)),
                if ((s['macro_note']?.toString() ?? '').isNotEmpty) Text(s['macro_note'].toString(), style: TextStyle(color: c.muted, fontSize: 12)),
                Wrap(spacing: 6, children: [for (final l in asList(s['leaders']).take(4)) ActionChip(label: Text('${l['symbol']} · ${Fmt.score(asNum(l['score']))}', style: const TextStyle(fontSize: 11.5)), onPressed: () => context.push('/stocks/${l['symbol']}'), visualDensity: VisualDensity.compact)]),
              ]),
            ),
        ],
      ]),
    );
  }
}

class _RatingChanges extends StatelessWidget {
  final Map<String, dynamic> d;
  const _RatingChanges(this.d);
  @override
  Widget build(BuildContext context) {
    final rows = asList(d['rating_changes']);
    if (rows.isEmpty) return const SizedBox.shrink();
    final c = context.vn;
    return AppCard(
      child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
        Text('${rows.length} mã bạn theo dõi đổi khuyến nghị hôm nay', style: Theme.of(context).textTheme.titleMedium),
        const SizedBox(height: 8),
        for (final r in rows) ListTile(dense: true, contentPadding: EdgeInsets.zero, title: Text(r['symbol'].toString(), style: const TextStyle(fontWeight: FontWeight.w700)), subtitle: Text('${r['from']} → ${r['to']}', style: TextStyle(color: c.muted)), trailing: const Icon(Icons.chevron_right), onTap: () => context.push('/stocks/${r['symbol']}')),
      ]),
    );
  }
}

class _Events extends StatelessWidget {
  final Map<String, dynamic> d;
  const _Events(this.d);
  @override
  Widget build(BuildContext context) {
    final c = context.vn;
    final rows = asList(d['events']);
    return AppCard(
      child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
        Text('Sự kiện tuần', style: Theme.of(context).textTheme.titleMedium),
        const SizedBox(height: 8),
        if (rows.isEmpty) Text('Không có cổ tức, phát hành hay ĐHCĐ của mã thanh khoản cao trong 7 ngày tới.', style: TextStyle(color: c.muted, fontSize: 13)),
        for (final e in rows)
          ListTile(
            dense: true, contentPadding: EdgeInsets.zero, onTap: () => context.push('/stocks/${e['symbol']}'),
            leading: Text(Fmt.date(Fmt.parseDate(e['date'])), style: TextStyle(color: c.faint)),
            title: Text('${e['symbol']} · ${e['kind_vi'] ?? e['title'] ?? e['kind']}', style: const TextStyle(fontWeight: FontWeight.w600)),
            subtitle: (e['note'] ?? '').toString().isEmpty ? null : Text(e['note'].toString(), maxLines: 1, overflow: TextOverflow.ellipsis, style: TextStyle(color: c.muted, fontSize: 12)),
          ),
      ]),
    );
  }
}
