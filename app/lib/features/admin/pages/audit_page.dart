import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../../../core/format.dart';
import '../../../core/providers.dart';
import '../../../core/theme.dart';
import '../../../shared/widgets/common.dart';
import '../admin_common.dart';

/// A07 – Nhật ký kiểm toán: time, actor, action, target, IP; filter by action and actor; before/after as a diff; paging.
class AuditPage extends ConsumerStatefulWidget {
  const AuditPage({super.key});
  @override
  ConsumerState<AuditPage> createState() => _AuditPageState();
}

class _AuditPageState extends ConsumerState<AuditPage> {
  String? action;
  String actor = '';
  int page = 1;
  static const size = 50;

  @override
  Widget build(BuildContext context) {
    final c = context.vn;
    final path = '/admin/audit-logs?size=$size&page=$page${action != null ? '&action=$action' : ''}${actor.isNotEmpty ? '&actor=$actor' : ''}';
    final d = ref.watch(getMapProvider(path));
    return Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
      const AdminHeader('Nhật ký kiểm toán', subtitle: 'Mọi thao tác quản trị và đăng nhập. Giá trị trước/sau hiện dạng so sánh.'),
      d.when(
        loading: () => const SkeletonList(),
        error: (e, _) => ErrorBox(e),
        data: (a) {
          final total = asInt(a['total']) ?? 0;
          final pages = (total / size).ceil().clamp(1, 9999);
          return Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
            Wrap(spacing: 12, runSpacing: 8, crossAxisAlignment: WrapCrossAlignment.center, children: [
              SizedBox(width: 260, child: DropdownButtonFormField<String?>(initialValue: action, isDense: true, decoration: const InputDecoration(labelText: 'Hành động', isDense: true), items: [const DropdownMenuItem(value: null, child: Text('Tất cả')), for (final x in (a['actions'] as List? ?? [])) DropdownMenuItem(value: x.toString(), child: Text(auditActionVi[x] ?? x.toString()))], onChanged: (v) => setState(() {
                action = v;
                page = 1;
              }))),
              SizedBox(width: 240, child: TextField(decoration: const InputDecoration(labelText: 'Người thực hiện', isDense: true, prefixIcon: Icon(Icons.search, size: 18)), onSubmitted: (v) => setState(() {
                actor = v.trim();
                page = 1;
              }))),
              Text('$total bản ghi', style: TextStyle(color: c.muted, fontSize: 12.5)),
            ]),
            const SizedBox(height: 12),
            AppCard(
              padding: EdgeInsets.zero,
              child: SingleChildScrollView(
                scrollDirection: Axis.horizontal,
                child: DataTable(
                  headingTextStyle: TextStyle(fontSize: 12.5, color: c.muted, fontWeight: FontWeight.w600),
                  dataRowMinHeight: 44, dataRowMaxHeight: 76,
                  columns: const [DataColumn(label: Text('Thời gian')), DataColumn(label: Text('Người thực hiện')), DataColumn(label: Text('Hành động')), DataColumn(label: Text('Đối tượng')), DataColumn(label: Text('IP')), DataColumn(label: Text('Trước → sau'))],
                  rows: [
                    for (final r in asList(a['items']))
                      DataRow(cells: [
                        DataCell(cell(Fmt.dateTime(Fmt.parseDate(r['created_at'])))),
                        DataCell(cell(r['actor_email']?.toString() ?? '—')),
                        DataCell(Tooltip(message: r['action'].toString(), child: Pill(auditActionVi[r['action']] ?? r['action'].toString(), color: r['action'].toString().contains('DELETE') || r['action'].toString().contains('LOCK') ? c.down : c.accent, fontSize: 10.5))),
                        DataCell(cell('${r['target_type'] ?? ''} ${(r['target_id']?.toString() ?? '').length > 14 ? '${r['target_id'].toString().substring(0, 8)}…' : (r['target_id'] ?? '')}', color: c.muted, size: 12)),
                        DataCell(cell(r['ip']?.toString() ?? '', color: c.muted, size: 12)),
                        DataCell(SizedBox(width: 440, child: DiffView(before: r['before'], after: r['after']))),
                      ]),
                  ],
                ),
              ),
            ),
            const SizedBox(height: 10),
            Row(children: [
              IconButton(onPressed: page > 1 ? () => setState(() => page--) : null, icon: const Icon(Icons.chevron_left)),
              Text('Trang $page / $pages', style: TextStyle(color: c.muted, fontSize: 12.5)),
              IconButton(onPressed: page < pages ? () => setState(() => page++) : null, icon: const Icon(Icons.chevron_right)),
            ]),
          ]);
        },
      ),
    ]);
  }
}
