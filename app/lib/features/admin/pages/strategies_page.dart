import 'dart:async';

import 'package:fl_chart/fl_chart.dart';
import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../../../core/api.dart';
import '../../../core/format.dart';
import '../../../core/providers.dart';
import '../../../core/responsive.dart';
import '../../../core/theme.dart';
import '../../../shared/widgets/common.dart';
import '../../../shared/widgets/score.dart';
import '../admin_common.dart';

/// A03 – Chiến lược & tín hiệu, trọng số điểm: strategy table with on/off, weight sliders with impact preview,
/// parameter panel with draft version, backtest comparison and "Bật phiên bản mới".
class StrategiesPage extends ConsumerStatefulWidget {
  final String? code;
  const StrategiesPage({super.key, this.code});
  @override
  ConsumerState<StrategiesPage> createState() => _StrategiesPageState();
}

class _StrategiesPageState extends ConsumerState<StrategiesPage> {
  String? selected;
  Timer? poll;

  @override
  void initState() {
    super.initState();
    selected = widget.code;
    poll = Timer.periodic(const Duration(seconds: 15), (_) {
      final d = ref.read(getMapProvider('/admin/strategies')).value;
      final running = d?['backtest_all_running'] == true || asList(d?['items']).any((s) => s['running'] == true);
      if (running) ref.invalidate(getProvider('/admin/strategies'));
    });
  }

  @override
  void dispose() {
    poll?.cancel();
    super.dispose();
  }

  void _refresh() => ref.invalidate(getProvider('/admin/strategies'));

  @override
  Widget build(BuildContext context) {
    final c = context.vn;
    final data = ref.watch(getMapProvider('/admin/strategies'));
    return Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
      AdminHeader('Chiến lược & tín hiệu', subtitle: 'Chỉ bật chiến lược đã có kết quả kiểm thử tối thiểu 5 năm. Mọi thay đổi có phiên bản và ghi nhật ký.', actions: [
        OutlinedButton.icon(
          onPressed: data.value?['backtest_all_running'] == true ? null : () async {
            if (!await confirmDialog(context, title: 'Chạy lại backtest tất cả?', message: 'Chạy lại 5 năm cho mọi chiến lược đang bật, mất khoảng 20 phút. Số liệu tỷ lệ đúng, lợi nhuận TB sẽ cập nhật sau khi xong.', confirmLabel: 'Chạy')) return;
            try {
              final r = asMap(await ref.read(apiProvider).post('/admin/strategies/backtest-all'));
              _refresh();
              if (context.mounted) showToast(context, r['message'].toString());
            } on ApiException catch (e) {
              if (context.mounted) showToast(context, e.message, error: true);
            }
          },
          icon: data.value?['backtest_all_running'] == true ? const SizedBox(width: 16, height: 16, child: CircularProgressIndicator(strokeWidth: 2)) : const Icon(Icons.replay, size: 18),
          label: Text(data.value?['backtest_all_running'] == true ? 'Đang backtest…' : 'Chạy lại backtest tất cả'),
        ),
        Tooltip(message: 'Chiến lược mới cần viết luật trong engines/strategies.py; chưa tạo được từ giao diện.', child: OutlinedButton.icon(onPressed: null, icon: const Icon(Icons.add, size: 18), label: const Text('Chiến lược mới'))),
      ]),
      data.when(
        loading: () => const SkeletonList(),
        error: (e, _) => ErrorBox(e, onRetry: _refresh),
        data: (d) {
          final rows = asList(d['items']);
          final sel = rows.where((s) => s['code'] == selected).firstOrNull;
          final list = Column(children: [
            AppCard(
              padding: EdgeInsets.zero,
              child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
                Padding(padding: const EdgeInsets.fromLTRB(16, 14, 16, 4), child: Row(children: [
                  Expanded(child: Text('Danh sách chiến lược', style: Theme.of(context).textTheme.titleMedium)),
                  Text(d['last_backtest'] != null ? 'Backtest gần nhất ${Fmt.dateTime(Fmt.parseDate(d['last_backtest']['started_at']))}' : 'Backtest ≥ 5 năm, toàn bộ mã đủ thanh khoản', style: TextStyle(color: c.muted, fontSize: 12.5)),
                ])),
                SingleChildScrollView(
                  scrollDirection: Axis.horizontal,
                  child: DataTable(
                    headingTextStyle: TextStyle(fontSize: 12.5, color: c.muted, fontWeight: FontWeight.w600),
                    columnSpacing: 20,
                    columns: const [DataColumn(label: Text('Bật')), DataColumn(label: Text('Chiến lược')), DataColumn(label: Text('Loại tín hiệu')), DataColumn(label: Text('Khung')), DataColumn(label: Text('Phiên bản')), DataColumn(label: Text('Số lệnh'), numeric: true), DataColumn(label: Text('Tỷ lệ đúng'), numeric: true), DataColumn(label: Text('LN TB'), numeric: true), DataColumn(label: Text('Sụt giảm tối đa'), numeric: true)],
                    rows: [
                      for (final s in rows)
                        DataRow(
                          selected: s['code'] == selected,
                          onSelectChanged: (_) => setState(() => selected = s['code'].toString()),
                          cells: [
                            DataCell(Switch(value: s['enabled'] == true, onChanged: (v) async {
                              if (v && !await confirmDialog(context, title: 'Bật chiến lược ${s['name']}?', message: 'Tín hiệu sẽ gửi tới người dùng từ phiên tới. Thao tác được ghi nhật ký.', confirmLabel: 'Bật')) return;
                              if (!v && !await confirmDialog(context, title: 'Tắt chiến lược ${s['name']}?', message: 'Không phát tín hiệu mới từ phiên tới; tín hiệu đã phát giữ nguyên.', confirmLabel: 'Tắt', danger: true)) return;
                              try {
                                await ref.read(apiProvider).put('/admin/strategies/${s['code']}', data: {'enabled': v});
                                _refresh();
                              } on ApiException catch (e) {
                                if (context.mounted) showToast(context, e.message, error: true);
                              }
                            })),
                            DataCell(Column(mainAxisAlignment: MainAxisAlignment.center, crossAxisAlignment: CrossAxisAlignment.start, children: [
                              Row(children: [Text(s['name'].toString(), style: const TextStyle(fontWeight: FontWeight.w600)), if (s['draft_params'] != null) ...[const SizedBox(width: 6), Pill('Nháp v${(asInt(s['version']) ?? 1) + 1}', color: c.ref, fontSize: 10)]]),
                              Text(s['code'].toString(), style: TextStyle(fontSize: 11, color: c.faint, fontFamily: 'monospace')),
                              if (asList(s['gated_regimes']).isNotEmpty) Text('Tự đứng ngoài khi ${asList(s['gated_regimes']).map((g) => '${regimeVi[g['regime']] ?? g['regime']} (${Fmt.signed(asNum(g['avg_return']), decimals: 1)}%, ${g['samples']} lần)').join(', ')}', style: TextStyle(fontSize: 11, color: c.down), maxLines: 2, overflow: TextOverflow.ellipsis),
                            ])),
                            DataCell(cell(signalTypeVi[s['signal_type']] ?? s['signal_type'].toString(), color: {'BUY': c.up, 'SELL': c.down, 'TAKE_PROFIT': c.ref}[s['signal_type']])),
                            DataCell(cell(horizonVi[s['horizon']] ?? '')),
                            DataCell(cell('v${s['version']}')),
                            DataCell(cell(s['trades'] != null ? Fmt.price(asNum(s['trades'])) : '—')),
                            DataCell(cell(s['win_rate'] != null ? '${Fmt.num_(asNum(s['win_rate']))}%${s['signal_type'] != 'BUY' ? '*' : ''}' : '—', bold: true, color: winRateColor(c, asNum(s['win_rate'])))),
                            DataCell(cell(s['signal_type'] == 'BUY' ? Fmt.pct(asNum(s['avg_return'])) : '—', color: s['signal_type'] == 'BUY' ? c.changeColor(asNum(s['avg_return'])) : null)),
                            DataCell(cell(s['signal_type'] == 'BUY' ? Fmt.pct(asNum(s['max_drawdown'])) : '—', color: s['signal_type'] == 'BUY' ? c.down : null)),
                          ],
                        ),
                    ],
                  ),
                ),
                Padding(padding: const EdgeInsets.fromLTRB(16, 6, 16, 12), child: Text('* Với tín hiệu bán/chốt lời: tỷ lệ giá giảm trong 20 phiên sau tín hiệu. LN TB: lợi nhuận trung bình mỗi lệnh sau phí. "Tự đứng ngoài": chiến lược lỗ ở trạng thái thị trường đó (≥ ${asMap(d['gate'])['min_samples'] ?? 50} lần) nên tín hiệu chỉ được ghi nhận, không gợi ý. Bấm một dòng để sửa tham số.', style: TextStyle(color: c.faint, fontSize: 11.5))),
              ]),
            ),
            const SizedBox(height: 16),
            const _WeightsCard(),
          ]);
          final panel = sel == null ? null : _StrategyPanel(key: ValueKey(sel['code']), s: sel, onChanged: _refresh, onClose: () => setState(() => selected = null));
          if (!context.isDesktop) return Column(children: [if (panel != null) ...[panel, const SizedBox(height: 16)], list]);
          return Row(crossAxisAlignment: CrossAxisAlignment.start, children: [Expanded(flex: 3, child: list), if (panel != null) ...[const SizedBox(width: 16), SizedBox(width: 420, child: panel)]]);
        },
      ),
    ]);
  }
}

/// Scoring weights per horizon with the "Ảnh hưởng: N mã đổi xếp loại" preview before saving.
class _WeightsCard extends ConsumerStatefulWidget {
  const _WeightsCard();
  @override
  ConsumerState<_WeightsCard> createState() => _WeightsCardState();
}

class _WeightsCardState extends ConsumerState<_WeightsCard> {
  Map<String, Map<String, double>>? weights;
  String hz = 'MID';
  Map<String, dynamic>? impact;
  bool previewing = false;

  @override
  Widget build(BuildContext context) {
    final c = context.vn;
    final config = ref.watch(getListProvider('/admin/config'));
    return config.when(
      loading: () => const SkeletonCard(),
      error: (e, _) => ErrorBox(e),
      data: (rows) {
        final row = rows.firstWhere((r) => r['key'] == 'scoring.weights', orElse: () => {});
        final w = asMap(row['value']);
        weights ??= {for (final h in ['SHORT', 'MID', 'LONG']) h: {for (final k in ['tech', 'fund', 'sector', 'pattern']) k: (asNum(asMap(w[h])[k]) ?? 25).toDouble()}};
        final sum = weights![hz]!.values.fold<double>(0, (a, b) => a + b);
        final ok = (sum - 100).abs() < 0.5;
        final dirty = weights!.entries.any((e) => e.value.entries.any((k) => (asNum(asMap(w[e.key])[k.key]) ?? 0).toDouble() != k.value));
        return AppCard(
          child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
            Row(children: [Expanded(child: Text('Trọng số điểm tổng hợp', style: Theme.of(context).textTheme.titleMedium)), if (row['updated_by'] != null) Text('${row['updated_by']} · ${Fmt.relative(Fmt.parseDate(row['updated_at']))}', style: TextStyle(color: c.faint, fontSize: 11.5))]),
            const SizedBox(height: 8),
            Segmented<String>(options: const [('SHORT', 'Ngắn hạn'), ('MID', 'Trung hạn'), ('LONG', 'Dài hạn')], value: hz, onChanged: (v) => setState(() => hz = v)),
            const SizedBox(height: 8),
            for (final k in [('tech', 'Kỹ thuật'), ('fund', 'Cơ bản'), ('sector', 'Ngành & vĩ mô'), ('pattern', 'Nền giá & AI')])
              Row(children: [
                SizedBox(width: 110, child: Text(k.$2, style: const TextStyle(fontSize: 13))),
                Expanded(child: Slider(value: weights![hz]![k.$1]!, min: 0, max: 100, divisions: 20, label: '${weights![hz]![k.$1]!.round()}%', onChanged: (v) => setState(() {
                  weights![hz]![k.$1] = v;
                  impact = null;
                }))),
                SizedBox(width: 44, child: Text('${weights![hz]![k.$1]!.round()}%', textAlign: TextAlign.right, style: const TextStyle(fontSize: 13, fontWeight: FontWeight.w600))),
              ]),
            Row(children: [
              Text(ok ? 'Tổng 100%' : 'Tổng ${sum.round()}% — phải bằng 100%', style: TextStyle(color: ok ? c.up : c.down, fontWeight: FontWeight.w700, fontSize: 13)),
              const SizedBox(width: 12),
              if (impact != null) Expanded(child: Text('Ảnh hưởng: ${impact!['changed']} / ${impact!['total']} mã đổi xếp loại (ngắn ${asMap(impact!['by_horizon'])['SHORT']}, trung ${asMap(impact!['by_horizon'])['MID']}, dài ${asMap(impact!['by_horizon'])['LONG']})${asList(impact!['examples']).isNotEmpty ? ' · ví dụ ${asList(impact!['examples']).take(3).map((e) => '${e['symbol']} ${ratingVi[e['from']] ?? e['from']} → ${ratingVi[e['to']] ?? e['to']}').join(', ')}' : ''}', style: TextStyle(color: c.muted, fontSize: 12.5), maxLines: 2, overflow: TextOverflow.ellipsis)) else const Spacer(),
              TextButton(onPressed: () async {
                await ref.read(apiProvider).post('/admin/config/scoring.weights/reset');
                setState(() {
                  weights = null;
                  impact = null;
                });
                ref.invalidate(getProvider('/admin/config'));
              }, child: const Text('Khôi phục mặc định')),
              const SizedBox(width: 6),
              FilledButton(
                onPressed: !ok || !dirty || previewing ? null : () async {
                  final value = {for (final e in weights!.entries) e.key: {for (final k in e.value.entries) k.key: k.value.round()}};
                  final anyOff = value.values.any((m) => (m.values.fold<int>(0, (a, b) => a + b) - 100).abs() > 0);
                  if (anyOff) {
                    showToast(context, 'Tổng mỗi khung phải bằng 100% (kiểm tra cả 3 khung)', error: true);
                    return;
                  }
                  setState(() => previewing = true);
                  try {
                    final imp = asMap(await ref.read(apiProvider).post('/admin/config/scoring.weights/preview', data: {'value': value}));
                    setState(() => impact = imp);
                    if (!context.mounted) return;
                    if (!await confirmDialog(context, title: 'Lưu trọng số mới?', message: 'Ảnh hưởng: ${imp['changed']} / ${imp['total']} mã đổi xếp loại. Áp dụng từ lần chấm điểm tới (có thể chạy lại bước "Chấm điểm 3 khung" để thấy ngay). Thao tác được ghi nhật ký.', confirmLabel: 'Lưu trọng số')) return;
                    await ref.read(apiProvider).put('/admin/config/scoring.weights', data: {'value': value});
                    ref.invalidate(getProvider('/admin/config'));
                    setState(() => impact = null);
                    if (context.mounted) showToast(context, 'Đã lưu trọng số.');
                  } on ApiException catch (e) {
                    if (context.mounted) showToast(context, e.message, error: true);
                  } finally {
                    if (mounted) setState(() => previewing = false);
                  }
                },
                child: Text(previewing ? 'Đang tính ảnh hưởng…' : 'Lưu trọng số'),
              ),
            ]),
          ]),
        );
      },
    );
  }
}

/// Parameter panel for one strategy: fields with units → draft → backtest comparison → activate.
class _StrategyPanel extends ConsumerStatefulWidget {
  final Map<String, dynamic> s;
  final VoidCallback onChanged, onClose;
  const _StrategyPanel({super.key, required this.s, required this.onChanged, required this.onClose});
  @override
  ConsumerState<_StrategyPanel> createState() => _StrategyPanelState();
}

class _StrategyPanelState extends ConsumerState<_StrategyPanel> {
  final ctls = <String, TextEditingController>{};
  bool busy = false;

  @override
  void initState() {
    super.initState();
    _fill();
  }

  @override
  void didUpdateWidget(covariant _StrategyPanel old) {
    super.didUpdateWidget(old);
    if (old.s['draft_updated_at'] != widget.s['draft_updated_at'] || old.s['version'] != widget.s['version']) _fill();
  }

  void _fill() {
    final live = asMap(widget.s['params']), draft = asMap(widget.s['draft_params']);
    for (final f in asList(widget.s['fields'])) {
      final k = f['key'].toString();
      final v = draft[k] ?? live[k];
      ctls[k] = TextEditingController(text: v is List ? v.join(' ; ') : (v?.toString() ?? ''));
    }
  }

  Map<String, dynamic>? _collect() {
    final out = <String, dynamic>{};
    for (final f in asList(widget.s['fields'])) {
      final t = ctls[f['key']]!.text.trim();
      dynamic v;
      if (f['type'] == 'range') {
        final parts = t.split(RegExp(r'[;,]')).map((x) => num.tryParse(x.trim())).toList();
        v = parts.length == 2 && !parts.contains(null) ? parts : null;
      } else if (f['type'] == 'int') {
        v = int.tryParse(t);
      } else {
        v = num.tryParse(t.replaceAll(',', '.'));
      }
      if (v == null) {
        showToast(context, 'Giá trị "${f['label']}" không hợp lệ', error: true);
        return null;
      }
      out[f['key'].toString()] = v;
    }
    return out;
  }

  Future<void> _do(Future<void> Function() fn) async {
    setState(() => busy = true);
    try {
      await fn();
      widget.onChanged();
    } on ApiException catch (e) {
      if (mounted) showToast(context, e.message, error: true);
    } finally {
      if (mounted) setState(() => busy = false);
    }
  }

  @override
  Widget build(BuildContext context) {
    final c = context.vn;
    final s = widget.s;
    final api = ref.read(apiProvider);
    final fields = asList(s['fields']);
    final live = asMap(s['params']);
    final bt = asMap(s['draft_backtest']);
    final hasDraft = s['draft_params'] != null;
    final v = asInt(s['version']) ?? 1;
    return AppCard(
      child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
        Row(children: [
          Expanded(child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [Text(s['name'].toString(), style: Theme.of(context).textTheme.titleMedium), Text('${s['code']}${hasDraft ? ', đang sửa bản nháp v${v + 1}' : ', phiên bản v$v'}', style: TextStyle(color: c.muted, fontSize: 12.5))])),
          Pill(s['enabled'] == true ? 'Đang bật' : 'Chưa bật', color: s['enabled'] == true ? c.up : c.ref, fontSize: 11),
          IconButton(onPressed: widget.onClose, icon: const Icon(Icons.close, size: 20)),
        ]),
        if ((s['description']?.toString() ?? '').isNotEmpty) Padding(padding: const EdgeInsets.only(top: 4), child: Text(s['description'].toString(), style: TextStyle(color: c.muted, fontSize: 12.5))),
        const Divider(),
        if (fields.isEmpty)
          Text('Chiến lược này dùng luật cố định (giao cắt MA, phân kỳ RSI…), không có tham số chỉnh được.', style: TextStyle(color: c.muted, fontSize: 13))
        else
          for (final f in fields)
            Padding(
              padding: const EdgeInsets.symmetric(vertical: 4),
              child: Row(children: [
                Expanded(child: Text(f['label'].toString(), style: const TextStyle(fontSize: 13))),
                SizedBox(width: 150, child: TextField(controller: ctls[f['key']], textAlign: TextAlign.right, decoration: InputDecoration(isDense: true, suffixText: (f['unit']?.toString() ?? '').isEmpty ? null : f['unit'].toString(), helperText: 'v$v: ${live[f['key']] is List ? (live[f['key']] as List).join(' ; ') : live[f['key']]}', helperStyle: TextStyle(fontSize: 10.5, color: c.faint)))),
              ]),
            ),
        if (fields.isNotEmpty) ...[
          const SizedBox(height: 8),
          Row(children: [
            if (hasDraft) TextButton(onPressed: busy ? null : () => _do(() => api.delete('/admin/strategies/${s['code']}/draft')), child: const Text('Bỏ bản nháp')),
            const Spacer(),
            OutlinedButton(onPressed: busy ? null : () {
              final p = _collect();
              if (p != null) _do(() => api.put('/admin/strategies/${s['code']}/draft', data: {'params': p}));
            }, child: const Text('Lưu bản nháp')),
          ]),
        ],
        if (hasDraft) ...[
          const Divider(),
          Row(children: [
            Expanded(child: Text('So sánh backtest', style: const TextStyle(fontWeight: FontWeight.w700, fontSize: 13.5))),
            if (s['running'] == true) const SizedBox(width: 14, height: 14, child: CircularProgressIndicator(strokeWidth: 2)) else TextButton.icon(onPressed: busy ? null : () => _do(() async {
              final r = asMap(await api.post('/admin/strategies/${s['code']}/backtest'));
              if (mounted) showToast(context, r['message'].toString());
            }), icon: const Icon(Icons.play_arrow, size: 16), label: Text(bt.isEmpty ? 'Chạy backtest' : 'Chạy lại')),
          ]),
          if (s['running'] == true) Text('Đang chạy 150 mã thanh khoản nhất, 3 năm (khoảng 5 phút)…', style: TextStyle(color: c.muted, fontSize: 12.5)),
          if (bt.isNotEmpty) _Compare(bt: bt, version: v),
          if (bt.isEmpty && s['running'] != true) Text('Chạy backtest để so sánh bản nháp với phiên bản hiện tại trước khi bật.', style: TextStyle(color: c.muted, fontSize: 12.5)),
          const SizedBox(height: 10),
          Row(children: [
            Expanded(child: FilledButton(
              onPressed: busy ? null : () async {
                if (!await confirmDialog(context, title: 'Bật phiên bản v${v + 1}?', message: bt.isEmpty ? 'Chưa có backtest cho bản nháp. Tham số mới áp dụng từ phiên tới và được ghi nhật ký.' : 'Tham số mới áp dụng từ phiên tới, phiên bản tăng lên v${v + 1}. Thao tác được ghi nhật ký.', confirmLabel: 'Bật phiên bản v${v + 1}')) return;
                await _do(() => api.post('/admin/strategies/${s['code']}/activate-draft'));
                if (context.mounted) showToast(context, 'Đã bật phiên bản v${v + 1}');
              },
              child: Text('Bật phiên bản v${v + 1}'),
            )),
          ]),
        ],
      ]),
    );
  }
}

class _Compare extends StatelessWidget {
  final Map<String, dynamic> bt;
  final int version;
  const _Compare({required this.bt, required this.version});
  @override
  Widget build(BuildContext context) {
    final c = context.vn;
    final live = asMap(bt['live']), draft = asMap(bt['draft']);
    final lc = asList(live['curve']), dc = asList(draft['curve']);
    List<FlSpot> spots(List<Map<String, dynamic>> xs) => [for (var i = 0; i < xs.length; i++) FlSpot(i.toDouble(), (asNum(xs[i]['value']) ?? 0).toDouble())];
    Widget row(String label, String a, String b, {bool better = false, bool worse = false}) => Padding(
          padding: const EdgeInsets.symmetric(vertical: 3),
          child: Row(children: [Expanded(child: Text(label, style: TextStyle(fontSize: 12.5, color: c.muted))), Text(a, style: TextStyle(fontSize: 12.5, color: c.muted)), const Text('  →  ', style: TextStyle(fontSize: 12.5)), Text(b, style: TextStyle(fontSize: 13, fontWeight: FontWeight.w700, color: better ? c.up : (worse ? c.down : c.text)))]),
        );
    num? n(Map m, String k) => asNum(m[k]);
    return Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
      Row(children: [Container(width: 14, height: 3, color: c.accent), const SizedBox(width: 4), Text('v${version + 1} nháp', style: TextStyle(fontSize: 11.5, color: c.muted)), const SizedBox(width: 10), Container(width: 14, height: 3, color: c.faint), const SizedBox(width: 4), Text('v$version hiện tại', style: TextStyle(fontSize: 11.5, color: c.muted))]),
      const SizedBox(height: 6),
      SizedBox(
        height: 120,
        child: (lc.isEmpty && dc.isEmpty)
            ? Center(child: Text('Không có tín hiệu nào trong kỳ thử', style: TextStyle(color: c.faint, fontSize: 12)))
            : LineChart(LineChartData(
                gridData: const FlGridData(show: false), titlesData: const FlTitlesData(show: false), borderData: FlBorderData(show: false), lineTouchData: const LineTouchData(enabled: false),
                lineBarsData: [
                  if (lc.isNotEmpty) LineChartBarData(spots: spots(lc), color: c.faint, barWidth: 2, dotData: const FlDotData(show: false)),
                  if (dc.isNotEmpty) LineChartBarData(spots: spots(dc), color: c.accent, barWidth: 2.5, dotData: const FlDotData(show: false)),
                ],
              )),
      ),
      const SizedBox(height: 6),
      Container(
        padding: const EdgeInsets.all(10),
        decoration: BoxDecoration(color: c.surface2, borderRadius: BorderRadius.circular(8)),
        child: Column(children: [
          row('Tỷ lệ đúng', '${n(live, 'win_rate') ?? '—'}%', '${n(draft, 'win_rate') ?? '—'}%', better: (n(draft, 'win_rate') ?? 0) > (n(live, 'win_rate') ?? 0), worse: (n(draft, 'win_rate') ?? 0) < (n(live, 'win_rate') ?? 0)),
          row('Lợi nhuận TB/lệnh', Fmt.pct(n(live, 'avg_return')), Fmt.pct(n(draft, 'avg_return')), better: (n(draft, 'avg_return') ?? 0) > (n(live, 'avg_return') ?? 0), worse: (n(draft, 'avg_return') ?? 0) < (n(live, 'avg_return') ?? 0)),
          row('Sụt giảm tối đa', Fmt.pct(n(live, 'max_drawdown')), Fmt.pct(n(draft, 'max_drawdown')), better: (n(draft, 'max_drawdown') ?? 0) > (n(live, 'max_drawdown') ?? 0), worse: (n(draft, 'max_drawdown') ?? 0) < (n(live, 'max_drawdown') ?? 0)),
          row('Số tín hiệu/tháng', '${n(live, 'per_month') ?? '—'}', '${n(draft, 'per_month') ?? '—'}'),
          row('Số lệnh', '${n(live, 'trades') ?? 0}', '${n(draft, 'trades') ?? 0}'),
        ]),
      ),
      Padding(padding: const EdgeInsets.only(top: 4), child: Text('${bt['symbols']} mã thanh khoản nhất, ${bt['years']} năm, kết quả sau 20 phiên · ${Fmt.relative(Fmt.parseDate(bt['at']))}', style: TextStyle(color: c.faint, fontSize: 11))),
    ]);
  }
}
