import 'dart:async';

import 'package:file_picker/file_picker.dart';
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

const _path = '/admin/jobs?limit=60';

/// A04 – Dữ liệu & tác vụ: 4 KPI tiles, job table (schedule, queue, last run, run again / stop), alert-latency p95 chart,
/// daily data-quality checks, backup price-file import, data sources, run log.
class JobsPage extends ConsumerStatefulWidget {
  const JobsPage({super.key});
  @override
  ConsumerState<JobsPage> createState() => _JobsPageState();
}

class _JobsPageState extends ConsumerState<JobsPage> {
  String filter = 'ALL';
  bool showLog = false;
  Timer? poll;

  @override
  void initState() {
    super.initState();
    poll = Timer.periodic(const Duration(seconds: 20), (_) {
      final d = ref.read(getMapProvider(_path)).value;
      if (d != null && asList(d['jobs']).any((j) => j['running'] == true)) ref.invalidate(getProvider(_path));
    });
  }

  @override
  void dispose() {
    poll?.cancel();
    super.dispose();
  }

  void _refresh() => ref.invalidate(getProvider(_path));

  @override
  Widget build(BuildContext context) {
    final c = context.vn;
    final data = ref.watch(getMapProvider(_path));
    return Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
      AdminHeader('Dữ liệu & tác vụ', subtitle: 'Theo dõi tác vụ nền, hàng đợi và chất lượng dữ liệu. Có thể chạy lại tác vụ ngoài giờ giao dịch.', actions: [
        IconButton(tooltip: 'Tải lại', onPressed: _refresh, icon: const Icon(Icons.refresh)),
        OutlinedButton.icon(onPressed: () => setState(() => showLog = !showLog), icon: const Icon(Icons.list_alt, size: 18), label: Text(showLog ? 'Ẩn nhật ký' : 'Nhật ký chạy')),
      ]),
      data.when(
        loading: () => const SkeletonList(),
        error: (e, _) => ErrorBox(e, onRetry: _refresh),
        data: (d) {
          final k = asMap(d['kpis']);
          final jobs = asList(d['jobs']).where((j) => filter == 'ALL' || (filter == 'FAILED' && (j['status'] == 'FAILED' || j['status'] == 'WARN')) || (filter == 'RUNNING' && j['running'] == true)).toList();
          final latency = asList(d['latency']);
          final quality = asList(d['quality']);
          final queue = asInt(k['queue_pending']) ?? 0;
          final failed = asInt(k['failed_24h']) ?? 0;
          final backupAt = Fmt.parseDate(k['last_backup_at']);
          return Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
            LayoutBuilder(builder: (ctx, box) {
              final tw = box.maxWidth < 800 ? (box.maxWidth - 12) / 2 : (box.maxWidth - 36) / 4;
              return Wrap(spacing: 12, runSpacing: 12, children: [
                SizedBox(width: tw, child: KpiTile(label: 'Hàng đợi đang chờ', value: Fmt.price(queue), note: 'ngưỡng cảnh báo ${Fmt.price(asNum(k['queue_warn']))}', valueColor: queue > (asInt(k['queue_warn']) ?? 1000) ? c.down : null)),
                SizedBox(width: tw, child: KpiTile(label: 'Tác vụ lỗi 24 giờ', value: '$failed', note: (k['failed_names'] as List? ?? []).isEmpty ? 'không có lỗi' : (k['failed_names'] as List).join(', '), valueColor: failed > 0 ? c.ref : c.up)),
                SizedBox(width: tw, child: KpiTile(label: 'Dung lượng CSDL', value: k['db_size_pretty']?.toString() ?? '—', note: 'Postgres trên Railway')),
                SizedBox(width: tw, child: KpiTile(label: 'Sao lưu gần nhất', value: backupAt != null ? fmtHm(backupAt) : '—', note: backupAt != null ? '${Fmt.date(backupAt, year: true)} · khôi phục thử: ${k['last_restore_test'] == true ? 'đạt' : (k['last_restore_test'] == false ? 'LỖI' : 'chưa chạy')}' : 'chạy 01:30 hằng ngày, kèm khôi phục thử', valueColor: k['last_backup_status'] == 'DONE' && k['last_restore_test'] != false ? c.up : (k['last_backup_status'] == null ? null : c.ref))),
              ]);
            }),
            const SizedBox(height: 16),
            AppCard(
              padding: EdgeInsets.zero,
              child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
                Padding(padding: const EdgeInsets.fromLTRB(16, 12, 12, 4), child: Row(children: [
                  Expanded(child: Text('Tác vụ nền', style: Theme.of(context).textTheme.titleMedium)),
                  Segmented<String>(options: const [('ALL', 'Tất cả'), ('FAILED', 'Lỗi'), ('RUNNING', 'Đang chạy')], value: filter, onChanged: (v) => setState(() => filter = v)),
                ])),
                SingleChildScrollView(
                  scrollDirection: Axis.horizontal,
                  child: ConstrainedBox(
                    constraints: BoxConstraints(minWidth: context.isDesktop ? 900 : 0),
                    child: DataTable(
                      headingTextStyle: TextStyle(fontSize: 12.5, color: c.muted, fontWeight: FontWeight.w600),
                      columns: const [DataColumn(label: Text('Tác vụ')), DataColumn(label: Text('Lịch')), DataColumn(label: Text('Hàng đợi')), DataColumn(label: Text('Lần chạy gần nhất')), DataColumn(label: Text('Thời gian')), DataColumn(label: Text('Trạng thái')), DataColumn(label: Text('Thao tác'))],
                      rows: [
                        for (final j in jobs)
                          DataRow(cells: [
                            DataCell(Column(mainAxisAlignment: MainAxisAlignment.center, crossAxisAlignment: CrossAxisAlignment.start, children: [Text(j['name'].toString(), style: const TextStyle(fontWeight: FontWeight.w700, fontFamily: 'monospace', fontSize: 13)), Text(j['label'].toString(), style: TextStyle(fontSize: 11.5, color: c.muted))])),
                            DataCell(Column(mainAxisAlignment: MainAxisAlignment.center, crossAxisAlignment: CrossAxisAlignment.start, children: [cell(j['schedule'].toString()), if (j['next_run'] != null) Text('tiếp ${Fmt.dateTime(Fmt.parseDate(j['next_run']))}', style: TextStyle(fontSize: 11, color: c.faint))])),
                            DataCell(cell(j['queue'].toString(), color: c.muted)),
                            DataCell(cell(j['last_run_at'] != null ? Fmt.dateTime(Fmt.parseDate(j['last_run_at'])) : '—')),
                            DataCell(cell(j['running'] == true ? '—' : fmtDuration(asNum(j['duration_ms'])))),
                            DataCell(Tooltip(message: j['summary']?.toString() ?? '', child: StatusPill(j['status'].toString(), label: j['status'] == 'WARN' && j['summary'] != null ? 'Chậm / cảnh báo' : null))),
                            DataCell(j['running'] == true
                                ? OutlinedButton(style: OutlinedButton.styleFrom(visualDensity: VisualDensity.compact, foregroundColor: c.down), onPressed: j['stoppable'] == true ? () => _stop(context, j['name'].toString()) : null, child: const Text('Dừng'))
                                : OutlinedButton(style: OutlinedButton.styleFrom(visualDensity: VisualDensity.compact), onPressed: () => runJob(context, ref, j['name'].toString(), refresh: const [_path, '/admin/overview']), child: const Text('Chạy lại'))),
                          ]),
                      ],
                    ),
                  ),
                ),
                if (jobs.isEmpty) Padding(padding: const EdgeInsets.all(20), child: Text('Không có tác vụ ở mục này.', style: TextStyle(color: c.muted))),
                Padding(padding: const EdgeInsets.fromLTRB(16, 4, 16, 12), child: Text('Chạy lại trong giờ giao dịch cần xác nhận. "Dừng" chỉ áp dụng cho tác vụ đang chạy trong tiến trình hiện tại.', style: TextStyle(color: c.faint, fontSize: 11.5))),
              ]),
            ),
            const SizedBox(height: 16),
            if (showLog) ...[_RunLog(runs: asList(d['runs'])), const SizedBox(height: 16)],
            Flex(
              direction: context.isDesktop ? Axis.horizontal : Axis.vertical,
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                Expanded(flex: context.isDesktop ? 1 : 0, child: _LatencyChart(buckets: latency)),
                SizedBox(width: context.isDesktop ? 16 : 0, height: context.isDesktop ? 0 : 16),
                Expanded(flex: context.isDesktop ? 1 : 0, child: AppCard(child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
                  Text('Kiểm tra chất lượng dữ liệu hôm nay', style: Theme.of(context).textTheme.titleMedium),
                  const SizedBox(height: 6),
                  for (final q in quality)
                    Padding(
                      padding: const EdgeInsets.symmetric(vertical: 6),
                      child: Row(children: [
                        Icon(q['ok'] == null ? Icons.remove_circle_outline : (q['ok'] == true ? Icons.check_circle_outline : Icons.warning_amber_rounded), color: q['ok'] == null ? c.faint : (q['ok'] == true ? c.up : c.ref), size: 18),
                        const SizedBox(width: 8),
                        Expanded(child: Text(q['check'].toString(), style: const TextStyle(fontSize: 13))),
                        Flexible(child: Text('${q['value']}${q['detail'] != null && q['ok'] != true ? ' (${q['detail']})' : ''}', textAlign: TextAlign.right, maxLines: 2, overflow: TextOverflow.ellipsis, style: TextStyle(fontWeight: FontWeight.w700, fontSize: 13, color: q['ok'] == null ? c.muted : (q['ok'] == true ? c.up : c.ref)))),
                      ]),
                    ),
                ]))),
              ],
            ),
            const SizedBox(height: 16),
            _PriceImportCard(onDone: _refresh),
            const SizedBox(height: 16),
            const _SourcesCard(),
          ]);
        },
      ),
    ]);
  }

  Future<void> _stop(BuildContext context, String name) async {
    if (!await confirmDialog(context, title: 'Dừng tác vụ $name?', message: 'Tác vụ bị hủy giữa chừng; dữ liệu đã ghi trước đó giữ nguyên. Thao tác được ghi nhật ký.', confirmLabel: 'Dừng', danger: true)) return;
    try {
      final r = asMap(await ref.read(apiProvider).post('/admin/jobs/$name/stop'));
      if (context.mounted) showToast(context, r['message'].toString());
      Future.delayed(const Duration(seconds: 2), _refresh);
    } on ApiException catch (e) {
      if (context.mounted) showToast(context, e.message, error: true);
    }
  }
}

class _LatencyChart extends StatelessWidget {
  final List<Map<String, dynamic>> buckets;
  const _LatencyChart({required this.buckets});
  @override
  Widget build(BuildContext context) {
    final c = context.vn;
    final maxV = buckets.fold<double>(60, (m, b) => ((asNum(b['p95_ms']) ?? 0) / 1000).toDouble() > m ? ((asNum(b['p95_ms']) ?? 0) / 1000).toDouble() : m);
    return AppCard(child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
      Text('Độ trễ cảnh báo trong phiên (giây, p95 theo 15 phút)', style: Theme.of(context).textTheme.titleMedium),
      Text('Vạch mục tiêu 60 giây · ngày gần nhất có cảnh báo gửi ngoài ứng dụng', style: TextStyle(color: c.muted, fontSize: 12)),
      const SizedBox(height: 10),
      SizedBox(
        height: 180,
        child: buckets.isEmpty
            ? Center(child: Text('Chưa có cảnh báo nào gửi qua push/Telegram/email trong phiên.', style: TextStyle(color: c.faint, fontSize: 12.5)))
            : BarChart(BarChartData(
                maxY: maxV * 1.15,
                gridData: const FlGridData(show: false),
                borderData: FlBorderData(show: false),
                barTouchData: BarTouchData(touchTooltipData: BarTouchTooltipData(getTooltipItem: (g, gi, rod, ri) => BarTooltipItem('${buckets[gi]['bucket']}: ${rod.toY.toStringAsFixed(1)} giây (${buckets[gi]['count']} cảnh báo)', TextStyle(color: c.text, fontSize: 12)))),
                titlesData: FlTitlesData(
                  leftTitles: AxisTitles(sideTitles: SideTitles(showTitles: true, reservedSize: 32, getTitlesWidget: (v, _) => Text(v.toStringAsFixed(0), style: TextStyle(fontSize: 10, color: c.faint)))),
                  rightTitles: const AxisTitles(), topTitles: const AxisTitles(),
                  bottomTitles: AxisTitles(sideTitles: SideTitles(showTitles: true, reservedSize: 22, getTitlesWidget: (v, _) {
                    final i = v.toInt();
                    if (i < 0 || i >= buckets.length || (buckets.length > 8 && i % 4 != 0)) return const SizedBox.shrink();
                    return Text(buckets[i]['bucket'].toString(), style: TextStyle(fontSize: 10, color: c.faint));
                  })),
                ),
                extraLinesData: ExtraLinesData(horizontalLines: [HorizontalLine(y: 60, color: c.down.withValues(alpha: 0.7), strokeWidth: 1, dashArray: [4, 4])]),
                barGroups: [for (var i = 0; i < buckets.length; i++) BarChartGroupData(x: i, barRods: [BarChartRodData(toY: ((asNum(buckets[i]['p95_ms']) ?? 0) / 1000).toDouble(), color: ((asNum(buckets[i]['p95_ms']) ?? 0) > 60000) ? c.down : c.accent, width: 10, borderRadius: BorderRadius.circular(3))])],
              )),
      ),
    ]));
  }
}

class _RunLog extends ConsumerWidget {
  final List<Map<String, dynamic>> runs;
  const _RunLog({required this.runs});
  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final c = context.vn;
    return AppCard(
      padding: EdgeInsets.zero,
      child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
        Padding(padding: const EdgeInsets.fromLTRB(16, 12, 16, 4), child: Text('Nhật ký chạy gần đây', style: Theme.of(context).textTheme.titleMedium)),
        SingleChildScrollView(
          scrollDirection: Axis.horizontal,
          child: DataTable(
            headingTextStyle: TextStyle(fontSize: 12.5, color: c.muted, fontWeight: FontWeight.w600),
            columns: const [DataColumn(label: Text('Tác vụ')), DataColumn(label: Text('Trạng thái')), DataColumn(label: Text('Bắt đầu')), DataColumn(label: Text('Thời gian')), DataColumn(label: Text('Kết quả')), DataColumn(label: Text('Kích hoạt bởi')), DataColumn(label: Text(''))],
            rows: [
              for (final r in runs)
                DataRow(cells: [
                  DataCell(Column(mainAxisAlignment: MainAxisAlignment.center, crossAxisAlignment: CrossAxisAlignment.start, children: [Text(r['name'].toString(), style: const TextStyle(fontWeight: FontWeight.w600, fontFamily: 'monospace', fontSize: 12.5)), Text(r['label'].toString(), style: TextStyle(fontSize: 11, color: c.muted))])),
                  DataCell(StatusPill(r['status'].toString())),
                  DataCell(cell(Fmt.dateTime(Fmt.parseDate(r['started_at'])))),
                  DataCell(cell(fmtDuration(asNum(r['duration_ms'])))),
                  DataCell(SizedBox(width: 360, child: Text(r['summary']?.toString() ?? '', maxLines: 2, overflow: TextOverflow.ellipsis, style: TextStyle(fontSize: 12, color: r['status'] == 'FAILED' ? c.down : null)))),
                  DataCell(cell(r['triggered_by']?.toString() ?? '', color: c.muted)),
                  DataCell(TextButton(onPressed: () => showJobRun(context, ref, asInt(r['id'])!), child: const Text('Log'))),
                ]),
            ],
          ),
        ),
      ]),
    );
  }
}

class _SourcesCard extends ConsumerWidget {
  const _SourcesCard();
  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final c = context.vn;
    final ds = ref.watch(getMapProvider('/admin/data-sources'));
    return ds.when(
      loading: () => const SkeletonCard(),
      error: (e, _) => ErrorBox(e),
      data: (d) => AppCard(child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
        Text('Nguồn dữ liệu', style: Theme.of(context).textTheme.titleMedium),
        for (final s in asList(d['sources']))
          ListTile(
            dense: true, contentPadding: EdgeInsets.zero,
            leading: StatusDot({'OK': c.up, 'DEGRADED': c.ref, 'DOWN': c.down}[s['status']] ?? c.faint, size: 10),
            title: Text('${s['name']} (${s['code']})', style: const TextStyle(fontWeight: FontWeight.w600, fontSize: 13.5)),
            subtitle: Text('${s['role'] == 'PRIMARY' ? 'Chính' : 'Dự phòng'} · ưu tiên ${s['priority']} · ${s['latency_ms'] ?? '—'} ms · lỗi liên tiếp ${s['consecutive_failures']} · cập nhật ${Fmt.relative(Fmt.parseDate(s['last_ok_at']))}${s['last_error'] != null ? '\n${s['last_error']}' : ''}', style: TextStyle(fontSize: 11.5, color: s['last_error'] != null ? c.down : c.muted)),
            trailing: Switch(value: s['enabled'] == true, onChanged: (v) async {
              if (!v && !await confirmDialog(context, title: 'Tắt nguồn ${s['name']}?', message: 'Hệ thống chuyển sang nguồn còn lại. Thao tác được ghi nhật ký.', confirmLabel: 'Tắt', danger: true)) return;
              await ref.read(apiProvider).put('/admin/data-sources/${s['code']}', query: {'enabled': v});
              ref.invalidate(getProvider('/admin/data-sources'));
            }),
          ),
        Text('Giá gần nhất: ${Fmt.date(Fmt.parseDate(asMap(d['coverage'])['last_price_date']), year: true)} · ${asMap(d['coverage'])['symbols_with_prices']} mã', style: TextStyle(color: c.faint, fontSize: 12)),
      ])),
    );
  }
}

class _PriceImportCard extends ConsumerStatefulWidget {
  final VoidCallback onDone;
  const _PriceImportCard({required this.onDone});
  @override
  ConsumerState<_PriceImportCard> createState() => _PriceImportCardState();
}

class _PriceImportCardState extends ConsumerState<_PriceImportCard> {
  Map<String, dynamic>? preview;
  bool importing = false;

  @override
  Widget build(BuildContext context) {
    final c = context.vn;
    return AppCard(child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
      Row(children: [Expanded(child: Text('Nhập file giá dự phòng', style: Theme.of(context).textTheme.titleMedium)), FilledButton.icon(onPressed: importing ? null : _pick, icon: const Icon(Icons.upload_file, size: 16), label: Text(importing ? 'Đang đọc…' : 'Nhập file giá'))]),
      Text('Dùng khi cả hai nguồn API cùng lỗi hoặc cần nạp lịch sử. CSV, TXT hoặc Excel ≤ 20 MB; cột nhận dạng theo tên tiếng Việt hoặc Anh: mã, ngày, mở cửa, cao nhất, thấp nhất, đóng cửa, khối lượng.', style: TextStyle(color: c.muted, fontSize: 12.5)),
      if (preview != null) ...[
        const SizedBox(height: 10),
        Wrap(spacing: 16, runSpacing: 6, children: [LabeledValue('Tệp', preview!['filename'].toString()), LabeledValue('Đơn vị', preview!['unit'].toString()), LabeledValue('Dòng hợp lệ', '${preview!['rows_ok']}'), LabeledValue('Dòng lỗi', '${preview!['rows_error']}', color: (asInt(preview!['rows_error']) ?? 0) > 0 ? c.down : null), LabeledValue('Phiên mới', '${preview!['new_sessions']}'), LabeledValue('Trùng', '${preview!['duplicate_sessions']}'), LabeledValue('Lệch > 0,5%', '${asList(preview!['mismatches']).length}', color: asList(preview!['mismatches']).isNotEmpty ? c.ref : null)]),
        const SizedBox(height: 8),
        Text('Xem trước 20 dòng đầu', style: TextStyle(color: c.muted, fontSize: 12)),
        SingleChildScrollView(scrollDirection: Axis.horizontal, child: DataTable(headingTextStyle: TextStyle(fontSize: 12, color: c.muted), columns: const [DataColumn(label: Text('Mã')), DataColumn(label: Text('Ngày')), DataColumn(label: Text('Mở')), DataColumn(label: Text('Cao')), DataColumn(label: Text('Thấp')), DataColumn(label: Text('Đóng')), DataColumn(label: Text('KL'))], rows: [for (final r in asList(preview!['preview']).take(20)) DataRow(cells: [DataCell(cell(r['symbol'].toString(), bold: true)), DataCell(cell(r['date'].toString())), DataCell(cell(Fmt.price(asNum(r['open'])))), DataCell(cell(Fmt.price(asNum(r['high'])))), DataCell(cell(Fmt.price(asNum(r['low'])))), DataCell(cell(Fmt.price(asNum(r['close'])))), DataCell(cell(Fmt.volume(asNum(r['volume']))))])])),
        if (asList(preview!['errors']).isNotEmpty) Padding(padding: const EdgeInsets.only(top: 6), child: Text('Dòng lỗi: ${asList(preview!['errors']).take(10).map((e) => 'dòng ${e['row']}: ${e['error']}').join('; ')}', style: TextStyle(color: c.down, fontSize: 12))),
        if (asList(preview!['mismatches']).isNotEmpty) Padding(padding: const EdgeInsets.only(top: 6), child: Text('Lệch so với API (đánh dấu để bạn xem): ${asList(preview!['mismatches']).take(8).map((m) => '${m['symbol']} ${m['date']} file ${Fmt.price(asNum(m['file']))} / API ${Fmt.price(asNum(m['api']))}').join('; ')}', style: TextStyle(color: c.ref, fontSize: 12))),
        const SizedBox(height: 8),
        Row(children: [FilledButton(onPressed: () => _commit('SKIP_EXISTING'), child: const Text('Ghi (bỏ qua trùng)')), const SizedBox(width: 8), OutlinedButton(onPressed: () => _commit('OVERWRITE'), child: const Text('Ghi đè')), const SizedBox(width: 8), TextButton(onPressed: () => setState(() => preview = null), child: const Text('Hủy'))]),
      ],
    ]));
  }

  Future<void> _pick() async {
    final picked = await FilePicker.pickFiles(type: FileType.custom, allowedExtensions: ['csv', 'txt', 'xlsx']);
    if (picked.isEmpty) return;
    setState(() => importing = true);
    try {
      final bytes = await picked.first.xFile.readAsBytes();
      preview = asMap(await ref.read(apiProvider).upload('/admin/price-imports', bytes, picked.first.name));
    } on ApiException catch (e) {
      if (mounted) showToast(context, e.message, error: true);
    } finally {
      if (mounted) setState(() => importing = false);
    }
  }

  Future<void> _commit(String mode) async {
    if (mode == 'OVERWRITE' && !await confirmDialog(context, title: 'Ghi đè giá đã có?', message: 'Các phiên trùng sẽ lấy giá trong file thay cho giá từ API.', confirmLabel: 'Ghi đè', danger: true)) return;
    try {
      final r = asMap(await ref.read(apiProvider).post('/admin/price-imports/${preview!['import_id']}/commit', query: {'mode': mode}));
      setState(() => preview = null);
      widget.onDone();
      if (mounted) showToast(context, 'Đã ghi ${r['rows']} dòng cho ${(r['symbols'] as List? ?? []).length} mã. Đang tính lại chỉ báo, điểm, tín hiệu.');
    } on ApiException catch (e) {
      if (mounted) showToast(context, e.message, error: true);
    }
  }
}
