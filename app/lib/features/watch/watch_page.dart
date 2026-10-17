import 'package:flutter/material.dart';
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
import '../pretrade/pretrade_sheet.dart';
import '../shell/app_shell.dart' show showSymbolSearch;

final _wlProvider = FutureProvider.autoDispose.family<List<Map<String, dynamic>>, String>((ref, hz) async => asList(await ref.watch(apiProvider).get('/watchlists', query: {'horizon': hz})));
final _oppProvider = FutureProvider.autoDispose.family<Map<String, dynamic>, String>((ref, q) async => asMap(await ref.watch(apiProvider).get('/opportunities$q')));

class WatchPage extends ConsumerStatefulWidget {
  final String? tab, horizon;
  const WatchPage({super.key, this.tab, this.horizon});
  @override
  ConsumerState<WatchPage> createState() => _WatchPageState();
}

class _WatchPageState extends ConsumerState<WatchPage> {
  late bool market = widget.tab == 'market';
  String? wlId;
  String? ratingFilter;
  bool onlyBuy = false, noRisk = false, noChase = false;
  int page = 1;

  @override
  void initState() {
    super.initState();
    if (widget.horizon != null) WidgetsBinding.instance.addPostFrameCallback((_) => ref.read(horizonProvider.notifier).set(widget.horizon!));
  }

  @override
  Widget build(BuildContext context) {
    final hz = ref.watch(horizonProvider);
    final c = context.vn;
    return PageBody(
      child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
        Row(children: [
          Expanded(child: Text('Theo dõi', style: Theme.of(context).textTheme.titleLarge)),
          if (!context.isPhone) ...[
            Segmented<String>(options: const [('SHORT', 'Ngắn'), ('MID', 'Trung'), ('LONG', 'Dài')], value: hz, onChanged: (v) => ref.read(horizonProvider.notifier).set(v)),
            const SizedBox(width: 8),
          ],
          FilledButton.icon(onPressed: () => showSymbolSearch(context, onPick: (r) => _add(r['symbol'])), icon: const Icon(Icons.add, size: 18), label: Text(context.isPhone ? 'Thêm' : 'Thêm mã')),
          if (context.isPhone) IconButton(tooltip: 'Bộ lọc', onPressed: () => context.go('/screener'), icon: const Icon(Icons.filter_alt_outlined)),
        ]),
        const SizedBox(height: 10),
        Row(children: [
          Expanded(child: Segmented<bool>(options: const [(false, 'Danh sách của tôi'), (true, 'Cơ hội toàn thị trường')], value: market, onChanged: (v) => setState(() => market = v))),
        ]),
        if (context.isPhone) Padding(padding: const EdgeInsets.only(top: 8), child: Segmented<String>(options: const [('SHORT', 'Ngắn hạn'), ('MID', 'Trung hạn'), ('LONG', 'Dài hạn')], value: hz, onChanged: (v) => ref.read(horizonProvider.notifier).set(v))),
        const SizedBox(height: 12),
        Expanded(child: market ? _market(hz) : _mine(hz)),
        Text('Xu hướng N·T·D: ▲ tăng, ▬ ngang, ▼ giảm theo ngắn · trung · dài hạn.', style: TextStyle(color: c.faint, fontSize: 11)),
      ]),
    );
  }

  Future<void> _add(String symbol) async {
    try {
      final body = {'symbol': symbol};
      if (wlId != null) {
        await ref.read(apiProvider).post('/watchlists/$wlId/items', data: body);
      } else {
        await ref.read(apiProvider).post('/watchlists/quick-add', data: body);
      }
      ref.invalidate(_wlProvider);
      if (mounted) showToast(context, 'Đã thêm $symbol vào danh sách theo dõi');
    } on ApiException catch (e) {
      if (mounted) showToast(context, e.message, error: true);
    }
  }

  Widget _mine(String hz) {
    final c = context.vn;
    final data = ref.watch(_wlProvider(hz));
    return data.when(
      loading: () => const SkeletonList(),
      error: (e, _) => ErrorBox(e, onRetry: () => ref.invalidate(_wlProvider(hz))),
      data: (lists) {
        final cur = lists.firstWhere((l) => l['id'] == wlId, orElse: () => lists.first);
        wlId ??= cur['id'];
        var items = asList(cur['items']);
        final counts = <String, int>{};
        for (final i in items) {
          final r = (i['rating_hz'] ?? i['rating'])?.toString();
          if (r != null) counts[r] = (counts[r] ?? 0) + 1;
        }
        if (ratingFilter != null) items = items.where((i) => (i['rating_hz'] ?? i['rating']) == ratingFilter).toList();
        final changed = asInt(cur['changed_today']) ?? 0;
        return RefreshIndicator(
          onRefresh: () async => ref.invalidate(_wlProvider(hz)),
          child: ListView(children: [
            if (changed > 0) Padding(padding: const EdgeInsets.only(bottom: 8), child: Text('$changed mã đổi khuyến nghị hôm nay', style: TextStyle(color: c.link, fontWeight: FontWeight.w600))),
            Wrap(spacing: 6, runSpacing: 6, children: [
              for (final l in lists)
                InputChip(
                  selected: l['id'] == wlId, label: Text('${l['name']} · ${l['count']}'), onSelected: (_) => setState(() => wlId = l['id']),
                  onDeleted: lists.length > 1 && l['id'] == wlId ? () async {
                    if (await confirmDialog(context, title: 'Xóa danh sách “${l['name']}”?', message: 'Các mã trong danh sách sẽ không còn được theo dõi.', confirmLabel: 'Xóa danh sách', danger: true)) {
                      await ref.read(apiProvider).delete('/watchlists/${l['id']}');
                      setState(() => wlId = null);
                      ref.invalidate(_wlProvider);
                    }
                  } : null,
                ),
              ActionChip(avatar: const Icon(Icons.add, size: 16), label: const Text('Danh sách mới'), onPressed: () => _newList()),
            ]),
            const SizedBox(height: 8),
            Wrap(spacing: 6, children: [
              ChoiceChip(label: const Text('Tất cả'), selected: ratingFilter == null, onSelected: (_) => setState(() => ratingFilter = null)),
              for (final r in ['STRONG_BUY', 'BUY', 'HOLD', 'REDUCE', 'SELL'])
                ChoiceChip(label: Text('${ratingVi[r]} · ${counts[r] ?? 0}'), selected: ratingFilter == r, onSelected: (_) => setState(() => ratingFilter = ratingFilter == r ? null : r), labelStyle: TextStyle(color: c.ratingColor(r), fontSize: 12)),
            ]),
            const SizedBox(height: 12),
            if (items.isEmpty)
              EmptyState(art: EmptyArt.watchlist, title: 'Chưa có mã theo dõi', message: 'Thêm mã để theo dõi diễn biến, hoặc thêm nhanh từ tab Cơ hội và Bộ lọc.', actionLabel: 'Thêm mã', onAction: () => showSymbolSearch(context, onPick: (r) => _add(r['symbol'])))
            else
              StockTable(
                rows: items, subtitleKey: null,
                columns: [...stdCols, const StockCol('today', 'Từ hôm nay', width: 110, build: _changedCell)],
                trailing: (ctx, r) => Row(mainAxisSize: MainAxisSize.min, children: [
                  BuyButton(onPressed: () => showPretradeSheet(ctx, symbol: r['symbol'], horizon: hz)),
                  if (!ctx.isPhone) IconButton(tooltip: 'Bỏ theo dõi', icon: const Icon(Icons.close, size: 16), onPressed: () => _remove(r['symbol'])),
                ]),
              ),
          ]),
        );
      },
    );
  }

  static Widget _changedCell(BuildContext ctx, Map<String, dynamic> r) {
    if (r['rating_changed'] != true) return Text(Fmt.dash, style: TextStyle(color: ctx.vn.faint));
    return Text('${ratingVi[r['prev_rating']] ?? '?'} → ${ratingVi[r['rating']] ?? '?'}', style: TextStyle(color: ctx.vn.link, fontSize: 11.5, fontWeight: FontWeight.w600));
  }

  Future<void> _remove(String symbol) async {
    await ref.read(apiProvider).delete('/watchlists/$wlId/items/$symbol');
    ref.invalidate(_wlProvider);
    if (mounted) showToast(context, 'Đã bỏ $symbol khỏi danh sách');
  }

  Future<void> _newList() async {
    final ctl = TextEditingController();
    final name = await showDialog<String>(context: context, builder: (ctx) => AlertDialog(title: const Text('Danh sách mới'), content: TextField(controller: ctl, autofocus: true, decoration: const InputDecoration(labelText: 'Tên danh sách')), actions: [TextButton(onPressed: () => Navigator.pop(ctx), child: const Text('Hủy')), FilledButton(onPressed: () => Navigator.pop(ctx, ctl.text), child: const Text('Tạo'))]));
    if (name == null || name.trim().isEmpty) return;
    final r = asMap(await ref.read(apiProvider).post('/watchlists', data: {'name': name.trim()}));
    setState(() => wlId = r['id']);
    ref.invalidate(_wlProvider);
  }

  Widget _market(String hz) {
    final q = '?horizon=$hz&only_buy=$onlyBuy&exclude_high_risk=$noRisk&exclude_chase=$noChase&limit=50&page=$page';
    final data = ref.watch(_oppProvider(q));
    final c = context.vn;
    return Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
      Wrap(spacing: 6, runSpacing: 6, children: [
        FilterChip(label: const Text('Chỉ tín hiệu mua'), selected: onlyBuy, onSelected: (v) => setState(() {
          onlyBuy = v;
          page = 1;
        })),
        FilterChip(label: const Text('Bỏ mã rủi ro DN cao'), selected: noRisk, onSelected: (v) => setState(() => noRisk = v)),
        FilterChip(label: const Text('Bỏ mã mua đuổi'), selected: noChase, onSelected: (v) => setState(() => noChase = v)),
      ]),
      const SizedBox(height: 10),
      Expanded(
        child: data.when(
          loading: () => const SkeletonList(),
          error: (e, _) => ErrorBox(e, onRetry: () => ref.invalidate(_oppProvider(q))),
          data: (d) {
            final rows = asList(d['items']);
            final total = asInt(d['total']) ?? 0;
            return ListView(children: [
              Text('$total mã · xếp theo điểm ${horizonVi[hz]?.toLowerCase()}', style: TextStyle(color: c.faint, fontSize: 12)),
              const SizedBox(height: 8),
              if (rows.isEmpty) const EmptyState(icon: Icons.radar, message: 'Không có mã nào thỏa bộ lọc nhanh. Thử bỏ bớt điều kiện.')
              else StockTable(rows: rows, trailing: (ctx, r) => Row(mainAxisSize: MainAxisSize.min, children: [IconButton(tooltip: 'Theo dõi', icon: const Icon(Icons.add_circle_outline, size: 18), onPressed: () => _add(r['symbol'])), BuyButton(onPressed: () => showPretradeSheet(ctx, symbol: r['symbol'], horizon: hz))])),
              if (total > 50) Padding(padding: const EdgeInsets.symmetric(vertical: 12), child: Row(mainAxisAlignment: MainAxisAlignment.center, children: [IconButton(onPressed: page > 1 ? () => setState(() => page--) : null, icon: const Icon(Icons.chevron_left)), Text('Trang $page / ${(total / 50).ceil()}'), IconButton(onPressed: page * 50 < total ? () => setState(() => page++) : null, icon: const Icon(Icons.chevron_right))])),
              const DisclaimerText(),
            ]);
          },
        ),
      ),
    ]);
  }
}
