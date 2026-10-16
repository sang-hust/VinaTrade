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
import '../pretrade/pretrade_sheet.dart';

final _plansProvider = FutureProvider.autoDispose.family<List<Map<String, dynamic>>, (String, String?)>((ref, k) async => asList(await ref.watch(apiProvider).get('/trade-plans', query: {'symbol': k.$1, if (k.$2 != null) 'portfolio_id': k.$2, 'status': 'ACTIVE'})));

const _paramVi = {'breakout': 'Giá phá nền', 'pullback': 'Giá hồi về', 'entry': 'Giá vốn / vào lệnh', 'stop': 'Cắt lỗ', 'support': 'Vùng hỗ trợ', 'tp1': 'Chốt lời 1', 'tp2': 'Chốt lời 2'};

class PlanPage extends ConsumerWidget {
  final String? portfolioId;
  final String symbol;
  const PlanPage({super.key, required this.portfolioId, required this.symbol});

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final c = context.vn;
    final plans = ref.watch(_plansProvider((symbol, portfolioId)));
    final analysis = ref.watch(getMapProvider('/stocks/$symbol/analysis'));
    return PageBody(
      maxWidth: 980,
      child: ListView(children: [
        Row(children: [IconButton(onPressed: () => context.canPop() ? context.pop() : context.go('/portfolio'), icon: const Icon(Icons.arrow_back)), Expanded(child: Text('Kế hoạch nếu–thì · $symbol', style: Theme.of(context).textTheme.titleLarge)), TextButton(onPressed: () => context.push('/stocks/$symbol'), child: const Text('Xem phân tích'))]),
        const SizedBox(height: 10),
        plans.when(
          loading: () => const SkeletonList(count: 2),
          error: (e, _) => ErrorBox(e),
          data: (list) => list.isEmpty
              ? analysis.when(loading: () => const SkeletonCard(), error: (e, _) => _Templates(symbol: symbol, portfolioId: portfolioId, plan: const {}), data: (a) => _Templates(symbol: symbol, portfolioId: portfolioId, plan: asMap(a['plan'])))
              : Column(children: [for (final (i, p) in list.indexed) Padding(padding: const EdgeInsets.only(bottom: 16), child: _PlanCard(p: p, portfolioId: portfolioId).stagger(context, i))]),
        ),
        AppCard(color: c.riskBg, borderColor: c.riskBorder, child: Row(children: [Icon(Icons.info_outline, color: c.risk), const SizedBox(width: 10), Expanded(child: Text('Vinatrade chỉ nhắc đúng bước. Hãy đặt lệnh điều kiện (dừng lỗ, chốt lời) ngay tại công ty chứng khoán để không bỏ lỡ.', style: TextStyle(color: c.text, fontSize: 13)))])),
      ]),
    );
  }
}

class _Templates extends ConsumerStatefulWidget {
  final String symbol;
  final String? portfolioId;
  final Map<String, dynamic> plan;
  const _Templates({required this.symbol, required this.portfolioId, required this.plan});
  @override
  ConsumerState<_Templates> createState() => _TemplatesState();
}

class _TemplatesState extends ConsumerState<_Templates> {
  String? code;
  final Map<String, TextEditingController> ctls = {};
  bool busy = false;

  @override
  Widget build(BuildContext context) {
    final c = context.vn;
    final tpls = ref.watch(getListProvider('/trade-plans/templates'));
    final plan = widget.plan;
    final entry = plan['entry'] as List? ?? [];
    final tp = plan['take_profit'] as List? ?? [];
    final defaults = {'breakout': entry.length > 1 ? entry[1] : null, 'pullback': entry.isNotEmpty ? entry[0] : null, 'entry': entry.length > 1 ? entry[1] : null, 'stop': plan['stop_loss'], 'support': entry.isNotEmpty ? entry[0] : null, 'tp1': tp.isNotEmpty ? tp[0] : null, 'tp2': tp.length > 1 ? tp[1] : null};
    return tpls.when(
      loading: () => const SkeletonCard(),
      error: (e, _) => ErrorBox(e),
      data: (list) {
        final sel = list.where((t) => t['code'] == code).firstOrNull;
        return AppCard(
          child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
            Text('Chọn mẫu kế hoạch', style: Theme.of(context).textTheme.titleMedium),
            Text('Các mức giá được điền sẵn từ kế hoạch giao dịch của hệ thống, bạn sửa lại được.', style: TextStyle(color: c.muted, fontSize: 12.5)),
            const SizedBox(height: 10),
            Wrap(spacing: 8, runSpacing: 8, children: [
              for (final t in list)
                ChoiceChip(label: Text(t['name'].toString()), selected: code == t['code'], selectedColor: c.accent, labelStyle: TextStyle(color: code == t['code'] ? Colors.white : c.text), onSelected: (_) => setState(() {
                  code = t['code'];
                  for (final p in (t['params'] as List)) {
                    ctls.putIfAbsent(p.toString(), () => TextEditingController(text: asNum(defaults[p])?.round().toString() ?? ''));
                  }
                })),
            ]),
            if (sel != null) ...[
              const SizedBox(height: 12),
              Wrap(spacing: 10, runSpacing: 10, children: [for (final p in (sel['params'] as List)) SizedBox(width: 200, child: TextField(controller: ctls[p.toString()], keyboardType: TextInputType.number, decoration: InputDecoration(labelText: _paramVi[p] ?? p.toString())))]),
              const SizedBox(height: 12),
              FilledButton(
                onPressed: busy ? null : () async {
                  setState(() => busy = true);
                  try {
                    await ref.read(apiProvider).post('/trade-plans', query: {if (widget.portfolioId != null) 'portfolio_id': widget.portfolioId}, data: {'symbol': widget.symbol, 'template': code, 'params': {for (final p in (sel['params'] as List)) p.toString(): num.tryParse(ctls[p.toString()]!.text.replaceAll('.', ''))}});
                    ref.invalidate(_plansProvider);
                    if (mounted) showToast(context, 'Đã tạo kế hoạch ${sel['name']}');
                  } on ApiException catch (e) {
                    if (mounted) showToast(context, e.message, error: true);
                  } finally {
                    if (mounted) setState(() => busy = false);
                  }
                },
                child: const Text('Tạo kế hoạch'),
              ),
            ],
          ]),
        );
      },
    );
  }
}

class _PlanCard extends ConsumerWidget {
  final Map<String, dynamic> p;
  final String? portfolioId;
  const _PlanCard({required this.p, required this.portfolioId});

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final c = context.vn;
    final steps = asList(p['steps']);
    final api = ref.read(apiProvider);
    Future<void> refresh() async => ref.invalidate(_plansProvider);
    return AppCard(
      child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
        Row(children: [
          Expanded(child: Text(p['name'].toString(), style: Theme.of(context).textTheme.titleMedium)),
          Pill(p['status'] == 'ACTIVE' ? 'Đang theo dõi' : p['status'].toString(), color: p['status'] == 'ACTIVE' ? c.up : c.muted),
          PopupMenuButton<String>(
            onSelected: (v) async {
              if (v == 'delete') {
                if (await confirmDialog(context, title: 'Xóa kế hoạch?', message: 'Các bước chưa làm sẽ không được nhắc nữa.', confirmLabel: 'Xóa', danger: true)) {
                  await api.delete('/trade-plans/${p['id']}');
                  await refresh();
                }
              } else {
                await api.put('/trade-plans/${p['id']}', query: {'status': v});
                await refresh();
              }
            },
            itemBuilder: (_) => [if (p['status'] == 'ACTIVE') const PopupMenuItem(value: 'PAUSED', child: Text('Tạm dừng')) else const PopupMenuItem(value: 'ACTIVE', child: Text('Kích hoạt lại')), const PopupMenuItem(value: 'delete', child: Text('Xóa kế hoạch'))],
          ),
        ]),
        const SizedBox(height: 12),
        for (final (i, s) in steps.indexed)
          IntrinsicHeight(
            child: Row(crossAxisAlignment: CrossAxisAlignment.stretch, children: [
              Column(children: [
                Container(
                  width: 26, height: 26,
                  decoration: BoxDecoration(shape: BoxShape.circle, color: s['status'] == 'DONE' ? c.up : (s['status'] == 'TRIGGERED' ? c.ref : (s['status'] == 'SKIPPED' ? c.surface2 : c.surface2)), border: Border.all(color: s['status'] == 'WAITING' ? c.line : Colors.transparent)),
                  child: Center(child: s['status'] == 'DONE' ? const Icon(Icons.check, size: 16, color: Colors.white) : Text('${s['seq']}', style: TextStyle(fontSize: 12, fontWeight: FontWeight.w700, color: s['status'] == 'TRIGGERED' ? Colors.black : c.muted))),
                ),
                if (i < steps.length - 1) Expanded(child: Container(width: 2, color: c.lineSoft)),
              ]),
              const SizedBox(width: 12),
              Expanded(
                child: Padding(
                  padding: const EdgeInsets.only(bottom: 14),
                  child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
                    Text(s['title'].toString(), style: TextStyle(fontWeight: FontWeight.w600, fontSize: 13.5, color: s['status'] == 'SKIPPED' ? c.faint : c.text, decoration: s['status'] == 'SKIPPED' ? TextDecoration.lineThrough : null)),
                    Text({'WAITING': 'Chưa tới', 'TRIGGERED': 'Điều kiện đã xảy ra — làm ngay', 'DONE': 'Đã làm ${Fmt.relative(Fmt.parseDate(s['done_at']))}', 'SKIPPED': 'Bỏ qua'}[s['status']] ?? '', style: TextStyle(color: s['status'] == 'TRIGGERED' ? c.ref : c.faint, fontSize: 11.5)),
                    if (s['status'] == 'TRIGGERED' || s['status'] == 'WAITING')
                      Padding(
                        padding: const EdgeInsets.only(top: 6),
                        child: Wrap(spacing: 6, children: [
                          if (s['action'] == 'BUY') FilledButton(style: FilledButton.styleFrom(visualDensity: VisualDensity.compact), onPressed: () => showPretradeSheet(context, symbol: p['symbol'], portfolioId: portfolioId, price: asNum(s['price']), planId: p['id'], planSeq: asInt(s['seq'])), child: const Text('Kiểm tra trước khi mua', style: TextStyle(fontSize: 12)))
                          else OutlinedButton(style: OutlinedButton.styleFrom(visualDensity: VisualDensity.compact), onPressed: () async {
                            await api.put('/trade-plans/${p['id']}/steps/${s['seq']}', data: {'status': 'DONE'});
                            await refresh();
                          }, child: const Text('Đánh dấu đã làm', style: TextStyle(fontSize: 12))),
                          TextButton(style: TextButton.styleFrom(visualDensity: VisualDensity.compact), onPressed: () async {
                            await api.put('/trade-plans/${p['id']}/steps/${s['seq']}', data: {'status': 'SKIPPED'});
                            await refresh();
                          }, child: const Text('Bỏ qua', style: TextStyle(fontSize: 12))),
                        ]),
                      ),
                  ]),
                ),
              ),
            ]),
          ).animate().fadeIn(delay: (i * 60).ms),
        TextButton.icon(
          onPressed: () async {
            final title = TextEditingController(), value = TextEditingController();
            String field = 'price', op = '>=', action = 'SELL';
            final ok = await showDialog<bool>(context: context, builder: (ctx) => StatefulBuilder(builder: (ctx, set) => AlertDialog(title: const Text('Thêm bước'), content: SizedBox(width: 380, child: Column(mainAxisSize: MainAxisSize.min, children: [
              TextField(controller: title, decoration: const InputDecoration(labelText: 'Mô tả bước')),
              const SizedBox(height: 8),
              Row(children: [
                Expanded(child: DropdownButtonFormField<String>(initialValue: field, items: const [DropdownMenuItem(value: 'price', child: Text('Giá')), DropdownMenuItem(value: 'position_pnl_pct', child: Text('Lãi/lỗ %')), DropdownMenuItem(value: 'rsi14', child: Text('RSI')), DropdownMenuItem(value: 'vol_ratio', child: Text('KL/TB20'))], onChanged: (v) => set(() => field = v!))),
                const SizedBox(width: 6),
                SizedBox(width: 70, child: DropdownButtonFormField<String>(initialValue: op, items: const [DropdownMenuItem(value: '>=', child: Text('≥')), DropdownMenuItem(value: '<=', child: Text('≤'))], onChanged: (v) => set(() => op = v!))),
                const SizedBox(width: 6),
                Expanded(child: TextField(controller: value, keyboardType: TextInputType.number, decoration: const InputDecoration(labelText: 'Giá trị'))),
              ]),
              const SizedBox(height: 8),
              DropdownButtonFormField<String>(initialValue: action, decoration: const InputDecoration(labelText: 'Hành động'), items: const [DropdownMenuItem(value: 'BUY', child: Text('Mua')), DropdownMenuItem(value: 'SELL', child: Text('Bán')), DropdownMenuItem(value: 'TAKE_PROFIT', child: Text('Chốt lời')), DropdownMenuItem(value: 'MOVE_STOP', child: Text('Dời cắt lỗ')), DropdownMenuItem(value: 'STOP_LOSS', child: Text('Cắt lỗ'))], onChanged: (v) => set(() => action = v!)),
            ])), actions: [TextButton(onPressed: () => Navigator.pop(ctx, false), child: const Text('Hủy')), FilledButton(onPressed: () => Navigator.pop(ctx, true), child: const Text('Thêm'))])));
            if (ok != true) return;
            if (title.text.trim().isEmpty) {
              if (context.mounted) showToast(context, 'Nhập mô tả bước.', error: true);
              return;
            }
            try {
              await api.post('/trade-plans/${p['id']}/steps', data: {'title': title.text.trim(), 'condition': {'field': field, 'op': op, 'value': num.tryParse(value.text.replaceAll('.', '').replaceAll(',', '.')) ?? 0}, 'action': action, 'fraction': 1.0});
              if (context.mounted) showToast(context, 'Đã thêm bước');
            } catch (e) {
              if (context.mounted) showToast(context, 'Không thêm được bước: $e', error: true);
            }
            await refresh();
          },
          icon: const Icon(Icons.add, size: 16), label: const Text('Thêm bước'),
        ),
      ]),
    );
  }
}
