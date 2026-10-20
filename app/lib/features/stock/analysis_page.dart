import 'package:flutter/material.dart';
import 'package:flutter_animate/flutter_animate.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:go_router/go_router.dart';

import '../../core/api.dart';
import '../../core/format.dart';
import '../../core/providers.dart';
import '../../core/responsive.dart';
import '../../core/session.dart';
import '../../core/theme.dart';
import '../../core/ws.dart';
import '../../shared/widgets/candle_chart.dart';
import '../../shared/widgets/common.dart';
import '../../shared/widgets/score.dart';
import '../ai/ai_panel.dart';
import '../alerts/alerts_page.dart' show showRuleEditor;
import '../pretrade/pretrade_sheet.dart';
import '../shell/app_shell.dart' show showSymbolSearch;
import 'insights_widgets.dart';

final _analysisProvider = FutureProvider.autoDispose.family<Map<String, dynamic>, (String, String?)>((ref, k) async => asMap(await ref.watch(apiProvider).get('/stocks/${k.$1}/analysis', query: {if (k.$2 != null) 'horizon': k.$2})));
final _candlesProvider = FutureProvider.autoDispose.family<Map<String, dynamic>, (String, String)>((ref, k) async => asMap(await ref.watch(apiProvider).get('/stocks/${k.$1}/candles', query: {'tf': k.$2, 'days': k.$2 == '1d' ? 300 : 400})));

/// "/analysis" with no symbol: search prompt.
class AnalysisLanding extends StatelessWidget {
  const AnalysisLanding({super.key});
  @override
  Widget build(BuildContext context) => Center(child: EmptyState(icon: Icons.query_stats, message: 'Chọn một mã để xem phân tích', actionLabel: 'Tìm mã', onAction: () => showSymbolSearch(context)));
}

class AnalysisPage extends ConsumerStatefulWidget {
  final String symbol;
  final String? horizon;
  const AnalysisPage({super.key, required this.symbol, this.horizon});
  @override
  ConsumerState<AnalysisPage> createState() => _AnalysisPageState();
}

class _AnalysisPageState extends ConsumerState<AnalysisPage> {
  String? hz;
  String tf = '1d';

  @override
  void initState() {
    super.initState();
    hz = widget.horizon;
    WidgetsBinding.instance.addPostFrameCallback((_) => ref.read(realtimeProvider.notifier).subscribe(['quotes:${widget.symbol}']));
  }

  @override
  Widget build(BuildContext context) {
    final session = ref.watch(sessionProvider);
    final key = (widget.symbol, hz);
    final data = ref.watch(_analysisProvider(key));
    final c = context.vn;
    return data.when(
      loading: () => const PageBody(child: SkeletonList(count: 3)),
      error: (e, _) => PageBody(child: Column(children: [ErrorBox(e, onRetry: () => ref.invalidate(_analysisProvider(key))), const SizedBox(height: 12), OutlinedButton(onPressed: () => showSymbolSearch(context), child: const Text('Tìm mã khác'))])),
      data: (d) {
        final level = session.uiDetail;
        final live = ref.watch(realtimeProvider.select((s) => s.quotes[widget.symbol]));
        if (live != null && live['p'] != null) {
          d = {...d, 'price': live['p'], 'change': live['chg'], 'change_pct': live['chg_pct']};
        }
        final card = _RecommendationCard(d: d, level: level, onLevel: (v) => ref.read(sessionProvider.notifier).updateSettings({'ui_detail': v}), onHorizon: (v) => setState(() => hz = v));
        final riskCard = _RiskCard(d: d);
        final chart = _ChartSection(d: d, symbol: widget.symbol, tf: tf, onTf: (v) => setState(() => tf = v), level: level);
        final details = _Details(d: d, level: level, symbol: widget.symbol);
        return RefreshIndicator(
          onRefresh: () async => ref.invalidate(_analysisProvider(key)),
          child: PageBody(
            child: ListView(children: [
              _Header(d: d).stagger(context, 0),
              SizedBox(height: context.gap),
              if (context.isDesktop)
                Row(crossAxisAlignment: CrossAxisAlignment.start, children: [
                  Expanded(flex: 5, child: Column(children: [chart.stagger(context, 1), SizedBox(height: context.gap), details.stagger(context, 2)])),
                  SizedBox(width: context.gap),
                  SizedBox(width: context.isWide ? 400 : 360, child: Column(children: [card.stagger(context, 1), SizedBox(height: context.gap), riskCard.stagger(context, 2)])),
                ])
              else ...[card.stagger(context, 1), SizedBox(height: context.gap), riskCard.stagger(context, 2), SizedBox(height: context.gap), chart.stagger(context, 3), SizedBox(height: context.gap), details.stagger(context, 4)],
              const DisclaimerText(),
              Text('Số liệu phiên ${d['date'] != null ? Fmt.date(Fmt.parseDate(d['date']), year: true) : '—'}', style: TextStyle(color: c.faint, fontSize: 11.5)),
            ]),
          ),
        );
      },
    );
  }
}

class _Header extends ConsumerWidget {
  final Map<String, dynamic> d;
  const _Header({required this.d});
  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final c = context.vn;
    final price = asNum(d['price']);
    final priceColor = c.priceColor(price, asNum(d['ref_price']), asNum(d['ceiling']), asNum(d['floor']));
    final inWl = asList(d['watchlists']);
    final sym = d['symbol'].toString();
    return AppCard(
      child: Wrap(crossAxisAlignment: WrapCrossAlignment.center, spacing: 20, runSpacing: 12, children: [
        Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
          Text('${d['exchange']} · ${d['industry'] ?? '—'}${d['in_vn30'] == true ? ' · VN30' : ''}', style: TextStyle(color: c.faint, fontSize: 12)),
          Row(children: [
            Hero(tag: 'sym-$sym', child: Material(color: Colors.transparent, child: Text(sym, style: TextStyle(fontSize: 28, fontWeight: FontWeight.w800, color: c.text)))),
            const SizedBox(width: 10),
            Flexible(child: Text(d['name_full']?.toString() ?? '', maxLines: 1, overflow: TextOverflow.ellipsis, style: TextStyle(color: c.muted, fontSize: 14))),
          ]),
          for (final f in (d['status_flags'] as List? ?? [])) Pill({'WARNING': 'Cảnh báo', 'CONTROL': 'Kiểm soát', 'RESTRICTED': 'Hạn chế GD', 'SUSPENDED': 'Đình chỉ'}[f] ?? f.toString(), color: c.down),
        ]),
        Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
          PriceFlash(price: price, child: Text(Fmt.priceVnd(price), style: TextStyle(fontSize: context.isPhone ? 30 : 34, fontWeight: FontWeight.w700, color: priceColor, fontFeatures: const [FontFeature.tabularFigures()]))),
          Wrap(crossAxisAlignment: WrapCrossAlignment.center, spacing: 10, runSpacing: 2, children: [
            Text(Fmt.change(asNum(d['change']), asNum(d['change_pct'])), style: TextStyle(color: c.changeColor(asNum(d['change_pct'])), fontWeight: FontWeight.w600, fontSize: 15)),
            Row(mainAxisSize: MainAxisSize.min, children: [Text('TC ', style: TextStyle(color: c.faint, fontSize: 12)), Text(Fmt.price(asNum(d['ref_price'])), style: TextStyle(color: c.ref, fontSize: 12.5, fontWeight: FontWeight.w600))]),
            Row(mainAxisSize: MainAxisSize.min, children: [Text('Trần ', style: TextStyle(color: c.faint, fontSize: 12)), Text(Fmt.price(asNum(d['ceiling'])), style: TextStyle(color: c.ceil, fontSize: 12.5, fontWeight: FontWeight.w600))]),
            Row(mainAxisSize: MainAxisSize.min, children: [Text('Sàn ', style: TextStyle(color: c.faint, fontSize: 12)), Text(Fmt.price(asNum(d['floor'])), style: TextStyle(color: c.floor, fontSize: 12.5, fontWeight: FontWeight.w600))]),
          ]),
          Text('KL ${Fmt.volume(asNum(d['volume']))} · GTGD ${Fmt.money(asNum(d['value']))} · 52T ${Fmt.price(asNum(d['low_52w']))}–${Fmt.price(asNum(d['high_52w']))}', style: TextStyle(color: c.muted, fontSize: 12)),
        ]),
        Wrap(spacing: 8, runSpacing: 8, children: [
          OutlinedButton.icon(
            onPressed: () async {
              final api = ref.read(apiProvider);
              try {
                if (inWl.isNotEmpty) {
                  await api.delete('/watchlists/${inWl.first['id']}/items/$sym');
                  if (context.mounted) showToast(context, 'Đã bỏ $sym khỏi “${inWl.first['name']}”');
                } else {
                  await api.post('/watchlists/quick-add', data: {'symbol': sym});
                  if (context.mounted) showToast(context, 'Đã thêm $sym vào danh sách theo dõi');
                }
                ref.invalidate(_analysisProvider);
              } on ApiException catch (e) {
                if (context.mounted) showToast(context, e.message, error: true);
              }
            },
            icon: Icon(inWl.isNotEmpty ? Icons.visibility : Icons.visibility_outlined, size: 18),
            label: Text(inWl.isNotEmpty ? 'Đang theo dõi' : 'Theo dõi'),
          ),
          OutlinedButton.icon(onPressed: () => showRuleEditor(context, symbol: sym), icon: const Icon(Icons.notifications_none, size: 18), label: const Text('Đặt cảnh báo')),
          AskAiButton(label: 'Hỏi AI về $sym', onPressed: () => openAi(context, {'symbol': sym, 'screen': 'stock'})),
        ]),
      ]),
    );
  }
}

class _RecommendationCard extends StatelessWidget {
  final Map<String, dynamic> d;
  final String level;
  final ValueChanged<String> onLevel, onHorizon;
  const _RecommendationCard({required this.d, required this.level, required this.onLevel, required this.onHorizon});

  @override
  Widget build(BuildContext context) {
    final c = context.vn;
    final rating = d['rating']?.toString();
    final plan = asMap(d['plan']);
    final rel = asMap(d['reliability']);
    final risk = asMap(d['company_risk']);
    final hz = d['horizon']?.toString() ?? 'MID';
    final entry = plan['entry'] as List? ?? [];
    final tp = plan['take_profit'] as List? ?? [];
    final sym = d['symbol'].toString();
    return AppCard(
      borderColor: c.ratingColor(rating).withValues(alpha: 0.5),
      child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
        Row(children: [
          Expanded(child: Segmented<String>(options: const [('SHORT', 'Ngắn'), ('MID', 'Trung'), ('LONG', 'Dài')], value: hz, onChanged: onHorizon)),
          const SizedBox(width: 8),
          PopupMenuButton<String>(
            tooltip: 'Mức chi tiết',
            onSelected: onLevel,
            itemBuilder: (_) => [for (final e in const [('SIMPLE', 'Đơn giản'), ('STANDARD', 'Vừa đủ'), ('FULL', 'Đầy đủ')]) PopupMenuItem(value: e.$1, child: Row(children: [if (level == e.$1) const Icon(Icons.check, size: 16) else const SizedBox(width: 16), const SizedBox(width: 6), Text(e.$2)]))],
            child: Row(mainAxisSize: MainAxisSize.min, children: [Icon(Icons.tune, size: 16, color: c.muted), const SizedBox(width: 4), Text({'SIMPLE': 'Đơn giản', 'STANDARD': 'Vừa đủ', 'FULL': 'Đầy đủ'}[level]!, style: TextStyle(color: c.muted, fontSize: 12))]),
          ),
        ]),
        const SizedBox(height: 14),
        Row(crossAxisAlignment: CrossAxisAlignment.end, children: [
          Expanded(child: Text((d['rating_vi'] ?? 'Chưa đủ dữ liệu').toString().toUpperCase(), style: TextStyle(fontSize: 24, fontWeight: FontWeight.w800, color: c.ratingColor(rating), letterSpacing: 0.5))),
          AnimatedCounter(value: asNum(d['score']) ?? 0, format: (v) => '${v.round()}', style: TextStyle(fontSize: 34, fontWeight: FontWeight.w800, color: c.ratingColor(rating), height: 1)),
          Padding(padding: const EdgeInsets.only(bottom: 4, left: 2), child: Text('/100', style: TextStyle(color: c.faint))),
        ]),
        const SizedBox(height: 8),
        ScoreGauge(score: asNum(d['score']), showScore: false),
        Padding(padding: const EdgeInsets.only(top: 3), child: Row(mainAxisAlignment: MainAxisAlignment.spaceBetween, children: [Text('Bán', style: TextStyle(color: c.faint, fontSize: 10)), Text('Nắm giữ', style: TextStyle(color: c.faint, fontSize: 10)), Text('Mua mạnh', style: TextStyle(color: c.faint, fontSize: 10))])),
        const SizedBox(height: 12),
        Text(d['conclusion']?.toString() ?? '', style: const TextStyle(fontSize: 14.5, height: 1.4, fontWeight: FontWeight.w500)),
        if (d['ai_conclusion'] == true) Padding(padding: const EdgeInsets.only(top: 4), child: Row(children: [Icon(Icons.auto_awesome, size: 12, color: c.ai), const SizedBox(width: 4), Text('AI tổng hợp từ số liệu hệ thống', style: TextStyle(color: c.ai, fontSize: 11))])),
        const SizedBox(height: 10),
        Wrap(spacing: 6, runSpacing: 6, children: [
          if (asMap(d['risk']).isNotEmpty) Pill('Rủi ro ${(asMap(d['risk'])['level_vi'] ?? '').toString().toLowerCase()} · ${Fmt.score(asNum(asMap(d['risk'])['score']))}/100', color: c.levelColor(asMap(d['risk'])['level']?.toString()), icon: Icons.shield_outlined)
          else if (risk.isNotEmpty) Pill('Rủi ro DN ${Fmt.score(asNum(risk['score']))} · ${risk['level_vi'] ?? ''}', color: c.levelColor(risk['level']?.toString()), icon: Icons.shield_outlined),
          if (d['is_chase'] == true) Pill('Mua đuổi', color: c.ref, icon: Icons.trending_up) else Pill('Không mua đuổi', color: c.up, icon: Icons.check),
          NextEventChip(ev: asMap(asMap(d['events'])['next'])),
          if (rel['stand_aside'] == true) Pill('Đứng ngoài', color: c.down),
        ]),
        if (rel.isNotEmpty) Padding(padding: const EdgeInsets.only(top: 8), child: Text('Độ tin cậy: ${rel['text']}', style: TextStyle(color: c.muted, fontSize: 12.5))),
        if (rel['gate_reason'] != null) Padding(padding: const EdgeInsets.only(top: 4), child: Text(rel['gate_reason'].toString(), style: TextStyle(color: c.downText, fontSize: 12.5, fontWeight: FontWeight.w600))),
        if (asMap(rel['risk_numbers'])['text'] != null)
          Container(
            margin: const EdgeInsets.only(top: 8), padding: const EdgeInsets.all(10),
            decoration: BoxDecoration(color: c.riskBg, borderRadius: BorderRadius.circular(10), border: Border.all(color: c.riskBorder)),
            child: Row(crossAxisAlignment: CrossAxisAlignment.start, children: [Icon(Icons.info_outline, size: 16, color: c.risk), const SizedBox(width: 8), Expanded(child: Text(asMap(rel['risk_numbers'])['text'].toString(), style: TextStyle(color: c.text, fontSize: 12.5, height: 1.35)))]),
          ),
        const SizedBox(height: 12),
        TrendTiles(asMap(d['trend'])),
        const Divider(height: 24),
        Text('Kế hoạch giao dịch', style: Theme.of(context).textTheme.titleMedium),
        const SizedBox(height: 8),
        _planRow(context, 'Vùng mua', entry.length == 2 ? '${Fmt.price(asNum(entry[0]))} – ${Fmt.price(asNum(entry[1]))}' : Fmt.dash, c.up, note: plan['price_vs_entry_pct'] != null ? 'giá hiện ${Fmt.pct(asNum(plan['price_vs_entry_pct']), decimals: 1)} so với vùng mua' : null),
        _planRow(context, 'Cắt lỗ', Fmt.price(asNum(plan['stop_loss'])), c.down, note: plan['stop_loss_pct'] != null ? Fmt.pct(asNum(plan['stop_loss_pct']), decimals: 1) : null),
        _planRow(context, 'Chốt lời 1', Fmt.price(tp.isNotEmpty ? asNum(tp[0]) : null), c.up),
        _planRow(context, 'Chốt lời 2', Fmt.price(tp.length > 1 ? asNum(tp[1]) : null), c.up),
        _planRow(context, 'Lãi / lỗ kỳ vọng', Fmt.ratio(asNum(plan['risk_reward'])), c.text),
        _SuggestedQty(symbol: sym, price: asNum(d['price']), stop: asNum(plan['stop_loss'])),
        const SizedBox(height: 12),
        Row(children: [
          Expanded(child: FilledButton.icon(onPressed: () => showPretradeSheet(context, symbol: sym, horizon: hz, stopLoss: asNum(plan['stop_loss']), takeProfit: tp.isNotEmpty ? asNum(tp[0]) : null), icon: const Icon(Icons.shopping_cart_checkout, size: 18), label: const Text('Mua'))),
          const SizedBox(width: 8),
          Expanded(child: OutlinedButton(onPressed: () => context.push('/plans/$sym'), child: const Text('Lưu thành kế hoạch'))),
        ]),
        Center(child: TextButton(onPressed: () => showRuleEditor(context, symbol: sym, template: 'ENTRY_ZONE'), child: const Text('Báo khi giá vào vùng mua'))),
      ]),
    );
  }

  Widget _planRow(BuildContext context, String label, String value, Color color, {String? note}) => Padding(
        padding: const EdgeInsets.symmetric(vertical: 4),
        child: Row(crossAxisAlignment: CrossAxisAlignment.start, children: [
          Text(label, style: TextStyle(color: context.vn.muted, fontSize: 13)),
          const SizedBox(width: 8),
          Expanded(child: Column(crossAxisAlignment: CrossAxisAlignment.end, children: [Text(value, textAlign: TextAlign.right, style: TextStyle(color: color, fontWeight: FontWeight.w700, fontSize: 14)), if (note != null) Text(note, textAlign: TextAlign.right, style: TextStyle(color: context.vn.faint, fontSize: 11))])),
        ]),
      );
}

class _SuggestedQty extends ConsumerWidget {
  final String symbol;
  final num? price, stop;
  const _SuggestedQty({required this.symbol, this.price, this.stop});
  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final c = context.vn;
    return FutureBuilder(
      future: ref.read(apiProvider).post('/position-sizing', data: {'symbol': symbol, 'price': price, 'stop_loss': stop}),
      builder: (_, snap) {
        final r = asMap(snap.data);
        final q = asInt(r['quantity']);
        return Padding(
          padding: const EdgeInsets.symmetric(vertical: 4),
          child: Row(crossAxisAlignment: CrossAxisAlignment.start, children: [
            Text('Khối lượng gợi ý', style: TextStyle(color: c.muted, fontSize: 13)),
            const SizedBox(width: 8),
            Expanded(child: Column(crossAxisAlignment: CrossAxisAlignment.end, children: [
              Text(q == null || q == 0 ? '—' : Fmt.qty(q), style: const TextStyle(fontWeight: FontWeight.w700, fontSize: 14)),
              Text(r['equity'] != null && (asNum(r['equity']) ?? 0) > 0 ? 'vốn ${Fmt.money(asNum(r['equity']))}, rủi ro ${Fmt.num_(asNum(r['risk_pct']))}% mỗi lệnh' : 'cần vốn hoặc danh mục để tính', textAlign: TextAlign.right, style: TextStyle(color: c.faint, fontSize: 11)),
            ])),
          ]),
        );
      },
    );
  }
}

class _ChartSection extends ConsumerWidget {
  final Map<String, dynamic> d;
  final String symbol, tf, level;
  final ValueChanged<String> onTf;
  const _ChartSection({required this.d, required this.symbol, required this.tf, required this.onTf, required this.level});
  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final c = context.vn;
    final cd = ref.watch(_candlesProvider((symbol, tf)));
    final plan = asMap(d['plan']);
    final entry = plan['entry'] as List? ?? [];
    final tp = plan['take_profit'] as List? ?? [];
    final ind = asMap(d['indicators']);
    final showInd = detailRank(level) >= 1;
    return AppCard(
      padding: const EdgeInsets.all(12),
      child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
        Row(children: [
          Text('Biểu đồ', style: Theme.of(context).textTheme.titleMedium),
          const Spacer(),
          Segmented<String>(options: const [('1d', 'Ngày'), ('1w', 'Tuần'), ('1m', 'Tháng')], value: tf, onChanged: onTf),
        ]),
        const SizedBox(height: 8),
        cd.when(
          loading: () => const SizedBox(height: 380, child: Center(child: CircularProgressIndicator())),
          error: (e, _) => SizedBox(height: 200, child: ErrorBox(e)),
          data: (cj) => CandleChart(
            candles: asList(cj['candles']).map(Candle.fromJson).toList(),
            bases: asList(cj['bases']).map(BaseBox.fromJson).toList(),
            entryLow: entry.length == 2 ? asDouble(entry[0]) : null, entryHigh: entry.length == 2 ? asDouble(entry[1]) : null,
            stopLoss: asDouble(plan['stop_loss']), takeProfit1: tp.isNotEmpty ? asDouble(tp[0]) : null, takeProfit2: tp.length > 1 ? asDouble(tp[1]) : null,
            showIndicators: showInd, height: context.isPhone ? 320 : (showInd ? 500 : 400),
          ),
        ),
        Padding(padding: const EdgeInsets.only(top: 6), child: Wrap(spacing: 12, children: [_legend('MA20', const Color(0xFF7FB0FF)), _legend('MA50', const Color(0xFFF08A3D)), _legend('MA200', c.ceil), _legend('Vùng mua', c.up), _legend('Cắt lỗ', c.down), Text('Cuộn/kéo để thu phóng, nhấn giữ để xem OHLCV', style: TextStyle(color: c.faint, fontSize: 11))])),
        DetailGate(
          min: 'STANDARD', current: level,
          child: Padding(
            padding: const EdgeInsets.only(top: 10),
            child: Wrap(spacing: 18, runSpacing: 8, children: [
              LabeledValue('RSI (14)', Fmt.num_(asNum(ind['rsi14']), decimals: 0), color: (asNum(ind['rsi14']) ?? 50) > 70 ? c.downText : ((asNum(ind['rsi14']) ?? 50) < 30 ? c.upText : null)),
              LabeledValue('MACD', '${Fmt.num_(asNum(ind['macd']), decimals: 0)} / ${Fmt.num_(asNum(ind['macd_signal']), decimals: 0)}', color: (asNum(ind['macd_hist']) ?? 0) > 0 ? c.upText : c.downText),
              LabeledValue('ADX (14)', Fmt.num_(asNum(ind['adx14']), decimals: 0)),
              LabeledValue('KL / TB20', '${Fmt.num_(asNum(ind['vol_ratio']), decimals: 2)}×'),
              LabeledValue('RS', Fmt.num_(asNum(ind['rs_rating']), decimals: 0)),
              LabeledValue('Cách MA50', Fmt.pct(asNum(ind['dist_ma50_pct']), decimals: 1)),
              LabeledValue('Hỗ trợ / kháng cự', '${Fmt.price(asNum(ind['support_1']))} / ${Fmt.price(asNum(ind['resistance_1']))}'),
              LabeledValue('ATR (14)', Fmt.price(asNum(ind['atr14']))),
            ]),
          ),
        ),
      ]),
    );
  }

  Widget _legend(String l, Color col) => Row(mainAxisSize: MainAxisSize.min, children: [Container(width: 14, height: 3, color: col), const SizedBox(width: 4), Text(l, style: TextStyle(fontSize: 11, color: col))]);
}

class _Details extends ConsumerStatefulWidget {
  final Map<String, dynamic> d;
  final String level, symbol;
  const _Details({required this.d, required this.level, required this.symbol});
  @override
  ConsumerState<_Details> createState() => _DetailsState();
}

class _DetailsState extends ConsumerState<_Details> with SingleTickerProviderStateMixin {
  late final tabs = <(String, Widget Function())>[
    ('Kỹ thuật', _tech),
    if (detailRank(widget.level) >= 1) ('Cơ bản & định giá', _fund),
    ('Tin tức', _news),
    if (detailRank(widget.level) >= 1) ('Dòng tiền & nội bộ', () => FlowsInsidersPanel(symbol: widget.symbol, d: widget.d)),
    ('Sự kiện', () => EventsPanel(symbol: widget.symbol)),
    if (detailRank(widget.level) >= 2) ('Nền giá & đợt tăng', _bases),
    ('Lịch sử tín hiệu', _history),
  ];
  late final _ctl = TabController(length: tabs.length, vsync: this);

  @override
  Widget build(BuildContext context) {
    final c = context.vn;
    final d = widget.d;
    final comp = asMap(d['components']);
    return AppCard(
      padding: const EdgeInsets.all(12),
      child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
        Text('Vì sao có khuyến nghị', style: Theme.of(context).textTheme.titleMedium),
        const SizedBox(height: 6),
        for (final r in asList(d['reasons'])) Padding(padding: const EdgeInsets.only(bottom: 4), child: Row(crossAxisAlignment: CrossAxisAlignment.start, children: [Icon(Icons.check, size: 16, color: c.up), const SizedBox(width: 6), Expanded(child: Text(r['text'].toString(), style: const TextStyle(fontSize: 13.5)))])),
        for (final r in asList(d['drawbacks'])) Padding(padding: const EdgeInsets.only(bottom: 4), child: Row(crossAxisAlignment: CrossAxisAlignment.start, children: [Icon(Icons.remove, size: 16, color: c.down), const SizedBox(width: 6), Expanded(child: Text(r['text'].toString(), style: TextStyle(fontSize: 13.5, color: c.muted)))])),
        DetailGate(
          min: 'STANDARD', current: widget.level,
          child: comp.isEmpty ? const SizedBox.shrink() : Padding(
            padding: const EdgeInsets.only(top: 10),
            child: Wrap(spacing: 10, runSpacing: 10, children: [
              for (final e in [('Kỹ thuật', 'tech', 'tech'), ('Cơ bản', 'fund', 'fund'), ('Ngành', 'sector', 'sector'), ('Nền giá & AI', 'pattern_ai', 'pattern')])
                SizedBox(width: 150, child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [Row(children: [Text(e.$1, style: TextStyle(color: c.faint, fontSize: 11.5)), const Spacer(), Text('${asMap(d['weights'])[e.$3] ?? ''}%', style: TextStyle(color: c.faint, fontSize: 10.5))]), ScoreGauge(score: asNum(comp[e.$2]), compact: true)])),
            ]),
          ),
        ),
        const SizedBox(height: 10),
        TabBar(controller: _ctl, isScrollable: true, tabAlignment: TabAlignment.start, tabs: [for (final t in tabs) Tab(text: t.$1)]),
        AnimatedBuilder(animation: _ctl, builder: (_, __) => Padding(padding: const EdgeInsets.only(top: 12), child: tabs[_ctl.index].$2().animate(key: ValueKey(_ctl.index)).fadeIn(duration: 200.ms))),
      ]),
    );
  }

  Widget _kv(String k, String v, {Color? color}) => Padding(padding: const EdgeInsets.symmetric(vertical: 4), child: Row(children: [Expanded(child: Text(k, style: TextStyle(color: context.vn.muted, fontSize: 13))), Text(v, style: TextStyle(fontWeight: FontWeight.w600, fontSize: 13, color: color))]));

  Widget _tech() {
    final ind = asMap(widget.d['indicators']);
    final c = context.vn;
    final full = detailRank(widget.level) >= 1;
    return Wrap(spacing: 24, runSpacing: 4, children: [
      SizedBox(width: 300, child: Column(children: [
        _kv('Xu hướng', {'STRONG_UP': 'Tăng mạnh', 'UP': 'Tăng', 'FLAT': 'Tích lũy / đi ngang', 'DOWN': 'Giảm', 'STRONG_DOWN': 'Giảm mạnh'}[widget.d['trend_state']] ?? '—'),
        _kv('MA10 / MA20', '${Fmt.price(asNum(ind['ma10']))} / ${Fmt.price(asNum(ind['ma20']))}'),
        _kv('MA50 / MA200', '${Fmt.price(asNum(ind['ma50']))} / ${Fmt.price(asNum(ind['ma200']))}'),
        _kv('Hỗ trợ / kháng cự', '${Fmt.price(asNum(ind['support_1']))} / ${Fmt.price(asNum(ind['resistance_1']))}'),
        _kv('Khối lượng / TB20', '${Fmt.num_(asNum(ind['vol_ratio']), decimals: 2)}×'),
      ])),
      if (full) SizedBox(width: 300, child: Column(children: [
        _kv('RSI (14)', Fmt.num_(asNum(ind['rsi14']), decimals: 1)),
        _kv('MACD / tín hiệu', '${Fmt.num_(asNum(ind['macd']), decimals: 0)} / ${Fmt.num_(asNum(ind['macd_signal']), decimals: 0)}'),
        _kv('ADX (14)', Fmt.num_(asNum(ind['adx14']), decimals: 1)),
        _kv('MFI / CMF', '${Fmt.num_(asNum(ind['mfi14']), decimals: 0)} / ${Fmt.num_(asNum(ind['cmf20']), decimals: 2)}'),
        _kv('Bollinger', '${Fmt.price(asNum(ind['bb_lower']))} – ${Fmt.price(asNum(ind['bb_upper']))} (${Fmt.num_(asNum(ind['bb_width']))}%)'),
        _kv('Xếp hạng RS', Fmt.num_(asNum(ind['rs_rating']), decimals: 0), color: (asNum(ind['rs_rating']) ?? 50) >= 80 ? c.upText : null),
        _kv('Phiên trần liên tiếp', '${ind['ceiling_streak'] ?? 0}'),
      ])),
    ]);
  }

  Widget _fund() {
    final f = asMap(widget.d['fundamentals']);
    final c = context.vn;
    final mos = asNum(f['margin_of_safety']);
    return Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
      Wrap(spacing: 24, runSpacing: 4, children: [
        SizedBox(width: 300, child: Column(children: [
          _kv('P/E', Fmt.num_(asNum(f['pe']))), _kv('P/B', Fmt.num_(asNum(f['pb']), decimals: 2)), _kv('PEG', Fmt.num_(asNum(f['peg']), decimals: 2)), _kv('Vốn hóa', Fmt.money(asNum(f['market_cap']))),
          _kv('Giá trị thực', Fmt.price(asNum(f['fair_value']))), _kv('Biên an toàn', Fmt.pct(mos, decimals: 0), color: mos != null ? (mos >= 20 ? c.upText : (mos < -10 ? c.downText : null)) : null),
        ])),
        SizedBox(width: 300, child: Column(children: [
          _kv('ROE / ROA', '${Fmt.num_(asNum(f['roe']))}% / ${Fmt.num_(asNum(f['roa']))}%'), _kv('Biên LN gộp / ròng', '${Fmt.num_(asNum(f['gross_margin']))}% / ${Fmt.num_(asNum(f['net_margin']))}%'),
          _kv('Nợ vay / VCSH', Fmt.num_(asNum(f['debt_to_equity']), decimals: 2)), _kv('Thanh toán hiện hành', Fmt.num_(asNum(f['current_ratio']), decimals: 2)),
          _kv('Tăng trưởng DT / LN quý', '${Fmt.pct(asNum(f['revenue_yoy']), decimals: 0)} / ${Fmt.pct(asNum(f['profit_yoy']), decimals: 0)}'), _kv('CAGR LN 3 năm', Fmt.pct(asNum(f['profit_cagr_3y']), decimals: 0)),
          _kv('Dòng tiền KD / LN', Fmt.num_(asNum(f['cfo_to_profit']), decimals: 2)), _kv('Tỷ suất cổ tức', Fmt.pct(asNum(f['dividend_yield']), sign: false)),
        ])),
      ]),
      const SizedBox(height: 8),
      _Financials(symbol: widget.symbol),
    ]);
  }

  Widget _news() {
    final n = asMap(widget.d['news']);
    return Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
      if ((asNum(n['count_7d']) ?? 0) > 0)
        Padding(padding: const EdgeInsets.only(bottom: 6), child: Row(children: [
          Text('7 ngày qua: ${n['count_7d']} tin', style: TextStyle(color: context.vn.muted, fontSize: 12.5)),
          const SizedBox(width: 8),
          SentimentPill(score: asNum(n['sentiment_7d'])),
        ])),
      NewsList(items: asList(n['items'])),
    ]);
  }

  Widget _bases() {
    final c = context.vn;
    final b = asMap(widget.d['base']);
    final rc = asMap(widget.d['rally_context']);
    return Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
      if (b.isNotEmpty) ...[
        Text('Nền giá hiện tại', style: TextStyle(fontWeight: FontWeight.w700, color: c.text)),
        _kv('Trạng thái', {'FORMING': 'Đang hình thành', 'BROKEN_OUT': 'Đã phá nền', 'FAILED': 'Thất bại'}[b['status']] ?? '—'),
        _kv('Bắt đầu', Fmt.date(Fmt.parseDate(b['start_date']), year: true)),
        _kv('Đỉnh / đáy nền', '${Fmt.price(asNum(b['base_high']))} / ${Fmt.price(asNum(b['base_low']))}'),
        _kv('Số phiên · biên độ', '${b['length_days']} phiên · ${Fmt.num_(asNum(b['depth_pct']), decimals: 0)}%'),
        _kv('Độ chặt 10 phiên', '${Fmt.num_(asNum(b['tightness_pct']))}%'),
        _kv('Mẫu hình', {'FLAT': 'Nền phẳng', 'CUP_HANDLE': 'Cốc tay cầm', 'DOUBLE_BOTTOM': 'Hai đáy', 'VCP': 'VCP (nén biên độ)'}[b['pattern']] ?? '—'),
        if (b['breakout_date'] != null) _kv('Phá nền', '${Fmt.date(Fmt.parseDate(b['breakout_date']), year: true)} · KL ${Fmt.num_(asNum(b['breakout_vol_ratio']))}× TB20'),
      ],
      const SizedBox(height: 10),
      if (rc.isNotEmpty) ...[
        Text('Thống kê các đợt tăng trước', style: TextStyle(fontWeight: FontWeight.w700, color: c.text)),
        _kv('Số đợt', '${rc['rally_count'] ?? 0}'),
        _kv('Mức tăng trung vị / p75', '${Fmt.pct(asNum(rc['median_gain_pct']), decimals: 0, sign: false)} / ${Fmt.pct(asNum(rc['p75_gain_pct']), decimals: 0, sign: false)}'),
        _kv('Số phiên tới đỉnh (trung vị)', Fmt.num_(asNum(rc['median_days']), decimals: 0)),
        if (rc['current_gain_pct'] != null) _kv('Đợt hiện tại', '${Fmt.pct(asNum(rc['current_gain_pct']), decimals: 0, sign: false)} = ${Fmt.num_(asNum(rc['pct_of_median']), decimals: 0)}% đợt trung bình'),
        if ((asNum(rc['rally_count']) ?? 0) >= 3 && rc['current_gain_pct'] != null)
          Padding(padding: const EdgeInsets.only(top: 6), child: Text('Trong ${rc['rally_count']} đợt tăng trước, mã này tăng trung vị ${Fmt.num_(asNum(rc['median_gain_pct']), decimals: 0)}% từ nền; hiện đã tăng ${Fmt.num_(asNum(rc['current_gain_pct']), decimals: 0)}%${(asNum(rc['pct_of_median']) ?? 0) >= 80 ? ' → vùng cân nhắc chốt lời một phần' : ''}.', style: TextStyle(color: c.muted, fontSize: 13))),
      ] else Text('Chưa đủ đợt tăng hoàn chỉnh để thống kê.', style: TextStyle(color: c.muted)),
    ]);
  }

  Widget _history() {
    final c = context.vn;
    final rows = asList(widget.d['history']);
    if (rows.isEmpty) return Text('Chưa có tín hiệu nào cho mã này.', style: TextStyle(color: c.muted));
    return Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
      if (widget.d['history_summary'] != null) Padding(padding: const EdgeInsets.only(bottom: 8), child: Text(widget.d['history_summary'].toString(), style: TextStyle(fontWeight: FontWeight.w600, color: c.text))),
      for (final h in rows)
        Padding(
          padding: const EdgeInsets.symmetric(vertical: 5),
          child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
            Row(children: [
              Text(Fmt.date(Fmt.parseDate(h['date']), year: true), style: TextStyle(color: c.faint, fontSize: 12)),
              const SizedBox(width: 8),
              Expanded(child: Text(h['title'].toString().split('] ').last, maxLines: 1, overflow: TextOverflow.ellipsis, style: const TextStyle(fontSize: 13))),
            ]),
            const SizedBox(height: 3),
            Wrap(spacing: 10, runSpacing: 4, crossAxisAlignment: WrapCrossAlignment.center, children: [
              RatingChip(h['rating']?.toString(), score: asNum(h['score'])),
              Text('giá ${Fmt.price(asNum(h['price']))}', style: TextStyle(fontSize: 12, color: c.muted)),
              Text('${h['result_vi']}${h['return_pct'] != null ? ' ${Fmt.pct(asNum(h['return_pct']), decimals: 1)}' : ''}', style: TextStyle(fontSize: 12, fontWeight: FontWeight.w600, color: {'TP_HIT': c.upText, 'WIN': c.upText, 'STOP_HIT': c.downText, 'LOSS': c.downText}[h['result']] ?? c.muted)),
            ]),
          ]),
        ),
    ]);
  }
}

class _Financials extends ConsumerWidget {
  final String symbol;
  const _Financials({required this.symbol});
  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final c = context.vn;
    final fin = ref.watch(getMapProvider('/stocks/$symbol/financials?period=Q'));
    return fin.when(
      loading: () => const Skeleton(height: 80),
      error: (e, _) => const SizedBox.shrink(),
      data: (f) {
        final rows = asList(f['statements']).reversed.take(8).toList();
        if (rows.isEmpty) return Text('Chưa có báo cáo tài chính.', style: TextStyle(color: c.muted));
        return SingleChildScrollView(
          scrollDirection: Axis.horizontal,
          child: DataTable(
            columnSpacing: 18,
            columns: [const DataColumn(label: Text('Quý')), for (final r in rows) DataColumn(label: Text('Q${r['quarter']}/${r['year']}'))],
            rows: [
              for (final e in [('Doanh thu', 'revenue'), ('LNST', 'net_profit'), ('EPS', 'eps'), ('Vốn chủ', 'equity'), ('Nợ vay', null), ('Dòng tiền KD', 'cfo')])
                DataRow(cells: [
                  DataCell(Text(e.$1, style: TextStyle(color: c.muted))),
                  for (final r in rows)
                    DataCell(Text(e.$2 == null ? Fmt.money((asNum(r['short_debt']) ?? 0) + (asNum(r['long_debt']) ?? 0)) : (e.$2 == 'eps' ? Fmt.price(asNum(r['eps'])) : Fmt.money(asNum(r[e.$2]))),
                        style: TextStyle(color: e.$2 == 'net_profit' || e.$2 == 'cfo' ? c.changeColor(asNum(r[e.$2])) : null))),
                ]),
            ],
          ),
        );
      },
    );
  }
}


/// Total risk (6 components) — the basis of "gợi ý ít rủi ro nhất". Always visible at every detail level (BR-20).
class _RiskCard extends StatelessWidget {
  final Map<String, dynamic> d;
  const _RiskCard({required this.d});
  @override
  Widget build(BuildContext context) {
    final c = context.vn;
    final risk = asMap(d['risk']);
    if (risk.isEmpty) return const SizedBox.shrink();
    final comps = asList(risk['components']);
    final level = risk['level']?.toString();
    Color colFor(num v) => v < 35 ? c.up : (v < 60 ? c.ref : c.downText);
    return AppCard(
      child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
        Row(children: [
          Expanded(child: Text('Rủi ro tổng hợp', style: Theme.of(context).textTheme.titleMedium)),
          Pill('${risk['level_vi'] ?? ''} · ${Fmt.score(asNum(risk['score']))}/100', color: c.levelColor(level), icon: Icons.shield_outlined),
        ]),
        const SizedBox(height: 4),
        Text(risk['text']?.toString() ?? '', style: TextStyle(color: c.muted, fontSize: 12.5)),
        if (risk['downgraded'] == true) Padding(padding: const EdgeInsets.only(top: 4), child: Text('Rủi ro cao nên khuyến nghị đã hạ một bậc.', style: TextStyle(color: c.downText, fontSize: 12.5, fontWeight: FontWeight.w600))),
        const SizedBox(height: 10),
        for (final x in comps)
          Padding(
            padding: const EdgeInsets.only(bottom: 8),
            child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
              Row(children: [
                SizedBox(width: 128, child: Text(x['label'].toString(), style: const TextStyle(fontSize: 13, fontWeight: FontWeight.w600))),
                Expanded(child: ClipRRect(borderRadius: BorderRadius.circular(4), child: LinearProgressIndicator(value: ((asNum(x['score']) ?? 0) / 100).clamp(0.0, 1.0), minHeight: 8, backgroundColor: c.surface2, color: colFor(asNum(x['score']) ?? 0)))),
                SizedBox(width: 44, child: Text(Fmt.score(asNum(x['score'])), textAlign: TextAlign.right, style: TextStyle(fontSize: 13, fontWeight: FontWeight.w700, color: colFor(asNum(x['score']) ?? 0), fontFeatures: const [FontFeature.tabularFigures()]))),
                SizedBox(width: 34, child: Text('${x['weight']}%', textAlign: TextAlign.right, style: TextStyle(fontSize: 11, color: c.faint))),
              ]),
              Padding(padding: const EdgeInsets.only(left: 128, top: 2), child: Text(x['note']?.toString() ?? '', style: TextStyle(color: c.muted, fontSize: 11.5), maxLines: 2, overflow: TextOverflow.ellipsis)),
            ]),
          ),
        Text(risk['personalized'] == true ? 'Tương quan tính theo các mã bạn đang nắm giữ. Cột phải là trọng số.' : 'Tương quan tạm tính theo beta với VN-Index; sẽ tính theo danh mục khi bạn ghi nhận giao dịch. Cột phải là trọng số.', style: TextStyle(color: c.faint, fontSize: 11)),
      ]),
    );
  }
}
