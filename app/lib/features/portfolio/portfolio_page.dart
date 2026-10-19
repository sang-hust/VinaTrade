import 'package:file_picker/file_picker.dart';
import 'package:fl_chart/fl_chart.dart';
import 'package:flutter/material.dart';
import 'package:flutter_animate/flutter_animate.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:go_router/go_router.dart';

import '../../core/api.dart';
import '../../core/format.dart';
import '../../core/providers.dart';
import '../../core/responsive.dart';
import '../../core/theme.dart';
import '../../shared/widgets/brand.dart';
import '../../shared/widgets/common.dart';
import '../../shared/widgets/score.dart';
import '../../shared/widgets/stock_rows.dart';
import '../ai/ai_panel.dart';
import '../pretrade/pretrade_sheet.dart';
import '../shell/app_shell.dart' show showSymbolSearch;

final portfoliosProvider = FutureProvider.autoDispose<List<Map<String, dynamic>>>((ref) async => asList(await ref.watch(apiProvider).get('/portfolios')));
final portfolioProvider = FutureProvider.autoDispose.family<Map<String, dynamic>, String>((ref, id) async => asMap(await ref.watch(apiProvider).get('/portfolios/$id')));

class PortfolioPage extends ConsumerStatefulWidget {
  final String? id, tab;
  const PortfolioPage({super.key, this.id, this.tab});
  @override
  ConsumerState<PortfolioPage> createState() => _PortfolioPageState();
}

class _PortfolioPageState extends ConsumerState<PortfolioPage> {
  late String tab = widget.tab ?? 'overview';

  @override
  Widget build(BuildContext context) {
    final pfs = ref.watch(portfoliosProvider);
    return pfs.when(
      loading: () => const PageBody(child: SkeletonList()),
      error: (e, _) => PageBody(child: ErrorBox(e, onRetry: () => ref.invalidate(portfoliosProvider))),
      data: (list) {
        if (list.isEmpty) return PageBody(child: _NoPortfolio(onCreate: () => _createPortfolio(context, ref)));
        final cur = list.firstWhere((p) => p['id'] == widget.id, orElse: () => list.first);
        return _Body(portfolios: list, current: cur, tab: tab, onTab: (t) => setState(() => tab = t), onPick: (id) => context.go('/portfolio/$id?tab=$tab'), onCreate: () => _createPortfolio(context, ref));
      },
    );
  }
}

Future<void> _createPortfolio(BuildContext context, WidgetRef ref, {bool paper = false}) async {
  final name = TextEditingController(text: paper ? 'Danh mục thử' : ''), broker = TextEditingController(), cap = TextEditingController(text: paper ? '500000000' : '');
  bool margin = false;
  final ok = await showDialog<bool>(
    context: context,
    builder: (ctx) => StatefulBuilder(builder: (ctx, set) => AlertDialog(
      title: Text(paper ? 'Tạo danh mục giao dịch thử' : 'Tạo danh mục'),
      content: SizedBox(width: 380, child: Column(mainAxisSize: MainAxisSize.min, children: [
        TextField(controller: name, decoration: const InputDecoration(labelText: 'Tên danh mục')),
        const SizedBox(height: 10),
        if (!paper) TextField(controller: broker, decoration: const InputDecoration(labelText: 'Công ty chứng khoán (VCBS, Pinetree…)')),
        const SizedBox(height: 10),
        TextField(controller: cap, keyboardType: TextInputType.number, decoration: InputDecoration(labelText: paper ? 'Vốn ảo (đồng)' : 'Tiền mặt ban đầu (đồng)')),
        if (!paper) SwitchListTile(contentPadding: EdgeInsets.zero, value: margin, onChanged: (v) => set(() => margin = v), title: const Text('Có dùng ký quỹ')),
      ])),
      actions: [TextButton(onPressed: () => Navigator.pop(ctx, false), child: const Text('Hủy')), FilledButton(onPressed: () => Navigator.pop(ctx, true), child: const Text('Tạo'))],
    )),
  );
  if (ok != true || name.text.trim().isEmpty) return;
  try {
    final r = asMap(await ref.read(apiProvider).post('/portfolios', query: {'paper': paper}, data: {'name': name.text.trim(), 'broker': broker.text.trim().isEmpty ? null : broker.text.trim(), 'is_paper': paper, 'uses_margin': margin, 'initial_capital': num.tryParse(cap.text.replaceAll('.', '')) ?? 0}));
    ref.invalidate(portfoliosProvider);
    if (context.mounted) context.go('/portfolio/${r['id']}');
  } on ApiException catch (e) {
    if (context.mounted) showToast(context, e.message, error: true);
  }
}

class _NoPortfolio extends StatelessWidget {
  final VoidCallback onCreate;
  const _NoPortfolio({required this.onCreate});
  @override
  Widget build(BuildContext context) => EmptyState(art: EmptyArt.portfolio, title: 'Danh mục đang trống', message: 'Tạo danh mục rồi thêm giao dịch đầu tiên để theo dõi lãi/lỗ và nhận cảnh báo cắt lỗ.', actionLabel: 'Tạo danh mục', onAction: onCreate);
}

class _Body extends ConsumerWidget {
  final List<Map<String, dynamic>> portfolios;
  final Map<String, dynamic> current;
  final String tab;
  final ValueChanged<String> onTab, onPick;
  final VoidCallback onCreate;
  const _Body({required this.portfolios, required this.current, required this.tab, required this.onTab, required this.onPick, required this.onCreate});

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final c = context.vn;
    final id = current['id'].toString();
    final data = ref.watch(portfolioProvider(id));
    return PageBody(
      child: ListView(children: [
        Builder(builder: (context) {
          final chips = Wrap(crossAxisAlignment: WrapCrossAlignment.center, spacing: 8, runSpacing: 8, children: [
            Text('Danh mục', style: Theme.of(context).textTheme.titleLarge),
            for (final p in portfolios)
              ChoiceChip(
                selected: p['id'] == id, onSelected: (_) => onPick(p['id']),
                label: Text('${p['name']} · ${p['label']}'),
                side: p['is_paper'] == true ? BorderSide(color: c.ai, width: 1.5, style: BorderStyle.solid) : null,
                avatar: p['is_paper'] == true ? Icon(Icons.science_outlined, size: 14, color: c.ai) : null,
              ),
            PopupMenuButton<String>(
              itemBuilder: (_) => const [PopupMenuItem(value: 'real', child: Text('Danh mục mới')), PopupMenuItem(value: 'paper', child: Text('Danh mục giao dịch thử (tiền ảo)'))],
              onSelected: (v) => _createPortfolio(context, ref, paper: v == 'paper'),
              child: const Chip(avatar: Icon(Icons.add, size: 16), label: Text('Thêm')),
            ),
          ]);
          final buttons = Wrap(spacing: 8, runSpacing: 8, children: [
            FilledButton.icon(onPressed: () => _recordTrade(context, ref, id), icon: const Icon(Icons.edit_note, size: 18), label: const Text('Ghi nhận giao dịch')),
            AskAiButton(compact: context.isPhone, onPressed: () => openAi(context, {'screen': 'portfolio', 'portfolio_id': id})),
          ]);
          if (context.isPhone) return Column(crossAxisAlignment: CrossAxisAlignment.start, children: [chips, const SizedBox(height: 8), buttons]);
          return Row(crossAxisAlignment: CrossAxisAlignment.start, children: [Expanded(child: chips), const SizedBox(width: 8), buttons]);
        }),
        Padding(padding: const EdgeInsets.symmetric(vertical: 6), child: Text('Vinatrade không đặt lệnh, chỉ ghi lại giao dịch đã khớp tại công ty chứng khoán.', style: TextStyle(color: c.faint, fontSize: 11.5))),
        Segmented<String>(options: const [('overview', 'Tổng quan'), ('risk', 'Rủi ro & ký quỹ'), ('history', 'Giao dịch'), ('perf', 'Hiệu suất')], value: tab, onChanged: onTab),
        const SizedBox(height: 12),
        data.when(
          loading: () => const SkeletonList(),
          error: (e, _) => ErrorBox(e, onRetry: () => ref.invalidate(portfolioProvider(id))),
          data: (d) => switch (tab) {
            'risk' => _RiskTab(d: d, id: id),
            'history' => _HistoryTab(id: id),
            'perf' => _PerfTab(id: id, d: d),
            _ => _Overview(d: d, id: id),
          },
        ),
        const DisclaimerText(),
      ]),
    );
  }
}

Future<void> _recordTrade(BuildContext context, WidgetRef ref, String pfId, {String? symbol}) async {
  String side = 'BUY';
  final sym = TextEditingController(text: symbol ?? ''), qty = TextEditingController(), price = TextEditingController(), amount = TextEditingController(), note = TextEditingController(), stop = TextEditingController();
  DateTime date = DateTime.now();
  await showDialog(
    context: context,
    builder: (ctx) => StatefulBuilder(builder: (ctx, set) {
      final isTrade = side == 'BUY' || side == 'SELL';
      return AlertDialog(
        title: const Text('Ghi nhận giao dịch'),
        content: SizedBox(
          width: 420,
          child: Column(mainAxisSize: MainAxisSize.min, crossAxisAlignment: CrossAxisAlignment.stretch, children: [
            Segmented<String>(options: const [('BUY', 'Mua'), ('SELL', 'Bán'), ('DEPOSIT', 'Nộp tiền'), ('WITHDRAW', 'Rút tiền')], value: side, onChanged: (v) => set(() => side = v)),
            const SizedBox(height: 12),
            if (side == 'BUY') Text('Lệnh mua luôn đi qua Kiểm tra trước khi mua.', style: TextStyle(color: ctx.vn.muted, fontSize: 12.5)),
            if (isTrade) ...[
              TextField(controller: sym, decoration: const InputDecoration(labelText: 'Mã'), textCapitalization: TextCapitalization.characters),
              const SizedBox(height: 8),
              Row(children: [Expanded(child: TextField(controller: qty, keyboardType: TextInputType.number, decoration: const InputDecoration(labelText: 'Khối lượng'))), const SizedBox(width: 8), Expanded(child: TextField(controller: price, keyboardType: TextInputType.number, decoration: const InputDecoration(labelText: 'Giá khớp (đồng)')))]),
              if (side == 'SELL') ...[const SizedBox(height: 8), TextField(controller: note, decoration: const InputDecoration(labelText: 'Lý do bán / bài học (tùy chọn)'))],
            ] else
              TextField(controller: amount, keyboardType: TextInputType.number, decoration: const InputDecoration(labelText: 'Số tiền (đồng)')),
            const SizedBox(height: 8),
            OutlinedButton.icon(
              onPressed: () async {
                final d = await showDatePicker(context: ctx, initialDate: date, firstDate: DateTime(2015), lastDate: DateTime.now());
                if (d != null) set(() => date = d);
              },
              icon: const Icon(Icons.calendar_today, size: 16), label: Text('Ngày ${Fmt.date(date, year: true)}'),
            ),
          ]),
        ),
        actions: [
          TextButton(onPressed: () => Navigator.pop(ctx), child: const Text('Hủy')),
          FilledButton(
            onPressed: () async {
              if (side == 'BUY') {
                if (sym.text.trim().isEmpty) return;
                Navigator.pop(ctx);
                final ok = await showPretradeSheet(context, symbol: sym.text.trim().toUpperCase(), portfolioId: pfId, quantity: int.tryParse(qty.text), price: num.tryParse(price.text), stopLoss: num.tryParse(stop.text));
                if (ok == true) ref.invalidate(portfolioProvider(pfId));
                return;
              }
              try {
                final r = asMap(await ref.read(apiProvider).post('/portfolios/$pfId/transactions', data: {
                  'side': side, 'symbol': sym.text.trim().isEmpty ? null : sym.text.trim().toUpperCase(), 'quantity': int.tryParse(qty.text.replaceAll('.', '')) ?? 0, 'price': num.tryParse(price.text.replaceAll('.', '')) ?? 0,
                  'amount': num.tryParse(amount.text.replaceAll('.', '')), 'trade_date': date.toIso8601String().substring(0, 10), 'reason': note.text.trim().isEmpty ? null : note.text.trim(),
                }));
                ref.invalidate(portfolioProvider(pfId));
                ref.invalidate(portfoliosProvider);
                if (ctx.mounted) Navigator.pop(ctx);
                if (context.mounted) showToast(context, r['message']?.toString() ?? 'Đã ghi giao dịch');
              } on ApiException catch (e) {
                if (ctx.mounted) showToast(ctx, e.message, error: true);
              }
            },
            child: const Text('Ghi nhận'),
          ),
        ],
      );
    }),
  );
}

class _Overview extends ConsumerWidget {
  final Map<String, dynamic> d;
  final String id;
  const _Overview({required this.d, required this.id});

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final c = context.vn;
    final k = asMap(d['kpis']);
    final items = asList(d['action_items']);
    final positions = asList(d['positions']);
    final pf = asMap(d['portfolio']);
    final stress = asList(k['stress']);
    final kpis = [
      KpiTile(label: 'Tổng tài sản', value: Fmt.money(asNum(k['nav']), full: true), animateFrom: asNum(k['nav']), format: (v) => Fmt.money(v, full: true), note: 'tiền mặt ${Fmt.money(asNum(k['cash']))}'),
      KpiTile(label: 'Lãi/lỗ chưa chốt', value: Fmt.money(asNum(k['unrealized_pnl'])), valueColor: c.changeColor(asNum(k['unrealized_pnl'])), note: Fmt.pct(asNum(k['unrealized_pnl_pct']))),
      KpiTile(label: 'Hôm nay', value: Fmt.pct(asNum(k['today_pnl_pct'])), valueColor: c.changeColor(asNum(k['today_pnl_pct'])), note: 'VN-Index ${Fmt.pct(asNum(k['vnindex_change_pct']))}'),
      KpiTile(label: 'Lỗ tối đa nếu mọi mã chạm cắt lỗ', value: Fmt.pct(-(asNum(k['open_risk_pct']) ?? 0), decimals: 1), valueColor: c.downText, note: stress.map((s) => '${s['shock_pct']}%: ${Fmt.money(asNum(s['loss']))}').join(' · ')),
    ];
    return Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
      if (pf['is_paper'] == true) Padding(padding: const EdgeInsets.only(bottom: 8), child: Pill('Tiền ảo — không tính vào cầu dao và tỷ trọng', color: c.ai, dashed: true)),
      if (context.isPhone) Column(crossAxisAlignment: CrossAxisAlignment.stretch, children: [for (final (i, t) in kpis.indexed) Padding(padding: const EdgeInsets.only(bottom: 8), child: t.stagger(context, i))]) else Row(children: [for (final (i, t) in kpis.indexed) Expanded(child: Padding(padding: EdgeInsets.only(right: i < 3 ? 12 : 0), child: t.stagger(context, i)))]),
      SizedBox(height: context.gap),
      AppCard(
        child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
          Row(children: [Text('Cần xử lý', style: Theme.of(context).textTheme.titleMedium), const SizedBox(width: 8), if (items.isNotEmpty) Pill('${items.length}', color: c.urgent), const Spacer(), IconButton(tooltip: 'Tính lại', icon: const Icon(Icons.refresh, size: 18), onPressed: () async {
            await ref.read(apiProvider).get('/portfolios/$id/action-items', query: {'refresh': true});
            ref.invalidate(portfolioProvider(id));
          })]),
          const SizedBox(height: 8),
          if (items.isEmpty) Text('Không có việc nào cần làm ngay. Danh mục đang trong giới hạn.', style: TextStyle(color: c.muted, fontSize: 13))
          else for (final (i, it) in items.indexed) Padding(padding: const EdgeInsets.only(bottom: 8), child: ActionItemCard(it, portfolioId: id).stagger(context, i)),
        ]),
      ).stagger(context, 4),
      SizedBox(height: context.gap),
      AppCard(
        padding: const EdgeInsets.all(12),
        child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
          Text('Vị thế đang nắm giữ', style: Theme.of(context).textTheme.titleMedium),
          const SizedBox(height: 8),
          if (positions.isEmpty) EmptyState(art: EmptyArt.portfolio, title: 'Chưa có vị thế', message: 'Ghi nhận giao dịch mua đầu tiên (đi qua kiểm tra trước khi mua).', actionLabel: 'Ghi nhận giao dịch', onAction: () => _recordTrade(context, ref, id))
          else _Positions(positions: positions, id: id),
        ]),
      ).stagger(context, 5),
      SizedBox(height: context.gap),
      Row(crossAxisAlignment: CrossAxisAlignment.start, children: [
        Expanded(child: AppCard(child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
          Text('Phân bổ theo ngành', style: Theme.of(context).textTheme.titleMedium),
          const SizedBox(height: 8),
          for (final s in asList(d['sector_weights']))
            Padding(padding: const EdgeInsets.symmetric(vertical: 3), child: Row(children: [SizedBox(width: 150, child: Text(s['name'].toString(), style: const TextStyle(fontSize: 13), overflow: TextOverflow.ellipsis)), Expanded(child: ClipRRect(borderRadius: BorderRadius.circular(3), child: LinearProgressIndicator(value: (asNum(s['weight_pct']) ?? 0) / 100, minHeight: 7, color: s['over_limit'] == true ? c.ref : c.accent, backgroundColor: c.surface2))), const SizedBox(width: 8), SizedBox(width: 50, child: Text(Fmt.pct(asNum(s['weight_pct']), decimals: 1, sign: false), textAlign: TextAlign.right, style: TextStyle(fontSize: 12.5, color: s['over_limit'] == true ? c.ref : null)))])),
          Padding(padding: const EdgeInsets.symmetric(vertical: 3), child: Row(children: [const SizedBox(width: 150, child: Text('Tiền mặt', style: TextStyle(fontSize: 13))), Expanded(child: ClipRRect(borderRadius: BorderRadius.circular(3), child: LinearProgressIndicator(value: (asNum(d['cash_weight_pct']) ?? 0) / 100, minHeight: 7, color: c.muted, backgroundColor: c.surface2))), const SizedBox(width: 8), SizedBox(width: 50, child: Text(Fmt.pct(asNum(d['cash_weight_pct']), decimals: 1, sign: false), textAlign: TextAlign.right, style: const TextStyle(fontSize: 12.5)))])),
          Text('Giới hạn ngành ${Fmt.num_(asNum(asMap(d['limits'])['max_sector_pct']), decimals: 0)}%', style: TextStyle(color: c.faint, fontSize: 11.5)),
        ]))),
      ]).stagger(context, 6),
    ]);
  }
}

class ActionItemCard extends ConsumerStatefulWidget {
  final Map<String, dynamic> item;
  final String portfolioId;
  const ActionItemCard(this.item, {super.key, required this.portfolioId});
  @override
  ConsumerState<ActionItemCard> createState() => _ActionItemCardState();
}

class _ActionItemCardState extends ConsumerState<ActionItemCard> {
  String? result;
  bool busy = false;

  Future<void> _do(Map<String, dynamic> a) async {
    final code = a['code']?.toString();
    final p = asMap(a['params']);
    if (code == 'OPEN') {
      context.push(p['route']?.toString() ?? '/portfolio');
      return;
    }
    if (code == 'PRETRADE') {
      final ok = await showPretradeSheet(context, symbol: p['symbol'].toString(), portfolioId: widget.portfolioId);
      if (ok == true) ref.invalidate(portfolioProvider(widget.portfolioId));
      return;
    }
    Map<String, dynamic> params = {};
    if (code == 'EDIT_STOP' || (code == 'MOVE_STOP' && p['stop_loss'] == null)) {
      final ctl = TextEditingController(text: p['stop_loss']?.toString() ?? '');
      final reason = TextEditingController();
      final v = await showDialog<Map<String, dynamic>>(context: context, builder: (ctx) => AlertDialog(title: Text('Cắt lỗ mới cho ${p['symbol']}'), content: Column(mainAxisSize: MainAxisSize.min, children: [TextField(controller: ctl, autofocus: true, keyboardType: TextInputType.number, decoration: const InputDecoration(labelText: 'Mức cắt lỗ (đồng)')), const SizedBox(height: 8), TextField(controller: reason, decoration: const InputDecoration(labelText: 'Lý do (bắt buộc nếu hạ thấp hơn kế hoạch)'))]), actions: [TextButton(onPressed: () => Navigator.pop(ctx), child: const Text('Hủy')), FilledButton(onPressed: () => Navigator.pop(ctx, {'stop_loss': num.tryParse(ctl.text.replaceAll('.', '')), 'reason': reason.text}), child: const Text('Lưu'))]));
      if (v == null) return;
      params = v;
      if (code == 'EDIT_STOP') params['symbol'] = p['symbol'];
    }
    setState(() => busy = true);
    try {
      final r = asMap(await ref.read(apiProvider).post('/action-items/${widget.item['id']}/resolve', data: {'action': code, 'params': params}));
      setState(() => result = r['result']?.toString());
      ref.invalidate(portfolioProvider(widget.portfolioId));
      if (mounted && r['result'] != 'open') showToast(context, r['result'].toString());
    } on ApiException catch (e) {
      if (mounted) showToast(context, e.message, error: true);
    } finally {
      if (mounted) setState(() => busy = false);
    }
  }

  @override
  Widget build(BuildContext context) {
    final c = context.vn;
    final it = widget.item;
    final pr = it['priority']?.toString();
    final done = result != null && result != 'open';
    return AnimatedOpacity(
      opacity: done ? 0.55 : 1,
      duration: 300.ms,
      child: Container(
        padding: const EdgeInsets.all(12),
        decoration: BoxDecoration(color: c.priorityBg(pr), borderRadius: BorderRadius.circular(12), border: Border.all(color: pr == 'URGENT' ? c.urgentBorder : (pr == 'RISK' ? c.riskBorder : c.suggestBg))),
        child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
          Row(children: [Pill(it['priority_vi']?.toString() ?? '', color: c.priorityColor(pr), fontSize: 10.5), if (it['symbol'] != null) ...[const SizedBox(width: 8), InkWell(onTap: () => context.push('/stocks/${it['symbol']}'), child: Text(it['symbol'].toString(), style: TextStyle(fontWeight: FontWeight.w700, color: c.link)))]]),
          const SizedBox(height: 6),
          Text(it['title'].toString(), style: const TextStyle(fontWeight: FontWeight.w700, fontSize: 14)),
          if (it['detail'] != null) Padding(padding: const EdgeInsets.only(top: 3), child: Text(it['detail'].toString(), style: TextStyle(color: c.muted, fontSize: 12.5))),
          const SizedBox(height: 8),
          if (done) Text('✓ $result', style: TextStyle(color: c.up, fontWeight: FontWeight.w600, fontSize: 13))
          else Wrap(spacing: 8, children: [
            for (final (i, a) in asList(it['actions']).indexed)
              i == 0 ? FilledButton(onPressed: busy ? null : () => _do(a), style: FilledButton.styleFrom(visualDensity: VisualDensity.compact), child: Text(a['label'].toString(), style: const TextStyle(fontSize: 12.5)))
                     : OutlinedButton(onPressed: busy ? null : () => _do(a), style: OutlinedButton.styleFrom(visualDensity: VisualDensity.compact), child: Text(a['label'].toString(), style: const TextStyle(fontSize: 12.5))),
          ]),
        ]),
      ),
    );
  }
}

class _Positions extends ConsumerWidget {
  final List<Map<String, dynamic>> positions;
  final String id;
  const _Positions({required this.positions, required this.id});
  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final rows = positions.map((p) => {...p, 'ref_price': null, 'score': p['score'], 'rating_hz': p['rating'], 'trend3': null}).toList();
    return StockTable(
      rows: rows, minWidth: 1100, highlightChanged: false,
      columns: [
        StockCol('quantity', 'KL', width: 70, build: (ctx, r) => Text(Fmt.price(asNum(r['quantity'])))),
        StockCol('avg_cost', 'Giá vốn / hiện tại', width: 140, build: (ctx, r) => Text('${Fmt.price(asNum(r['avg_cost']))} / ${Fmt.price(asNum(r['price']))}')),
        StockCol('value', 'Giá trị', width: 90, build: (ctx, r) => Text(Fmt.money(asNum(r['value'])))),
        StockCol('pnl', 'Lãi/lỗ', width: 130, build: (ctx, r) => Text('${Fmt.money(asNum(r['pnl']))} (${Fmt.pct(asNum(r['pnl_pct']))})', style: TextStyle(color: ctx.vn.changeColor(asNum(r['pnl'])), fontWeight: FontWeight.w600))),
        StockCol('weight_pct', 'Tỷ trọng', width: 70, build: (ctx, r) => Text(Fmt.pct(asNum(r['weight_pct']), decimals: 1, sign: false))),
        StockCol('rating', 'Khuyến nghị', width: 110, build: (ctx, r) => Align(alignment: Alignment.centerLeft, child: RatingChip(r['rating']?.toString(), score: asNum(r['score'])))),
        StockCol('bar', 'Cắt lỗ → mục tiêu', width: 150, build: (ctx, r) => Column(mainAxisAlignment: MainAxisAlignment.center, crossAxisAlignment: CrossAxisAlignment.start, children: [PriceBar(stop: asNum(r['stop_loss'] ?? r['sys_stop']), target: asNum(r['take_profit_1'] ?? r['sys_tp1']), price: asNum(r['price']), entry: asNum(r['avg_cost'])), Text('${Fmt.price(asNum(r['stop_loss'] ?? r['sys_stop']))} · ${Fmt.price(asNum(r['take_profit_1'] ?? r['sys_tp1']))}', style: TextStyle(fontSize: 10.5, color: ctx.vn.faint))])),
      ],
      trailing: (ctx, r) => Row(mainAxisSize: MainAxisSize.min, children: [
        IconButton(tooltip: 'Sửa cắt lỗ', icon: const Icon(Icons.edit_outlined, size: 16), onPressed: () => _editStop(ctx, ref, r)),
        IconButton(tooltip: 'Kế hoạch nếu–thì', icon: const Icon(Icons.alt_route, size: 16), onPressed: () => ctx.push('/portfolio/$id/plans/${r['symbol']}')),
      ]),
    );
  }

  Future<void> _editStop(BuildContext context, WidgetRef ref, Map<String, dynamic> r) async {
    final ctl = TextEditingController(text: (asNum(r['stop_loss']) ?? asNum(r['sys_stop']))?.round().toString() ?? ''), tp = TextEditingController(text: (asNum(r['take_profit_1']) ?? asNum(r['sys_tp1']))?.round().toString() ?? ''), reason = TextEditingController();
    final ok = await showDialog<bool>(context: context, builder: (ctx) => AlertDialog(title: Text('Cắt lỗ / chốt lời ${r['symbol']}'), content: SizedBox(width: 360, child: Column(mainAxisSize: MainAxisSize.min, children: [TextField(controller: ctl, keyboardType: TextInputType.number, decoration: const InputDecoration(labelText: 'Cắt lỗ (đồng)')), const SizedBox(height: 8), TextField(controller: tp, keyboardType: TextInputType.number, decoration: const InputDecoration(labelText: 'Chốt lời 1 (đồng)')), const SizedBox(height: 8), TextField(controller: reason, decoration: const InputDecoration(labelText: 'Lý do (bắt buộc nếu hạ cắt lỗ)'))])), actions: [TextButton(onPressed: () => Navigator.pop(ctx, false), child: const Text('Hủy')), FilledButton(onPressed: () => Navigator.pop(ctx, true), child: const Text('Lưu'))]));
    if (ok != true) return;
    try {
      await ref.read(apiProvider).put('/portfolios/$id/positions/${r['symbol']}/stop', data: {'stop_loss': num.tryParse(ctl.text.replaceAll('.', '')), 'take_profit_1': num.tryParse(tp.text.replaceAll('.', '')), 'reason': reason.text.trim().isEmpty ? null : reason.text.trim()});
      ref.invalidate(portfolioProvider(id));
      if (context.mounted) showToast(context, 'Đã cập nhật cắt lỗ ${r['symbol']}');
    } on ApiException catch (e) {
      if (context.mounted) showToast(context, e.message, error: true);
    }
  }
}

class _RiskTab extends ConsumerWidget {
  final Map<String, dynamic> d;
  final String id;
  const _RiskTab({required this.d, required this.id});
  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final c = context.vn;
    final g = asMap(d['guard']);
    final lim = asMap(d['limits']);
    final k = asMap(d['kpis']);
    final pf = asMap(d['portfolio']);
    final corr = ref.watch(getMapProvider('/portfolios/$id/correlation'));
    final margin = ref.watch(getMapProvider('/portfolios/$id/margin'));
    final defensive = g['mode'] == 'DEFENSIVE';
    return Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
      AppCard(
        borderColor: defensive ? c.down : null,
        child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
          Row(children: [Icon(Icons.shield_outlined, color: defensive ? c.down : c.up), const SizedBox(width: 8), Text(defensive ? 'Chế độ phòng thủ${g['release_at'] != null ? ' đến ${Fmt.date(Fmt.parseDate(g['release_at']))}' : ''}' : 'Bình thường', style: TextStyle(fontWeight: FontWeight.w700, fontSize: 16, color: defensive ? c.downText : c.upText))]),
          if (g['reason'] != null) Padding(padding: const EdgeInsets.only(top: 4), child: Text(g['reason'].toString(), style: TextStyle(color: c.muted))),
          const SizedBox(height: 14),
          LimitBar(label: 'Lỗ tuần so với giới hạn', value: (asNum(g['week_pnl_pct']) ?? 0) < 0 ? (asNum(g['week_pnl_pct']) ?? 0).toDouble() : 0, limit: (asNum(lim['weekly_loss_limit_pct']) ?? 3).toDouble(), valueText: '${Fmt.pct(asNum(g['week_pnl_pct']), decimals: 1)} / −${Fmt.num_(asNum(lim['weekly_loss_limit_pct']))}%'),
          const SizedBox(height: 10),
          LimitBar(label: 'Lỗ tháng so với giới hạn', value: (asNum(g['month_pnl_pct']) ?? 0) < 0 ? (asNum(g['month_pnl_pct']) ?? 0).toDouble() : 0, limit: (asNum(lim['monthly_loss_limit_pct']) ?? 6).toDouble(), valueText: '${Fmt.pct(asNum(g['month_pnl_pct']), decimals: 1)} / −${Fmt.num_(asNum(lim['monthly_loss_limit_pct']))}%'),
          const SizedBox(height: 10),
          LimitBar(label: 'Lỗ tối đa nếu mọi mã chạm cắt lỗ', value: (asNum(k['open_risk_pct']) ?? 0).toDouble(), limit: (asNum(lim['monthly_loss_limit_pct']) ?? 6).toDouble(), valueText: '${Fmt.num_(asNum(k['open_risk_pct']))}% / ${Fmt.num_(asNum(lim['monthly_loss_limit_pct']))}%'),
          const SizedBox(height: 12),
          Wrap(spacing: 16, runSpacing: 6, children: [
            LabeledValue('Rủi ro mỗi lệnh', '≤ ${Fmt.num_(asNum(lim['max_risk_per_trade_pct']))}%'), LabeledValue('Tỷ trọng một mã', '≤ ${Fmt.num_(asNum(lim['max_position_pct']), decimals: 0)}%'),
            LabeledValue('Tỷ trọng ngành', '≤ ${Fmt.num_(asNum(lim['max_sector_pct']), decimals: 0)}%'), LabeledValue('Nhóm tương quan', '≤ ${Fmt.num_(asNum(lim['max_correlated_group_pct']), decimals: 0)}%'),
          ]),
          TextButton(onPressed: () => context.push('/account?s=risk'), child: const Text('Sửa giới hạn rủi ro →')),
        ]),
      ).stagger(context, 0),
      SizedBox(height: context.gap),
      AppCard(
        child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
          Text('Kịch bản xấu (theo beta từng mã)', style: Theme.of(context).textTheme.titleMedium),
          const SizedBox(height: 8),
          Row(children: [
            for (final s in asList(k['stress']))
              Expanded(child: Container(margin: const EdgeInsets.only(right: 8), padding: const EdgeInsets.all(10), decoration: BoxDecoration(color: c.surface2, borderRadius: BorderRadius.circular(8)), child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [Text('VN-Index ${s['shock_pct']}%', style: TextStyle(color: c.faint, fontSize: 11.5)), Text(Fmt.money(asNum(s['loss'])), style: TextStyle(color: c.downText, fontWeight: FontWeight.w700, fontSize: 15)), Text('còn ${Fmt.money(asNum(s['nav_after']))}', style: TextStyle(color: c.muted, fontSize: 11.5))]))),
          ]),
        ]),
      ).stagger(context, 1),
      SizedBox(height: context.gap),
      corr.when(
        loading: () => const SkeletonCard(),
        error: (e, _) => const SizedBox.shrink(),
        data: (cr) {
          final groups = asList(cr['groups']);
          return AppCard(
            child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
              Text('Tập trung ẩn (tương quan 60 phiên > 0,8)', style: Theme.of(context).textTheme.titleMedium),
              const SizedBox(height: 8),
              if (groups.isEmpty) Text('Không có nhóm mã tăng giảm cùng nhau vượt ngưỡng.', style: TextStyle(color: c.muted, fontSize: 13)),
              for (final g in groups)
                Container(
                  margin: const EdgeInsets.only(bottom: 8), padding: const EdgeInsets.all(10),
                  decoration: BoxDecoration(borderRadius: BorderRadius.circular(8), border: Border.all(color: g['over_limit'] == true ? c.ref : c.line, width: g['over_limit'] == true ? 1.5 : 1)),
                  child: Row(children: [Expanded(child: Text((g['symbols'] as List).join(', '), style: const TextStyle(fontWeight: FontWeight.w700))), Text('${Fmt.pct(asNum(g['weight_pct']), decimals: 1, sign: false)} · ρ ${Fmt.num_(asNum(g['avg_corr']), decimals: 2)}', style: TextStyle(color: g['over_limit'] == true ? c.ref : c.muted))]),
                ),
            ]),
          );
        },
      ).stagger(context, 2),
      if (pf['uses_margin'] == true) ...[
        SizedBox(height: context.gap),
        margin.when(loading: () => const SkeletonCard(), error: (e, _) => const SizedBox.shrink(), data: (m) => _MarginCard(m: m, id: id)).stagger(context, 3),
      ] else Padding(padding: const EdgeInsets.only(top: 8), child: TextButton.icon(onPressed: () => _MarginCard.edit(context, ref, id, {}), icon: const Icon(Icons.account_balance_outlined, size: 16), label: const Text('Nhập dư nợ ký quỹ cho danh mục này'))),
    ]);
  }
}

class _MarginCard extends ConsumerWidget {
  final Map<String, dynamic> m;
  final String id;
  const _MarginCard({required this.m, required this.id});

  static Future<void> edit(BuildContext context, WidgetRef ref, String id, Map<String, dynamic> s) async {
    final loan = TextEditingController(text: asNum(s['loan'])?.round().toString() ?? ''), call = TextEditingController(text: ((asNum(s['call_ratio']) ?? 0.35) * 100).toStringAsFixed(0)), force = TextEditingController(text: ((asNum(s['force_sell_ratio']) ?? 0.30) * 100).toStringAsFixed(0));
    final ok = await showDialog<bool>(context: context, builder: (ctx) => AlertDialog(title: const Text('Ký quỹ'), content: SizedBox(width: 360, child: Column(mainAxisSize: MainAxisSize.min, children: [TextField(controller: loan, keyboardType: TextInputType.number, decoration: const InputDecoration(labelText: 'Dư nợ ký quỹ (đồng)')), const SizedBox(height: 8), TextField(controller: call, keyboardType: TextInputType.number, decoration: const InputDecoration(labelText: 'Tỷ lệ gọi ký quỹ (%)')), const SizedBox(height: 8), TextField(controller: force, keyboardType: TextInputType.number, decoration: const InputDecoration(labelText: 'Tỷ lệ bán giải chấp (%)'))])), actions: [TextButton(onPressed: () => Navigator.pop(ctx, false), child: const Text('Hủy')), FilledButton(onPressed: () => Navigator.pop(ctx, true), child: const Text('Lưu'))]));
    if (ok != true) return;
    await ref.read(apiProvider).put('/portfolios/$id/margin', data: {'loan': num.tryParse(loan.text.replaceAll('.', '')) ?? 0, 'call_ratio': (num.tryParse(call.text) ?? 35) / 100, 'force_sell_ratio': (num.tryParse(force.text) ?? 30) / 100});
    ref.invalidate(getProvider('/portfolios/$id/margin'));
    ref.invalidate(portfolioProvider(id));
    ref.invalidate(portfoliosProvider);
  }

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final c = context.vn;
    final mt = asMap(m['metrics']);
    final ratio = asNum(mt['margin_ratio']);
    final call = asNum(mt['call_ratio']) ?? 0.35, force = asNum(mt['force_ratio']) ?? 0.30;
    final col = ratio == null ? c.muted : (ratio < force ? c.down : (ratio < call ? const Color(0xFFF08A3D) : c.up));
    return AppCard(
      child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
        Row(children: [Expanded(child: Text('Ký quỹ', style: Theme.of(context).textTheme.titleMedium)), TextButton(onPressed: () => edit(context, ref, id, asMap(m['settings'])), child: const Text('Sửa'))]),
        Wrap(spacing: 16, runSpacing: 6, children: [LabeledValue('Dư nợ', Fmt.money(asNum(mt['loan']))), LabeledValue('Tỷ lệ ký quỹ', ratio == null ? Fmt.dash : '${(ratio * 100).toStringAsFixed(1)}%', color: col), LabeledValue('Gọi ký quỹ / giải chấp', '${(call * 100).toStringAsFixed(0)}% / ${(force * 100).toStringAsFixed(0)}%')]),
        const SizedBox(height: 10),
        if (ratio != null) ClipRRect(borderRadius: BorderRadius.circular(4), child: SizedBox(height: 8, child: Stack(children: [Container(decoration: BoxDecoration(gradient: LinearGradient(colors: [c.down, const Color(0xFFF08A3D), c.up]))), LayoutBuilder(builder: (_, cons) => Positioned(left: (cons.maxWidth * (ratio / 1.0)).clamp(0, cons.maxWidth - 3), child: Container(width: 3, height: 8, color: Colors.white)))]))),
        const SizedBox(height: 10),
        for (final p in asList(mt['positions'])) Padding(padding: const EdgeInsets.symmetric(vertical: 3), child: Row(children: [SizedBox(width: 70, child: Text(p['symbol'].toString(), style: const TextStyle(fontWeight: FontWeight.w700))), Expanded(child: Text('gọi ký quỹ tại ${Fmt.price(asNum(p['call_price']))} · giải chấp tại ${Fmt.price(asNum(p['force_price']))}', style: TextStyle(color: c.muted, fontSize: 12.5)))])),
        const Divider(),
        for (final s in asList(mt['scenarios'])) Padding(padding: const EdgeInsets.symmetric(vertical: 3), child: Row(children: [SizedBox(width: 110, child: Text('VN-Index ${s['shock_pct']}%')), Expanded(child: Text('${s['margin_call'] == true ? 'Bị gọi ký quỹ, nộp thêm ${Fmt.money(asNum(s['cash_needed']))}' : 'An toàn'} · tỷ lệ ${s['margin_ratio'] != null ? '${((asNum(s['margin_ratio']) ?? 0) * 100).toStringAsFixed(1)}%' : '—'}', style: TextStyle(color: s['margin_call'] == true ? c.downText : c.muted, fontSize: 12.5)))])),
      ]),
    );
  }
}

class _HistoryTab extends ConsumerWidget {
  final String id;
  const _HistoryTab({required this.id});
  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final c = context.vn;
    final tx = ref.watch(getMapProvider('/portfolios/$id/transactions?size=100'));
    return Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
      Row(children: [
        OutlinedButton.icon(
          onPressed: () async {
            final picked = await FilePicker.pickFiles(type: FileType.custom, allowedExtensions: ['csv', 'xlsx']);
            if (picked.isEmpty) return;
            try {
              final bytes = await picked.first.xFile.readAsBytes();
              final res = asMap(await ref.read(apiProvider).upload('/portfolios/$id/import', bytes, picked.first.name));
              ref.invalidate(getProvider('/portfolios/$id/transactions?size=100'));
              ref.invalidate(portfolioProvider(id));
              if (context.mounted) showToast(context, 'Đã nhập ${res['imported']} giao dịch${asList(res['errors']).isNotEmpty ? ', ${asList(res['errors']).length} dòng lỗi' : ''}');
            } on ApiException catch (e) {
              if (context.mounted) showToast(context, e.message, error: true);
            }
          },
          icon: const Icon(Icons.upload_file, size: 18), label: const Text('Nhập sao kê CSV/XLSX'),
        ),
        const SizedBox(width: 8),
        Expanded(child: Text('Cột: ngày, mã, mua/bán, khối lượng, giá, phí, thuế', style: TextStyle(color: c.faint, fontSize: 11.5))),
      ]),
      const SizedBox(height: 10),
      tx.when(
        loading: () => const SkeletonList(),
        error: (e, _) => ErrorBox(e),
        data: (d) {
          final rows = asList(d['items']);
          if (rows.isEmpty) return const EmptyState(icon: Icons.receipt_long_outlined, message: 'Chưa có giao dịch nào.');
          return AppCard(
            padding: const EdgeInsets.symmetric(horizontal: 12),
            child: Column(children: [
              for (final t in rows)
                ListTile(
                  dense: true, contentPadding: EdgeInsets.zero,
                  leading: Pill({'BUY': 'Mua', 'SELL': 'Bán', 'DEPOSIT': 'Nộp', 'WITHDRAW': 'Rút', 'DIVIDEND': 'Cổ tức'}[t['side']] ?? t['side'].toString(), color: t['side'] == 'BUY' ? c.up : (t['side'] == 'SELL' ? c.down : c.muted)),
                  title: Text(t['symbol'] != null ? '${t['symbol']} · ${Fmt.price(asNum(t['quantity']))} × ${Fmt.price(asNum(t['price']))}' : Fmt.money(asNum(t['amount']), full: true), style: const TextStyle(fontSize: 13.5, fontWeight: FontWeight.w600)),
                  subtitle: Text('${Fmt.date(Fmt.parseDate(t['trade_date']), year: true)}${t['reason'] != null ? ' · ${t['reason']}' : ''}${t['note'] != null ? ' · ${t['note']}' : ''}', style: TextStyle(fontSize: 11.5, color: c.faint)),
                  trailing: Row(mainAxisSize: MainAxisSize.min, children: [
                    Text(Fmt.money(asNum(t['amount'])), style: TextStyle(color: c.changeColor(asNum(t['amount'])), fontWeight: FontWeight.w600)),
                    IconButton(icon: const Icon(Icons.delete_outline, size: 18), onPressed: () async {
                      if (await confirmDialog(context, title: 'Xóa giao dịch?', message: 'Vị thế và tiền mặt sẽ được tính lại.', confirmLabel: 'Xóa', danger: true)) {
                        await ref.read(apiProvider).delete('/portfolios/$id/transactions/${t['id']}');
                        ref.invalidate(getProvider('/portfolios/$id/transactions?size=100'));
                        ref.invalidate(portfolioProvider(id));
                      }
                    }),
                  ]),
                ),
            ]),
          );
        },
      ),
    ]);
  }
}

class _PerfTab extends ConsumerWidget {
  final String id;
  final Map<String, dynamic> d;
  const _PerfTab({required this.id, required this.d});
  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final c = context.vn;
    final b = ref.watch(getMapProvider('/portfolios/$id/benchmark?days=180'));
    return b.when(
      loading: () => const SkeletonCard(lines: 6),
      error: (e, _) => ErrorBox(e),
      data: (bm) {
        final series = asList(bm['series']);
        return Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
          Row(children: [
            Expanded(child: KpiTile(label: 'Danh mục (180 ngày)', value: Fmt.pct(asNum(bm['portfolio_pct'])), valueColor: c.changeColor(asNum(bm['portfolio_pct'])))),
            const SizedBox(width: 10),
            Expanded(child: KpiTile(label: 'VN-Index', value: Fmt.pct(asNum(bm['vnindex_pct'])), valueColor: c.changeColor(asNum(bm['vnindex_pct'])))),
            const SizedBox(width: 10),
            Expanded(child: KpiTile(label: 'Gửi tiết kiệm', value: Fmt.pct(asNum(bm['savings_pct'])))),
            const SizedBox(width: 10),
            Expanded(child: KpiTile(label: 'Sharpe · sụt giảm tối đa', value: '${Fmt.num_(asNum(bm['sharpe']), decimals: 2)} · ${Fmt.pct(asNum(bm['max_drawdown_pct']), decimals: 1)}')),
          ]),
          SizedBox(height: context.gap),
          AppCard(
            child: SizedBox(
              height: 260,
              child: series.length < 2
                  ? Center(child: Text('Cần ít nhất 2 phiên có giao dịch để vẽ hiệu suất.', style: TextStyle(color: c.muted)))
                  : LineChart(LineChartData(
                      gridData: FlGridData(show: true, drawVerticalLine: false, getDrawingHorizontalLine: (_) => FlLine(color: c.lineSoft, strokeWidth: 1)),
                      titlesData: FlTitlesData(topTitles: const AxisTitles(), rightTitles: const AxisTitles(), leftTitles: AxisTitles(sideTitles: SideTitles(showTitles: true, reservedSize: 44, getTitlesWidget: (v, _) => Text('${v.toStringAsFixed(0)}%', style: TextStyle(fontSize: 10, color: c.faint)))), bottomTitles: AxisTitles(sideTitles: SideTitles(showTitles: true, interval: (series.length / 5).ceilToDouble(), getTitlesWidget: (v, _) => v.toInt() < series.length ? Text(Fmt.date(Fmt.parseDate(series[v.toInt()]['date'])), style: TextStyle(fontSize: 10, color: c.faint)) : const SizedBox()))),
                      borderData: FlBorderData(show: false),
                      lineBarsData: [
                        LineChartBarData(spots: [for (final (i, s) in series.indexed) FlSpot(i.toDouble(), (asNum(s['portfolio']) ?? 0).toDouble())], color: c.accent, barWidth: 2, dotData: const FlDotData(show: false), belowBarData: BarAreaData(show: true, color: c.accent.withValues(alpha: 0.12))),
                        LineChartBarData(spots: [for (final (i, s) in series.indexed) if (s['vnindex'] != null) FlSpot(i.toDouble(), (asNum(s['vnindex']) ?? 0).toDouble())], color: c.ref, barWidth: 1.5, dotData: const FlDotData(show: false)),
                      ],
                      lineTouchData: LineTouchData(touchTooltipData: LineTouchTooltipData(getTooltipItems: (spots) => [for (final s in spots) LineTooltipItem('${s.barIndex == 0 ? 'Danh mục' : 'VN-Index'} ${Fmt.pct(s.y)}', TextStyle(color: s.barIndex == 0 ? c.link : c.ref, fontSize: 12))])),
                    )),
            ),
          ),
          Padding(padding: const EdgeInsets.only(top: 6), child: Row(children: [Container(width: 14, height: 3, color: c.accent), const SizedBox(width: 4), const Text('Danh mục', style: TextStyle(fontSize: 11)), const SizedBox(width: 12), Container(width: 14, height: 3, color: c.ref), const SizedBox(width: 4), const Text('VN-Index', style: TextStyle(fontSize: 11))])),
          const SizedBox(height: 8),
          TextButton.icon(onPressed: () => showSymbolSearch(context), icon: const Icon(Icons.search, size: 16), label: const Text('Tìm mã để so sánh')),
        ]);
      },
    );
  }
}
