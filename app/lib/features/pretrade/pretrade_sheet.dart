import 'dart:async';

import 'package:flutter/material.dart';
import 'package:flutter_animate/flutter_animate.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:go_router/go_router.dart';

import '../../core/api.dart';
import '../../core/format.dart';
import '../../core/providers.dart';
import '../../core/responsive.dart';
import '../../core/theme.dart';
import '../../shared/widgets/common.dart';

/// Every "Mua" path opens this. Dialog on desktop, bottom sheet on phone.
Future<bool?> showPretradeSheet(BuildContext context, {required String symbol, String? horizon, String? portfolioId, int? quantity, num? price, num? stopLoss, num? takeProfit, String? planId, int? planSeq}) {
  final body = PretradeSheet(symbol: symbol, horizon: horizon, portfolioId: portfolioId, quantity: quantity, price: price, stopLoss: stopLoss, takeProfit: takeProfit, planId: planId, planSeq: planSeq);
  if (context.isDesktop) {
    return showDialog<bool>(context: context, builder: (_) => Dialog(insetPadding: const EdgeInsets.all(24), child: ConstrainedBox(constraints: const BoxConstraints(maxWidth: 960, maxHeight: 720), child: body)));
  }
  return showModalBottomSheet<bool>(context: context, isScrollControlled: true, useSafeArea: true, builder: (_) => DraggableScrollableSheet(expand: false, initialChildSize: 0.95, maxChildSize: 0.97, builder: (_, __) => body));
}

class PretradeSheet extends ConsumerStatefulWidget {
  final String symbol;
  final String? horizon, portfolioId, planId;
  final int? quantity, planSeq;
  final num? price, stopLoss, takeProfit;
  const PretradeSheet({super.key, required this.symbol, this.horizon, this.portfolioId, this.quantity, this.price, this.stopLoss, this.takeProfit, this.planId, this.planSeq});
  @override
  ConsumerState<PretradeSheet> createState() => _PretradeSheetState();
}

class _PretradeSheetState extends ConsumerState<PretradeSheet> {
  Map<String, dynamic>? res;
  String? err;
  String? pfId;
  late String hz = widget.horizon ?? 'MID';
  final qty = TextEditingController(), price = TextEditingController(), stop = TextEditingController(), tp = TextEditingController(), reason = TextEditingController();
  Timer? _deb;
  bool _busy = false, _saving = false, _done = false;
  List<Map<String, dynamic>> portfolios = [];

  @override
  void initState() {
    super.initState();
    pfId = widget.portfolioId;
    if (widget.quantity != null) qty.text = widget.quantity.toString();
    if (widget.price != null) price.text = widget.price!.round().toString();
    if (widget.stopLoss != null) stop.text = widget.stopLoss!.round().toString();
    if (widget.takeProfit != null) tp.text = widget.takeProfit!.round().toString();
    _init();
  }

  Future<void> _init() async {
    try {
      portfolios = asList(await ref.read(apiProvider).get('/portfolios'));
      pfId ??= (portfolios.where((p) => p['is_paper'] != true).firstOrNull ?? portfolios.firstOrNull)?['id'];
    } catch (_) {}
    await _check(save: false);
  }

  Map<String, dynamic> _body(bool save) => {
        'symbol': widget.symbol, 'portfolio_id': pfId, 'horizon': hz, 'save': save,
        if (qty.text.isNotEmpty) 'quantity': int.tryParse(qty.text.replaceAll('.', '')),
        if (price.text.isNotEmpty) 'price': num.tryParse(price.text.replaceAll('.', '')),
        if (stop.text.isNotEmpty) 'stop_loss': num.tryParse(stop.text.replaceAll('.', '')),
        if (tp.text.isNotEmpty) 'take_profit': num.tryParse(tp.text.replaceAll('.', '')),
        if (save && reason.text.trim().isNotEmpty) 'override_reason': reason.text.trim(),
      };

  @override
  void dispose() {
    _deb?.cancel();
    super.dispose();
  }

  Future<void> _check({bool save = false}) async {
    if (!mounted) return;
    setState(() {
      _busy = true;
      err = null;
    });
    try {
      final r = asMap(await ref.read(apiProvider).post('/pretrade-check', data: _body(save)));
      if (!mounted) return;
      setState(() {
        res = r;
        if (qty.text.isEmpty) qty.text = r['quantity'].toString();
        if (price.text.isEmpty) price.text = r['price'].toString();
        if (stop.text.isEmpty) stop.text = r['stop_loss'].toString();
        if (tp.text.isEmpty) tp.text = r['take_profit'].toString();
      });
    } on ApiException catch (e) {
      if (mounted) setState(() => err = e.message);
    } finally {
      if (mounted) setState(() => _busy = false);
    }
  }

  void refresh() => setState(() {});

  void _recalc() {
    _deb?.cancel();
    _deb = Timer(400.ms, () => _check(save: false));
  }

  Future<void> _confirm(int quantity) async {
    if (pfId == null) {
      showToast(context, 'Hãy tạo một danh mục trước khi ghi lệnh', error: true, actionLabel: 'Tạo', onAction: () => context.push('/portfolio'));
      return;
    }
    setState(() => _saving = true);
    try {
      final api = ref.read(apiProvider);
      final saved = asMap(await api.post('/pretrade-check', data: {..._body(true), 'quantity': quantity}));
      final r = asMap(await api.post('/portfolios/$pfId/transactions', data: {
        'side': 'BUY', 'symbol': widget.symbol, 'quantity': quantity, 'price': num.tryParse(price.text.replaceAll('.', '')), 'stop_loss': num.tryParse(stop.text.replaceAll('.', '')),
        'take_profit': num.tryParse(tp.text.replaceAll('.', '')), 'pretrade_check_id': saved['check_id'], 'reason': reason.text.trim().isEmpty ? null : reason.text.trim(),
        if (widget.planId != null) 'plan_id': widget.planId, if (widget.planSeq != null) 'plan_seq': widget.planSeq,
      }));
      ref.invalidate(getProvider);
      if (!mounted) return;
      setState(() => _done = true);
      showToast(context, '${r['message']}. ${r['reminder'] ?? ''}'.trim());
    } on ApiException catch (e) {
      if (mounted) showToast(context, e.message, error: true);
    } finally {
      if (mounted) setState(() => _saving = false);
    }
  }

  @override
  Widget build(BuildContext context) {
    final c = context.vn;
    final desktop = context.isDesktop;
    final r = res;
    final head = Padding(
      padding: const EdgeInsets.fromLTRB(20, 16, 12, 8),
      child: Row(children: [
        Expanded(child: Text('Kiểm tra trước khi mua · ${widget.symbol}${r?['name'] != null ? ' · ${r!['name']}' : ''}', style: Theme.of(context).textTheme.titleLarge)),
        IconButton(onPressed: () => Navigator.pop(context, _done), icon: const Icon(Icons.close)),
      ]),
    );
    if (_done) {
      return Column(mainAxisSize: MainAxisSize.min, children: [
        head,
        Padding(
          padding: const EdgeInsets.all(24),
          child: Column(mainAxisSize: MainAxisSize.min, children: [
            Icon(Icons.check_circle, color: c.up, size: 56).animate().scale(duration: 400.ms, curve: Curves.elasticOut),
            const SizedBox(height: 12),
            Text('Đã ghi lệnh mua ${widget.symbol}', style: Theme.of(context).textTheme.titleMedium),
            const SizedBox(height: 6),
            Text('Nhớ đặt lệnh dừng lỗ tại ${Fmt.price(num.tryParse(stop.text))} ở công ty chứng khoán.', style: TextStyle(color: c.muted)),
            const SizedBox(height: 18),
            Wrap(spacing: 10, children: [
              FilledButton(onPressed: () {
                Navigator.pop(context, true);
                context.push(pfId != null ? '/portfolio/$pfId/plans/${widget.symbol}' : '/plans/${widget.symbol}');
              }, child: const Text('Lập kế hoạch nếu–thì')),
              OutlinedButton(onPressed: () {
                Navigator.pop(context, true);
                context.go('/portfolio${pfId != null ? '/$pfId' : ''}');
              }, child: const Text('Xem danh mục')),
            ]),
          ]),
        ),
      ]);
    }
    final form = _Form(this);
    final result = _Result(this);
    return Column(children: [
      head,
      Expanded(
        child: SingleChildScrollView(
          padding: const EdgeInsets.fromLTRB(20, 0, 20, 20),
          child: desktop ? Row(crossAxisAlignment: CrossAxisAlignment.start, children: [Expanded(flex: 4, child: form), const SizedBox(width: 20), Expanded(flex: 5, child: result)]) : Column(children: [result, const SizedBox(height: 16), form]),
        ),
      ),
      Container(
        padding: const EdgeInsets.fromLTRB(20, 10, 20, 16),
        decoration: BoxDecoration(border: Border(top: BorderSide(color: c.line))),
        child: _Actions(this),
      ),
    ]);
  }
}

class _Form extends StatelessWidget {
  final _PretradeSheetState s;
  const _Form(this.s);
  @override
  Widget build(BuildContext context) {
    final c = context.vn;
    final r = s.res ?? {};
    Widget numField(String label, TextEditingController ctl, {int step = 100, String? help}) => Row(children: [
          Expanded(child: TextField(controller: ctl, keyboardType: TextInputType.number, decoration: InputDecoration(labelText: label, helperText: help), onChanged: (_) => s._recalc())),
          const SizedBox(width: 4),
          IconButton(onPressed: () {
            final v = (num.tryParse(ctl.text.replaceAll('.', '')) ?? 0) - step;
            ctl.text = (v < 0 ? 0 : v).round().toString();
            s._recalc();
          }, icon: const Icon(Icons.remove_circle_outline, size: 20)),
          IconButton(onPressed: () {
            ctl.text = ((num.tryParse(ctl.text.replaceAll('.', '')) ?? 0) + step).round().toString();
            s._recalc();
          }, icon: const Icon(Icons.add_circle_outline, size: 20)),
        ]);
    final tick = (asInt(r['tick']) ?? 100).clamp(10, 100);
    final orderValue = (num.tryParse(s.qty.text) ?? 0) * (num.tryParse(s.price.text) ?? 0);
    final maxLoss = asNum(r['max_loss']);
    return AppCard(
      child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
        Text('Lệnh dự kiến', style: Theme.of(context).textTheme.titleMedium),
        const SizedBox(height: 10),
        DropdownButtonFormField<String>(
          initialValue: s.pfId,
          decoration: const InputDecoration(labelText: 'Danh mục'),
          items: [for (final p in s.portfolios) DropdownMenuItem(value: p['id'].toString(), child: Text('${p['name']} · ${p['label']} · ${Fmt.money(asNum(p['nav']))}'))],
          onChanged: (v) {
            s.pfId = v;
            s._recalc();
          },
        ),
        if (s.portfolios.isEmpty) Padding(padding: const EdgeInsets.only(top: 6), child: Text('Chưa có danh mục. Kết quả dưới đây tính theo vốn ${Fmt.money(asNum(r['equity']))}${r['equity_is_default'] == true ? ' (mặc định minh họa)' : ''}.', style: TextStyle(color: c.ref, fontSize: 12))),
        const SizedBox(height: 10),
        Segmented<String>(options: const [('SHORT', 'Ngắn hạn'), ('MID', 'Trung hạn'), ('LONG', 'Dài hạn')], value: s.hz, onChanged: (v) {
          s.hz = v;
          s._recalc();
        }),
        const SizedBox(height: 12),
        numField('Khối lượng (bước 100)', s.qty, step: 100),
        numField('Giá mua', s.price, step: tick, help: r['ceiling'] != null ? 'Biên độ ${Fmt.price(asNum(r['floor']))} – ${Fmt.price(asNum(r['ceiling']))}' : null),
        numField('Cắt lỗ', s.stop, step: tick),
        numField('Mục tiêu (chốt lời 1)', s.tp, step: tick),
        const Divider(height: 20),
        Row(children: [
          Expanded(child: LabeledValue('Giá trị lệnh', Fmt.money(orderValue))),
          Expanded(child: LabeledValue('Có thể lỗ nếu chạm cắt lỗ', maxLoss == null ? Fmt.dash : '${Fmt.money(maxLoss)} (${Fmt.pct(asNum(r['risk_pct']), decimals: 2, sign: false)})', color: c.downText)),
          Expanded(child: LabeledValue('Lãi / lỗ kỳ vọng', Fmt.ratio(asNum(r['risk_reward'])))),
        ]),
      ]),
    );
  }
}

class _Result extends StatelessWidget {
  final _PretradeSheetState s;
  const _Result(this.s);
  @override
  Widget build(BuildContext context) {
    final c = context.vn;
    final r = s.res;
    if (s.err != null) return ErrorBox(s.err!, onRetry: () => s._check());
    if (r == null) return const SkeletonCard(lines: 6);
    final level = r['result']?.toString();
    final col = c.levelColor(level);
    final rel = asMap(r['reliability']);
    return AnimatedOpacity(
      opacity: s._busy ? 0.6 : 1,
      duration: 200.ms,
      child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
        Container(
          width: double.infinity, padding: const EdgeInsets.all(14),
          decoration: BoxDecoration(color: col.withValues(alpha: 0.14), borderRadius: BorderRadius.circular(12), border: Border.all(color: col)),
          child: Row(children: [
            Icon(level == 'GREEN' ? Icons.check_circle : (level == 'YELLOW' ? Icons.warning_amber_rounded : Icons.block), color: col, size: 30),
            const SizedBox(width: 12),
            Expanded(child: Text(r['headline']?.toString() ?? '', style: TextStyle(color: c.text, fontWeight: FontWeight.w600, fontSize: 14.5))),
          ]),
        ).animate(key: ValueKey(level)).fadeIn(duration: 250.ms).scale(begin: const Offset(0.98, 0.98)),
        const SizedBox(height: 12),
        AppCard(
          padding: const EdgeInsets.symmetric(horizontal: 12, vertical: 6),
          child: Column(children: [
            for (final it in asList(r['items']))
              Padding(
                padding: const EdgeInsets.symmetric(vertical: 7),
                child: Row(crossAxisAlignment: CrossAxisAlignment.start, children: [
                  Icon(it['level'] == 'GREEN' ? Icons.check_circle_outline : (it['level'] == 'YELLOW' ? Icons.error_outline : Icons.cancel_outlined), size: 18, color: c.levelColor(it['level']?.toString())),
                  const SizedBox(width: 10),
                  Expanded(flex: 3, child: Text(it['name'].toString(), style: const TextStyle(fontSize: 13))),
                  Expanded(flex: 3, child: Text(it['value']?.toString() ?? '', textAlign: TextAlign.right, style: TextStyle(fontWeight: FontWeight.w600, fontSize: 13, color: c.levelColor(it['level']?.toString())))),
                  Expanded(flex: 2, child: Text(it['limit']?.toString() ?? '', textAlign: TextAlign.right, style: TextStyle(fontSize: 12, color: c.faint))),
                ]),
              ),
          ]),
        ),
        const SizedBox(height: 10),
        Wrap(spacing: 16, runSpacing: 8, children: [
          LabeledValue('Khối lượng gợi ý', Fmt.qty(asNum(r['suggested_qty']))),
          LabeledValue('Độ tin cậy tín hiệu', rel['win_rate'] != null ? 'đúng ${Fmt.num_(asNum(rel['win_rate']), decimals: 0)}% (${rel['samples']} lần)' : 'chưa đủ mẫu'),
          LabeledValue('Thị trường', regimeLabel(r['regime']?.toString()), color: c.regimeColor(r['regime']?.toString())),
        ]),
        if (level == 'RED' && r['can_override'] == true) ...[
          const SizedBox(height: 12),
          TextField(controller: s.reason, minLines: 2, maxLines: 3, decoration: const InputDecoration(labelText: 'Lý do vẫn muốn mua (ít nhất 10 ký tự, ghi vào nhật ký kỷ luật)'), onChanged: (_) => s.refresh()),
        ],
      ]),
    );
  }

  String regimeLabel(String? r) => {'UPTREND': 'Tăng', 'PRESSURE': 'Chịu áp lực', 'CORRECTION': 'Điều chỉnh', 'DOWNTREND': 'Giảm'}[r] ?? '—';
}

class _Actions extends StatelessWidget {
  final _PretradeSheetState s;
  const _Actions(this.s);
  @override
  Widget build(BuildContext context) {
    final r = s.res;
    if (r == null) return const SizedBox(height: 40);
    final level = r['result']?.toString();
    final suggested = asInt(r['suggested_qty']) ?? 0;
    final entered = int.tryParse(s.qty.text.replaceAll('.', '')) ?? suggested;
    final red = level == 'RED';
    final reasonOk = s.reason.text.trim().length >= 10;
    final canOverride = r['can_override'] == true;
    return Wrap(alignment: WrapAlignment.end, spacing: 10, runSpacing: 8, children: [
      OutlinedButton(onPressed: () => Navigator.pop(context, false), child: const Text('Hủy')),
      if (!red) ...[
        if (suggested > 0 && suggested != entered) OutlinedButton(onPressed: s._saving ? null : () => s._confirm(suggested), child: Text('Ghi lệnh ${Fmt.qty(suggested)} theo gợi ý')),
        FilledButton(onPressed: s._saving || entered <= 0 ? null : () => s._confirm(entered), child: s._saving ? const SizedBox(width: 18, height: 18, child: CircularProgressIndicator(strokeWidth: 2, color: Colors.white)) : Text('Mua ${Fmt.qty(entered)}')),
      ] else
        FilledButton(
          style: FilledButton.styleFrom(backgroundColor: context.vn.down),
          onPressed: canOverride && reasonOk && !s._saving ? () => s._confirm(entered) : null,
          child: Text(canOverride ? 'Vẫn ghi lệnh (ghi lý do)' : 'Không thể mua: chế độ phòng thủ'),
        ),
    ]);
  }
}
