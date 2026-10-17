import 'package:flutter/material.dart';
import '../../shared/widgets/brand.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:go_router/go_router.dart';

import '../../core/api.dart';
import '../../core/format.dart';
import '../../core/responsive.dart';
import '../../core/session.dart';
import '../../core/theme.dart';
import '../../shared/widgets/common.dart';
import '../../shared/widgets/score.dart' show StatusDot;

final _alertsProvider = FutureProvider.autoDispose.family<Map<String, dynamic>, String>((ref, f) async => asMap(await ref.watch(apiProvider).get('/alerts', query: {'f': f, 'size': 100})));
final _rulesProvider = FutureProvider.autoDispose<List<Map<String, dynamic>>>((ref) async => asList(await ref.watch(apiProvider).get('/alert-rules')));

const _filters = [('all', 'Tất cả'), ('unread', 'Chưa đọc'), ('urgent', 'Khẩn'), ('rating', 'Đổi khuyến nghị'), ('price', 'Giá & chỉ báo'), ('portfolio', 'Danh mục & rủi ro')];

class AlertsPage extends ConsumerStatefulWidget {
  final String? filter;
  const AlertsPage({super.key, this.filter});
  @override
  ConsumerState<AlertsPage> createState() => _AlertsPageState();
}

class _AlertsPageState extends ConsumerState<AlertsPage> {
  late String f = widget.filter ?? 'all';

  @override
  Widget build(BuildContext context) {
    final c = context.vn;
    final data = ref.watch(_alertsProvider(f));
    final list = data.when(
      loading: () => const SkeletonList(count: 5),
      error: (e, _) => ErrorBox(e, onRetry: () => ref.invalidate(_alertsProvider(f))),
      data: (d) {
        final items = asList(d['items']);
        final counts = asMap(d['counts']);
        final groups = <String, List<Map<String, dynamic>>>{};
        for (final a in items) {
          final dt = Fmt.parseDate(a['created_at']);
          groups.putIfAbsent(dt == null ? '—' : Fmt.dayLabel(dt), () => []).add(a);
        }
        return RefreshIndicator(
          onRefresh: () async => ref.invalidate(_alertsProvider(f)),
          child: ListView(children: [
            SingleChildScrollView(
              scrollDirection: Axis.horizontal,
              child: Row(children: [
                for (final ff in _filters) Padding(padding: const EdgeInsets.only(right: 6), child: ChoiceChip(label: Text('${ff.$2} · ${counts[ff.$1] ?? 0}'), selected: f == ff.$1, onSelected: (_) => setState(() => f = ff.$1))),
                TextButton(onPressed: () async {
                  await ref.read(apiProvider).post('/alerts/read', data: {'all': true});
                  ref.invalidate(_alertsProvider);
                  ref.read(sessionProvider.notifier).patchLocal({'unread_alerts': 0});
                }, child: const Text('Đọc hết')),
              ]),
            ),
            const SizedBox(height: 10),
            if (items.isEmpty) const EmptyState(art: EmptyArt.alerts, title: 'Chưa có cảnh báo', message: 'Cảnh báo cuối ngày sẽ về sau 15h30 mỗi phiên. Tạo quy tắc cho mức giá bạn quan tâm.'),
            for (final g in groups.entries) ...[
              Padding(padding: const EdgeInsets.only(top: 8, bottom: 6), child: Text(g.key, style: TextStyle(color: c.faint, fontWeight: FontWeight.w600, fontSize: 12))),
              for (final (i, a) in g.value.indexed) Padding(padding: const EdgeInsets.only(bottom: 8), child: _AlertCard(a, onOpen: () => _open(a)).stagger(context, i, step: 25)),
            ],
          ]),
        );
      },
    );
    final rules = _RulesPanel(onNew: () => showRuleEditor(context));
    return Scaffold(
      backgroundColor: Colors.transparent,
      floatingActionButton: context.isDesktop ? null : FloatingActionButton.extended(onPressed: () => showRuleEditor(context), icon: const Icon(Icons.add), label: const Text('Quy tắc mới')),
      body: PageBody(
        child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
          Row(children: [Expanded(child: Text('Cảnh báo', style: Theme.of(context).textTheme.titleLarge)), if (!context.isDesktop) TextButton.icon(onPressed: () => _showRulesSheet(context), icon: const Icon(Icons.rule, size: 18), label: const Text('Quy tắc'))]),
          const SizedBox(height: 10),
          Expanded(child: context.isDesktop ? Row(crossAxisAlignment: CrossAxisAlignment.start, children: [Expanded(flex: 3, child: list), const SizedBox(width: 16), SizedBox(width: 360, child: rules)]) : list),
        ]),
      ),
    );
  }

  void _showRulesSheet(BuildContext context) => showModalBottomSheet(context: context, isScrollControlled: true, useSafeArea: true, builder: (_) => DraggableScrollableSheet(expand: false, initialChildSize: 0.85, builder: (_, __) => Padding(padding: const EdgeInsets.all(16), child: _RulesPanel(onNew: () => showRuleEditor(context)))));

  Future<void> _open(Map<String, dynamic> a) async {
    if (a['read_at'] == null) {
      await ref.read(apiProvider).post('/alerts/read', data: {'ids': [a['id']]});
      ref.invalidate(_alertsProvider);
      final s = ref.read(sessionProvider);
      ref.read(sessionProvider.notifier).patchLocal({'unread_alerts': (s.unread - 1).clamp(0, 9999)});
    }
    final link = a['deeplink']?.toString();
    if (link != null && link.isNotEmpty && mounted) context.push(link == '/' ? '/' : link);
  }
}

class _AlertCard extends StatelessWidget {
  final Map<String, dynamic> a;
  final VoidCallback onOpen;
  const _AlertCard(this.a, {required this.onOpen});
  @override
  Widget build(BuildContext context) {
    final c = context.vn;
    final unread = a['read_at'] == null;
    final col = c.priorityColor(a['priority']?.toString());
    final link = a['deeplink']?.toString() ?? '';
    final actionLabel = link.startsWith('/stocks') ? 'Xem phân tích' : (link.startsWith('/portfolio') && link.contains('plans') ? 'Mở kế hoạch' : (link.startsWith('/portfolio') ? 'Xử lý trong danh mục' : (link.startsWith('/screener') ? 'Mở bộ lọc' : null)));
    return AppCard(
      padding: EdgeInsets.zero,
      onTap: onOpen,
      child: IntrinsicHeight(child: Row(crossAxisAlignment: CrossAxisAlignment.stretch, children: [
        Container(width: 4, decoration: BoxDecoration(color: col, borderRadius: const BorderRadius.horizontal(left: Radius.circular(14)))),
        Expanded(
          child: Padding(
            padding: const EdgeInsets.all(12),
            child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
              Row(children: [
                if (unread) Padding(padding: const EdgeInsets.only(right: 6), child: StatusDot(c.link)),
                Expanded(child: Text(a['title'].toString(), style: TextStyle(fontWeight: unread ? FontWeight.w700 : FontWeight.w500, fontSize: 14))),
                Pill({'URGENT': 'Khẩn', 'HIGH': 'Quan trọng', 'INFO': 'Thông tin'}[a['priority']] ?? '', color: col, fontSize: 10),
              ]),
              if ((a['body']?.toString() ?? '').isNotEmpty) Padding(padding: const EdgeInsets.only(top: 4), child: Text(a['body'].toString(), style: TextStyle(color: c.muted, fontSize: 13))),
              const SizedBox(height: 6),
              Row(children: [
                Text(Fmt.relative(Fmt.parseDate(a['created_at'])), style: TextStyle(color: c.faint, fontSize: 11.5)),
                const Spacer(),
                if (actionLabel != null) Text('$actionLabel →', style: TextStyle(color: c.link, fontSize: 12, fontWeight: FontWeight.w600)),
              ]),
            ]),
          ),
        ),
      ])),
    );
  }
}

class _RulesPanel extends ConsumerWidget {
  final VoidCallback onNew;
  const _RulesPanel({required this.onNew});
  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final c = context.vn;
    final rules = ref.watch(_rulesProvider);
    return AppCard(
      child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
        Row(children: [Expanded(child: Text('Quy tắc cảnh báo', style: Theme.of(context).textTheme.titleMedium)), FilledButton.icon(onPressed: onNew, icon: const Icon(Icons.add, size: 16), label: const Text('Tạo'))]),
        const SizedBox(height: 8),
        rules.when(
          loading: () => const Skeleton(),
          error: (e, _) => ErrorBox(e),
          data: (rows) => rows.isEmpty
              ? Text('Chưa có quy tắc. Tạo cảnh báo giá, chỉ báo hoặc đổi khuyến nghị cho mã bạn quan tâm.', style: TextStyle(color: c.muted, fontSize: 13))
              : Column(children: [
                  for (final r in rows)
                    ListTile(
                      dense: true, contentPadding: EdgeInsets.zero,
                      title: Text(r['name'].toString(), style: const TextStyle(fontWeight: FontWeight.w600, fontSize: 13)),
                      subtitle: Text('${(r['channels'] as List? ?? []).join(', ')} · ${ {'INTRADAY': 'trong phiên', 'EOD': 'cuối ngày', 'BOTH': 'cả hai'}[r['timing']] } · ${r['priority']}', style: TextStyle(fontSize: 11.5, color: c.faint)),
                      trailing: Row(mainAxisSize: MainAxisSize.min, children: [
                        Switch(value: r['enabled'] == true, onChanged: (v) async {
                          await ref.read(apiProvider).patch('/alert-rules/${r['id']}/toggle', query: {'enabled': v});
                          ref.invalidate(_rulesProvider);
                        }),
                        IconButton(icon: const Icon(Icons.delete_outline, size: 18), onPressed: () async {
                          await ref.read(apiProvider).delete('/alert-rules/${r['id']}');
                          ref.invalidate(_rulesProvider);
                        }),
                      ]),
                      onTap: () => showRuleEditor(context, existing: r),
                    ),
                ]),
        ),
      ]),
    );
  }
}

/// Rule editor (create / edit). Also used from the analysis page ("Đặt cảnh báo", "Báo khi giá vào vùng mua").
Future<void> showRuleEditor(BuildContext context, {String? symbol, String? template, Map<String, dynamic>? existing}) async {
  final body = _RuleEditor(symbol: symbol, template: template, existing: existing);
  if (context.isDesktop) {
    await showDialog(context: context, builder: (_) => Dialog(child: ConstrainedBox(constraints: const BoxConstraints(maxWidth: 520), child: body)));
  } else {
    await showModalBottomSheet(context: context, isScrollControlled: true, useSafeArea: true, builder: (_) => Padding(padding: EdgeInsets.only(bottom: MediaQuery.viewInsetsOf(context).bottom), child: body));
  }
}

class _RuleEditor extends ConsumerStatefulWidget {
  final String? symbol, template;
  final Map<String, dynamic>? existing;
  const _RuleEditor({this.symbol, this.template, this.existing});
  @override
  ConsumerState<_RuleEditor> createState() => _RuleEditorState();
}

class _RuleEditorState extends ConsumerState<_RuleEditor> {
  late String scope = widget.existing?['scope_type'] ?? (widget.symbol != null ? 'SYMBOL' : 'SYMBOL');
  late final scopeId = TextEditingController(text: widget.existing?['scope_id']?.toString() ?? widget.symbol ?? '');
  late String template = widget.existing?['template'] ?? widget.template ?? 'PRICE';
  late String timing = widget.existing?['timing'] ?? 'BOTH';
  late String priority = widget.existing?['priority'] ?? 'HIGH';
  late Set<String> channels = {...((widget.existing?['channels'] as List?) ?? ['push', 'telegram']).map((e) => e.toString())};
  late int cooldown = asInt(widget.existing?['cooldown_minutes']) ?? 1440;
  final value = TextEditingController(), name = TextEditingController();
  String op = '<=';
  Map<String, dynamic>? preview;
  List<Map<String, dynamic>> templates = [];
  List<Map<String, dynamic>> portfolios = [], watchlists = [];
  bool _busy = false;

  @override
  void initState() {
    super.initState();
    name.text = widget.existing?['name']?.toString() ?? '';
    _load();
  }

  Future<void> _load() async {
    final api = ref.read(apiProvider);
    templates = asList(await api.get('/alert-rules/templates'));
    portfolios = asList(await api.get('/portfolios'));
    watchlists = asList(await api.get('/watchlists'));
    if (mounted) setState(() {});
  }

  Map<String, dynamic> _body() => {
        'name': name.text.trim().isEmpty ? null : name.text.trim(), 'scope_type': scope, 'scope_id': scope == 'MARKET' ? null : scopeId.text.trim().toUpperCase(),
        'template': template, 'params': {'op': op, if (value.text.isNotEmpty) 'value': num.tryParse(value.text.replaceAll('.', '')), 'direction': op == '>=' ? 'up' : 'down'},
        'timing': timing, 'priority': priority, 'channels': channels.toList(), 'cooldown_minutes': cooldown, 'enabled': true,
      };

  Future<void> _preview() async {
    try {
      preview = asMap(await ref.read(apiProvider).post('/alert-rules/preview', data: _body()));
      setState(() {});
    } on ApiException catch (e) {
      if (mounted) showToast(context, e.message, error: true);
    }
  }

  Future<void> _save() async {
    setState(() => _busy = true);
    try {
      final api = ref.read(apiProvider);
      widget.existing != null ? await api.put('/alert-rules/${widget.existing!['id']}', data: _body()) : await api.post('/alert-rules', data: _body());
      ref.invalidate(_rulesProvider);
      if (mounted) {
        showToast(context, 'Đã lưu cảnh báo');
        Navigator.pop(context);
      }
    } on ApiException catch (e) {
      if (mounted) showToast(context, e.message, error: true);
    } finally {
      if (mounted) setState(() => _busy = false);
    }
  }

  @override
  Widget build(BuildContext context) {
    final c = context.vn;
    final needsValue = ['RSI', 'PRICE', 'PCT_CHANGE', 'VOLUME_SPIKE'].contains(template);
    return SingleChildScrollView(
      padding: const EdgeInsets.all(20),
      child: Column(crossAxisAlignment: CrossAxisAlignment.stretch, mainAxisSize: MainAxisSize.min, children: [
        Row(children: [Expanded(child: Text(widget.existing != null ? 'Sửa quy tắc' : 'Quy tắc cảnh báo mới', style: Theme.of(context).textTheme.titleLarge)), IconButton(onPressed: () => Navigator.pop(context), icon: const Icon(Icons.close))]),
        const SizedBox(height: 10),
        Text('Áp dụng cho', style: TextStyle(color: c.faint, fontSize: 12)),
        Wrap(spacing: 6, children: [for (final s in const [('SYMBOL', 'Một mã'), ('WATCHLIST', 'Danh sách'), ('PORTFOLIO', 'Danh mục'), ('MARKET', 'Toàn thị trường')]) ChoiceChip(label: Text(s.$2), selected: scope == s.$1, onSelected: (_) => setState(() => scope = s.$1))]),
        const SizedBox(height: 8),
        if (scope == 'SYMBOL') TextField(controller: scopeId, decoration: const InputDecoration(labelText: 'Mã'), textCapitalization: TextCapitalization.characters),
        if (scope == 'WATCHLIST') DropdownButtonFormField<String>(initialValue: watchlists.any((w) => w['id'] == scopeId.text) ? scopeId.text : null, decoration: const InputDecoration(labelText: 'Danh sách'), items: [for (final w in watchlists) DropdownMenuItem(value: w['id'].toString(), child: Text(w['name'].toString()))], onChanged: (v) => scopeId.text = v ?? ''),
        if (scope == 'PORTFOLIO') DropdownButtonFormField<String>(initialValue: portfolios.any((p) => p['id'] == scopeId.text) ? scopeId.text : null, decoration: const InputDecoration(labelText: 'Danh mục'), items: [for (final p in portfolios) DropdownMenuItem(value: p['id'].toString(), child: Text(p['name'].toString()))], onChanged: (v) => scopeId.text = v ?? ''),
        const SizedBox(height: 12),
        Text('Khi nào báo', style: TextStyle(color: c.faint, fontSize: 12)),
        Wrap(spacing: 6, runSpacing: 6, children: [for (final t in templates) ChoiceChip(label: Text(t['name'].toString()), selected: template == t['code'], onSelected: (_) => setState(() => template = t['code']))]),
        if (needsValue) Padding(
          padding: const EdgeInsets.only(top: 8),
          child: Row(children: [
            SizedBox(width: 110, child: DropdownButtonFormField<String>(initialValue: op, items: const [DropdownMenuItem(value: '<=', child: Text('≤ dưới')), DropdownMenuItem(value: '>=', child: Text('≥ trên')), DropdownMenuItem(value: '<', child: Text('< nhỏ hơn')), DropdownMenuItem(value: '>', child: Text('> lớn hơn'))], onChanged: (v) => setState(() => op = v ?? '<='))),
            const SizedBox(width: 8),
            Expanded(child: TextField(controller: value, keyboardType: TextInputType.number, decoration: InputDecoration(labelText: {'RSI': 'Giá trị RSI', 'PRICE': 'Mức giá (đồng)', 'PCT_CHANGE': '% thay đổi', 'VOLUME_SPIKE': 'KL / TB20'}[template]))),
          ]),
        ),
        const SizedBox(height: 12),
        Row(children: [
          Expanded(child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [Text('Thời điểm', style: TextStyle(color: c.faint, fontSize: 12)), Segmented<String>(options: const [('INTRADAY', 'Trong phiên'), ('EOD', 'Cuối ngày'), ('BOTH', 'Cả hai')], value: timing, onChanged: (v) => setState(() => timing = v))])),
        ]),
        const SizedBox(height: 10),
        Row(children: [
          Expanded(child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [Text('Mức ưu tiên', style: TextStyle(color: c.faint, fontSize: 12)), Segmented<String>(options: const [('URGENT', 'Khẩn'), ('HIGH', 'Quan trọng'), ('INFO', 'Thông tin')], value: priority, onChanged: (v) => setState(() => priority = v))])),
        ]),
        const SizedBox(height: 10),
        Text('Gửi qua', style: TextStyle(color: c.faint, fontSize: 12)),
        Wrap(spacing: 6, children: [for (final ch in const [('push', 'Thông báo đẩy'), ('telegram', 'Telegram'), ('email', 'Email')]) FilterChip(label: Text(ch.$2), selected: channels.contains(ch.$1), onSelected: (v) => setState(() => v ? channels.add(ch.$1) : channels.remove(ch.$1)))]),
        const SizedBox(height: 10),
        Row(children: [Expanded(child: Text('Chống báo trùng: ${cooldown >= 1440 ? '${cooldown ~/ 1440} ngày' : '$cooldown phút'}', style: const TextStyle(fontSize: 13))), Slider(value: cooldown.toDouble(), min: 15, max: 4320, divisions: 20, onChanged: (v) => setState(() => cooldown = v.round()))]),
        TextField(controller: name, decoration: const InputDecoration(labelText: 'Tên quy tắc (tùy chọn)')),
        const SizedBox(height: 10),
        if (preview != null) Padding(padding: const EdgeInsets.only(bottom: 8), child: Text('Hiện có ${preview!['count']} mã thỏa điều kiện${(preview!['symbols'] as List? ?? []).isNotEmpty ? ': ${(preview!['symbols'] as List).take(10).join(', ')}' : ''}', style: TextStyle(color: c.muted, fontSize: 12.5))),
        Row(children: [
          OutlinedButton(onPressed: _preview, child: const Text('Xem trước')),
          const Spacer(),
          FilledButton(onPressed: _busy ? null : _save, child: const Text('Lưu cảnh báo')),
        ]),
      ]),
    );
  }
}
