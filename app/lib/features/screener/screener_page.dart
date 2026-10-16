import 'dart:convert';

import 'package:flutter/material.dart';
import 'package:flutter_animate/flutter_animate.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:go_router/go_router.dart';

import '../../core/api.dart';
import '../../core/format.dart';
import '../../core/responsive.dart';
import '../../core/session.dart';
import '../../core/theme.dart';
import '../../shared/widgets/common.dart';
import '../../shared/widgets/stock_rows.dart';
import '../ai/ai_panel.dart';
import '../pretrade/pretrade_sheet.dart';

final _presetsProvider = FutureProvider.autoDispose<List<Map<String, dynamic>>>((ref) async => asList(await ref.watch(apiProvider).get('/screeners/presets')));
final _fieldsProvider = FutureProvider<Map<String, dynamic>>((ref) async => asMap(await ref.watch(apiProvider).get('/screener/fields')));
final _savedProvider = FutureProvider.autoDispose<List<Map<String, dynamic>>>((ref) async => asList(await ref.watch(apiProvider).get('/screeners')).where((s) => s['is_preset'] != true).toList());

class ScreenerPage extends ConsumerStatefulWidget {
  final String? preset, savedId;
  const ScreenerPage({super.key, this.preset, this.savedId});
  @override
  ConsumerState<ScreenerPage> createState() => _ScreenerPageState();
}

class _ScreenerPageState extends ConsumerState<ScreenerPage> {
  String? presetCode;
  Map<String, dynamic> form = {};
  Map<String, dynamic>? advanced; // DSL built by the builder (FULL level)
  Map<String, dynamic>? result;
  bool _busy = false, _advancedMode = false, _showJson = false;
  String hz = 'MID';
  String? savedName;

  @override
  void initState() {
    super.initState();
    presetCode = widget.preset;
    WidgetsBinding.instance.addPostFrameCallback((_) => widget.savedId != null ? _loadSaved(widget.savedId!) : _selectPreset(presetCode ?? 'PULLBACK_MA50'));
  }

  Future<void> _loadSaved(String id) async {
    final s = asMap(await ref.read(apiProvider).get('/screeners/$id'));
    setState(() {
      savedName = s['name'];
      hz = s['horizon'] ?? 'MID';
      presetCode = null;
      if (s['form_state'] != null) {
        form = asMap(s['form_state']);
        advanced = null;
      } else {
        advanced = asMap(s['conditions']);
        _advancedMode = true;
      }
    });
    _run();
  }

  Future<void> _selectPreset(String code) async {
    final presets = await ref.read(_presetsProvider.future);
    final p = presets.firstWhere((p) => p['code'] == code, orElse: () => presets.first);
    setState(() {
      presetCode = p['code'];
      hz = p['horizon'] ?? 'MID';
      form = asMap(p['form_state']);
      advanced = null;
      _advancedMode = false;
      savedName = null;
    });
    _run();
  }

  Future<void> _run() async {
    setState(() => _busy = true);
    try {
      final body = _advancedMode && advanced != null ? {'conditions': advanced, 'horizon': hz, 'limit': 60} : {'preset_code': presetCode, 'form': form, 'horizon': hz, 'limit': 60};
      result = asMap(await ref.read(apiProvider).post('/screener/run', data: body));
    } on ApiException catch (e) {
      if (mounted) showToast(context, e.message, error: true);
    } finally {
      if (mounted) setState(() => _busy = false);
    }
  }

  Future<void> _save({bool notify = true}) async {
    final ctl = TextEditingController(text: savedName ?? (result?['chips'] as List?)?.take(2).join(', ') ?? 'Bộ lọc của tôi');
    final name = await showDialog<String>(context: context, builder: (ctx) => AlertDialog(title: const Text('Lưu bộ lọc'), content: TextField(controller: ctl, autofocus: true, decoration: const InputDecoration(labelText: 'Tên bộ lọc')), actions: [TextButton(onPressed: () => Navigator.pop(ctx), child: const Text('Hủy')), FilledButton(onPressed: () => Navigator.pop(ctx, ctl.text), child: const Text('Lưu'))]));
    if (name == null || name.trim().isEmpty) return;
    try {
      await ref.read(apiProvider).post('/screeners', data: {'name': name.trim(), 'horizon': hz, 'notify_new': notify, if (_advancedMode && advanced != null) 'conditions': advanced else ...{'preset_code': presetCode, 'form': form}});
      ref.invalidate(_savedProvider);
      if (mounted) showToast(context, notify ? 'Đã lưu bộ lọc. Bạn sẽ được báo mỗi tối khi có mã mới thỏa điều kiện.' : 'Đã lưu bộ lọc');
    } on ApiException catch (e) {
      if (mounted) showToast(context, e.message, error: true);
    }
  }

  @override
  Widget build(BuildContext context) {
    final c = context.vn;
    final level = ref.watch(sessionProvider).uiDetail;
    final presets = ref.watch(_presetsProvider);
    final fields = ref.watch(_fieldsProvider);
    final presetsCard = presets.when(
      loading: () => const SkeletonCard(lines: 4),
      error: (e, _) => ErrorBox(e),
      data: (ps) => _PresetGrid(presets: ps, selected: presetCode, onSelect: _selectPreset),
    );
    final formCard = fields.when(
      loading: () => const SkeletonCard(),
      error: (e, _) => ErrorBox(e),
      data: (f) => _FormCard(fields: asList(f['form']), defaults: asMap(f['form_default']), allFields: asList(f['fields']), ops: (f['ops'] as List? ?? []).map((e) => e.toString()).toList(), form: form, level: level, hz: hz, advanced: advanced, advancedMode: _advancedMode, showJson: _showJson,
          onChange: (k, v) {
            setState(() => form = {...form, k: v});
            _run();
          },
          onReset: () {
            setState(() => form = asMap(f['form_default']));
            _run();
          },
          onHz: (v) {
            setState(() => hz = v);
            _run();
          },
          onAdvanced: (dsl) {
            setState(() {
              advanced = dsl;
              _advancedMode = dsl != null;
            });
            _run();
          },
          onToggleJson: () => setState(() => _showJson = !_showJson),
          onSave: () => _save(notify: true), onSaveQuiet: () => _save(notify: false)),
    );
    final resultsCard = _Results(result: result, busy: _busy, hz: hz, onAdd: (s) async {
      await ref.read(apiProvider).post('/watchlists/quick-add', data: {'symbol': s});
      if (mounted) showToast(context, 'Đã thêm $s vào danh sách theo dõi');
    });
    final savedCard = _Saved(onOpen: (s) => context.go('/screener/${s['id']}'));
    return PageBody(
      child: ListView(children: [
        Row(children: [
          Expanded(child: Text(savedName ?? 'Bộ lọc', style: Theme.of(context).textTheme.titleLarge)),
          AskAiButton(label: 'Nhờ AI lập bộ lọc', onPressed: () => openAi(context, {'screen': 'screener'})),
        ]),
        const SizedBox(height: 12),
        presetsCard.stagger(context, 0),
        SizedBox(height: context.gap),
        if (context.isDesktop)
          Row(crossAxisAlignment: CrossAxisAlignment.start, children: [SizedBox(width: 340, child: Column(children: [formCard.stagger(context, 1), SizedBox(height: context.gap), savedCard])), SizedBox(width: context.gap), Expanded(child: resultsCard.stagger(context, 2))])
        else ...[formCard.stagger(context, 1), SizedBox(height: context.gap), resultsCard.stagger(context, 2), SizedBox(height: context.gap), savedCard],
        Text('Số mã khớp trên thẻ được tính sau mỗi phiên. $_disc', style: TextStyle(color: c.faint, fontSize: 11.5)),
      ]),
    );
  }

  static const _disc = 'Thông tin chỉ mang tính tham khảo, không phải lời khuyên mua bán.';
}

class _PresetGrid extends StatelessWidget {
  final List<Map<String, dynamic>> presets;
  final String? selected;
  final ValueChanged<String> onSelect;
  const _PresetGrid({required this.presets, required this.selected, required this.onSelect});
  @override
  Widget build(BuildContext context) {
    final c = context.vn;
    final groups = {'TECH': 'Kỹ thuật', 'FUND': 'Cơ bản', 'AVOID': 'Nên tránh'};
    return Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
      for (final g in groups.entries) ...[
        Padding(padding: const EdgeInsets.only(bottom: 6, top: 4), child: Text(g.value, style: TextStyle(color: c.faint, fontSize: 12, fontWeight: FontWeight.w600))),
        Wrap(spacing: 10, runSpacing: 10, children: [
          for (final (i, p) in presets.where((p) => p['group'] == g.key).indexed)
            SizedBox(
              width: context.isPhone ? double.infinity : 250,
              child: AppCard(
                padding: const EdgeInsets.all(12),
                onTap: () => onSelect(p['code']),
                borderColor: selected == p['code'] ? c.accent : null,
                color: selected == p['code'] ? c.accent.withValues(alpha: 0.08) : null,
                child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
                  Row(children: [Expanded(child: Text(p['name'].toString(), style: const TextStyle(fontWeight: FontWeight.w700, fontSize: 13))), Text('${p['count'] ?? 0} mã', style: TextStyle(fontWeight: FontWeight.w700, color: g.key == 'AVOID' ? c.downText : c.link, fontSize: 13))]),
                  const SizedBox(height: 4),
                  Text(p['description']?.toString() ?? '', maxLines: 2, overflow: TextOverflow.ellipsis, style: TextStyle(color: c.muted, fontSize: 11.5)),
                ]),
              ).stagger(context, i, step: 30),
            ),
        ]),
        const SizedBox(height: 8),
      ],
    ]);
  }
}

class _FormCard extends StatelessWidget {
  final List<Map<String, dynamic>> fields, allFields;
  final List<String> ops;
  final Map<String, dynamic> defaults, form;
  final Map<String, dynamic>? advanced;
  final String level, hz;
  final bool advancedMode, showJson;
  final void Function(String, dynamic) onChange;
  final VoidCallback onReset, onToggleJson, onSave, onSaveQuiet;
  final ValueChanged<String> onHz;
  final ValueChanged<Map<String, dynamic>?> onAdvanced;
  const _FormCard({required this.fields, required this.allFields, required this.ops, required this.defaults, required this.form, required this.level, required this.hz, required this.advanced, required this.advancedMode, required this.showJson, required this.onChange, required this.onReset, required this.onHz, required this.onAdvanced, required this.onToggleJson, required this.onSave, required this.onSaveQuiet});

  @override
  Widget build(BuildContext context) {
    final c = context.vn;
    final rank = detailRank(level);
    final visible = fields.where((f) => rank >= detailRank(f['level']?.toString() ?? 'SIMPLE')).toList();
    return AppCard(
      child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
        Row(children: [Expanded(child: Text('Điều kiện lọc', style: Theme.of(context).textTheme.titleMedium)), TextButton(onPressed: onReset, child: const Text('Về mặc định'))]),
        Segmented<String>(options: const [('SHORT', 'Ngắn hạn'), ('MID', 'Trung hạn'), ('LONG', 'Dài hạn')], value: hz, onChanged: onHz),
        const SizedBox(height: 10),
        if (!advancedMode)
          for (final f in visible) ...[
            Text(f['label'].toString(), style: TextStyle(color: c.faint, fontSize: 12)),
            const SizedBox(height: 4),
            if (f['toggle'] == true)
              SwitchListTile(dense: true, contentPadding: EdgeInsets.zero, value: form[f['key']] != false, title: Text(f['label'].toString(), style: const TextStyle(fontSize: 13)), onChanged: (v) => onChange(f['key'], v))
            else
              Wrap(spacing: 6, runSpacing: 6, children: [
                for (final o in asList(f['options']))
                  ChoiceChip(
                    label: Text(o['label'].toString()),
                    selected: f['multi'] == true ? ((form[f['key']] as List?) ?? defaults[f['key']] as List? ?? []).contains(o['v']) : (form[f['key']] ?? defaults[f['key']]) == o['v'],
                    selectedColor: c.accent, labelStyle: TextStyle(fontSize: 12, color: (f['multi'] == true ? ((form[f['key']] as List?) ?? []).contains(o['v']) : (form[f['key']] ?? defaults[f['key']]) == o['v']) ? Colors.white : c.text),
                    onSelected: (_) {
                      if (f['multi'] == true) {
                        final cur = List.from((form[f['key']] as List?) ?? defaults[f['key']] as List? ?? []);
                        cur.contains(o['v']) ? cur.remove(o['v']) : cur.add(o['v']);
                        onChange(f['key'], cur);
                      } else {
                        onChange(f['key'], o['v']);
                      }
                    },
                  ),
              ]),
            const SizedBox(height: 10),
          ],
        if (rank >= 2) ...[
          const Divider(),
          Row(children: [
            Expanded(child: Text('Nâng cao: ghép điều kiện VÀ / HOẶC', style: TextStyle(fontWeight: FontWeight.w600, color: c.text, fontSize: 13))),
            Switch(value: advancedMode, onChanged: (v) => onAdvanced(v ? (advanced ?? {'all': <Map<String, dynamic>>[]}) : null)),
          ]),
          if (advancedMode) _Builder(dsl: advanced ?? {'all': []}, fields: allFields, ops: ops, onChanged: onAdvanced),
          TextButton.icon(onPressed: onToggleJson, icon: const Icon(Icons.code, size: 16), label: Text(showJson ? 'Ẩn JSON' : 'Xem JSON')),
          if (showJson) Container(padding: const EdgeInsets.all(8), decoration: BoxDecoration(color: c.surface2, borderRadius: BorderRadius.circular(8)), child: SelectableText(const JsonEncoder.withIndent('  ').convert(advancedMode ? advanced : {'preset_form': form}), style: TextStyle(fontFamily: 'monospace', fontSize: 11, color: c.muted))),
        ],
        const SizedBox(height: 8),
        Row(children: [
          Expanded(child: FilledButton.icon(onPressed: onSave, icon: const Icon(Icons.notifications_active_outlined, size: 18), label: const Text('Lưu và báo khi có mã mới'))),
          const SizedBox(width: 6),
          IconButton(tooltip: 'Chỉ lưu', onPressed: onSaveQuiet, icon: const Icon(Icons.bookmark_add_outlined)),
        ]),
      ]),
    );
  }
}

/// AND/OR condition builder for FULL level.
class _Builder extends StatelessWidget {
  final Map<String, dynamic> dsl;
  final List<Map<String, dynamic>> fields;
  final List<String> ops;
  final ValueChanged<Map<String, dynamic>> onChanged;
  const _Builder({required this.dsl, required this.fields, required this.ops, required this.onChanged});

  @override
  Widget build(BuildContext context) {
    final c = context.vn;
    final isAll = dsl.containsKey('all');
    final rules = asList(dsl[isAll ? 'all' : 'any']);
    void update(List<Map<String, dynamic>> r, {bool? all}) => onChanged({(all ?? isAll) ? 'all' : 'any': r});
    return Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
      Row(children: [Text('Khớp', style: TextStyle(color: c.muted, fontSize: 12.5)), const SizedBox(width: 8), Segmented<bool>(options: const [(true, 'TẤT CẢ (VÀ)'), (false, 'BẤT KỲ (HOẶC)')], value: isAll, onChanged: (v) => update(rules, all: v))]),
      const SizedBox(height: 6),
      for (final (i, r) in rules.indexed)
        Padding(
          padding: const EdgeInsets.only(bottom: 6),
          child: Row(children: [
            Expanded(flex: 5, child: DropdownButtonFormField<String>(initialValue: r['field']?.toString(), isDense: true, items: [for (final f in fields) DropdownMenuItem(value: f['key'].toString(), child: Text(f['vi'].toString(), style: const TextStyle(fontSize: 12), overflow: TextOverflow.ellipsis))], onChanged: (v) => update([...rules]..[i] = {...r, 'field': v}))),
            const SizedBox(width: 4),
            Expanded(flex: 3, child: DropdownButtonFormField<String>(initialValue: r['op']?.toString() ?? '>=', isDense: true, items: [for (final o in ops) DropdownMenuItem(value: o, child: Text(o, style: const TextStyle(fontSize: 12)))], onChanged: (v) => update([...rules]..[i] = {...r, 'op': v}))),
            const SizedBox(width: 4),
            Expanded(flex: 3, child: TextFormField(initialValue: r['value'] is List ? (r['value'] as List).join(',') : r['value']?.toString() ?? '', decoration: const InputDecoration(hintText: 'giá trị', isDense: true), style: const TextStyle(fontSize: 12), onFieldSubmitted: (v) => update([...rules]..[i] = {...r, 'value': _parse(v, r['op']?.toString())}))),
            IconButton(icon: const Icon(Icons.close, size: 16), onPressed: () => update([...rules]..removeAt(i))),
          ]),
        ),
      TextButton.icon(onPressed: () => update([...rules, {'field': 'score_mid', 'op': '>=', 'value': 65}]), icon: const Icon(Icons.add, size: 16), label: const Text('Thêm điều kiện')),
      Text('Nhấn Enter trong ô giá trị để áp dụng. between: "50,70"; in: "HOSE,HNX".', style: TextStyle(color: c.faint, fontSize: 11)),
    ]);
  }

  dynamic _parse(String v, String? op) {
    if (op == 'between' || op == 'in' || op == 'not_in') {
      return v.split(',').map((e) => num.tryParse(e.trim()) ?? e.trim()).toList();
    }
    return num.tryParse(v.trim()) ?? v.trim();
  }
}

class _Results extends StatelessWidget {
  final Map<String, dynamic>? result;
  final bool busy;
  final String hz;
  final Future<void> Function(String) onAdd;
  const _Results({required this.result, required this.busy, required this.hz, required this.onAdd});
  @override
  Widget build(BuildContext context) {
    final c = context.vn;
    final r = result;
    return AppCard(
      padding: const EdgeInsets.all(12),
      child: AnimatedOpacity(
        opacity: busy ? 0.5 : 1,
        duration: 200.ms,
        child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
          Row(children: [Expanded(child: Text('Kết quả', style: Theme.of(context).textTheme.titleMedium)), if (busy) const SizedBox(width: 16, height: 16, child: CircularProgressIndicator(strokeWidth: 2))]),
          if (r == null) const SkeletonList(count: 3)
          else ...[
            Wrap(spacing: 6, runSpacing: 6, children: [for (final ch in (r['chips'] as List? ?? [])) Pill(ch.toString(), color: c.muted, bg: c.surface2, fontSize: 11)]),
            const SizedBox(height: 8),
            Text('${r['total']} mã phù hợp · hiển thị ${asList(r['items']).length} mã điểm cao nhất', style: TextStyle(color: c.faint, fontSize: 12)),
            const SizedBox(height: 8),
            if (asList(r['items']).isEmpty)
              EmptyState(icon: Icons.filter_alt_off_outlined, message: r['suggestion']?.toString() ?? 'Không có mã nào thỏa điều kiện. Thử nới bớt một điều kiện.')
            else
              StockTable(
                rows: asList(r['items']), minWidth: 1000,
                columns: [
                  const StockCol('price', 'Giá (VNĐ)', width: 90, build: priceCell), const StockCol('change_pct', '+/−', width: 70, build: changeCell),
                  StockCol('dist_ma50_pct', 'Cách MA50', width: 85, build: (ctx, r) => Text(Fmt.pct(asNum(r['dist_ma50_pct']), decimals: 1), style: TextStyle(color: ctx.vn.changeColor(asNum(r['dist_ma50_pct']))))),
                  StockCol('rsi14', 'RSI', width: 56, build: (ctx, r) => Text(Fmt.num_(asNum(r['rsi14']), decimals: 0))),
                  StockCol('vol_ratio', 'KL/TB20', width: 70, build: (ctx, r) => Text('${Fmt.num_(asNum(r['vol_ratio']), decimals: 1)}×')),
                  StockCol('roe', 'ROE', width: 60, build: (ctx, r) => Text(r['roe'] == null ? Fmt.dash : '${Fmt.num_(asNum(r['roe']), decimals: 0)}%')),
                  StockCol('pe', 'P/E', width: 56, build: (ctx, r) => Text(Fmt.num_(asNum(r['pe'])))),
                  ...stdCols.where((cc) => ['score', 'rating', 'risk'].contains(cc.key)),
                ],
                trailing: (ctx, row) => Row(mainAxisSize: MainAxisSize.min, children: [IconButton(tooltip: 'Theo dõi', icon: const Icon(Icons.add_circle_outline, size: 18), onPressed: () => onAdd(row['symbol'])), BuyButton(onPressed: () => showPretradeSheet(ctx, symbol: row['symbol'], horizon: hz))]),
              ),
          ],
        ]),
      ),
    );
  }
}

class _Saved extends ConsumerWidget {
  final void Function(Map<String, dynamic>) onOpen;
  const _Saved({required this.onOpen});
  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final c = context.vn;
    final saved = ref.watch(_savedProvider);
    return AppCard(
      child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
        Text('Bộ lọc đã lưu', style: Theme.of(context).textTheme.titleMedium),
        const SizedBox(height: 6),
        saved.when(
          loading: () => const Skeleton(),
          error: (e, _) => const SizedBox.shrink(),
          data: (rows) => rows.isEmpty
              ? Text('Chưa có bộ lọc nào. Chỉnh điều kiện rồi bấm “Lưu và báo khi có mã mới”.', style: TextStyle(color: c.muted, fontSize: 12.5))
              : Column(children: [
                  for (final s in rows)
                    ListTile(
                      dense: true, contentPadding: EdgeInsets.zero,
                      title: Text(s['name'].toString(), style: const TextStyle(fontWeight: FontWeight.w600)),
                      subtitle: Text('${s['count'] ?? 0} mã${s['notify_new'] == true ? ' · có báo' : ''}', style: TextStyle(fontSize: 11.5, color: c.faint)),
                      trailing: IconButton(icon: const Icon(Icons.delete_outline, size: 18), onPressed: () async {
                        if (await confirmDialog(context, title: 'Xóa bộ lọc “${s['name']}”?', message: 'Bạn sẽ không còn nhận báo khi có mã mới.', confirmLabel: 'Xóa', danger: true)) {
                          await ref.read(apiProvider).delete('/screeners/${s['id']}');
                          ref.invalidate(_savedProvider);
                        }
                      }),
                      onTap: () => onOpen(s),
                    ),
                ]),
        ),
      ]),
    );
  }
}
