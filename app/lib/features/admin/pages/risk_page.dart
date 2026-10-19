import 'package:file_picker/file_picker.dart';
import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../../../core/api.dart';
import '../../../core/format.dart';
import '../../../core/providers.dart';
import '../../../core/theme.dart';
import '../../../shared/widgets/common.dart';
import '../admin_common.dart';

/// A09 – Giới hạn rủi ro & ký quỹ: default limits for new users (form), pretrade / company-risk / correlation
/// parameters, margin lists per broker (file import), system-wide guard statistics.
class RiskPage extends ConsumerWidget {
  const RiskPage({super.key});
  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final c = context.vn;
    final stats = ref.watch(getMapProvider('/admin/risk-stats'));
    final cfg = ref.watch(getListProvider('/admin/config'));
    return Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
      const AdminHeader('Giới hạn rủi ro & ký quỹ', subtitle: 'Giới hạn mặc định cho người dùng mới, tham số kiểm tra trước khi mua, danh sách mã cho vay ký quỹ. Thống kê toàn hệ thống, không xem chi tiết giao dịch cá nhân.'),
      stats.when(
        loading: () => const SkeletonCard(),
        error: (e, _) => ErrorBox(e),
        data: (s) => Wrap(spacing: 12, runSpacing: 12, children: [
          for (final e in [('Cầu dao bật', 'GUARD_ON'), ('Hạ cắt lỗ', 'STOP_LOWERED'), ('Bình quân giá xuống', 'AVERAGE_DOWN'), ('Vượt rào Đỏ', 'RED_OVERRIDE')]) SizedBox(width: 190, child: KpiTile(label: '${e.$1} (${s['days']} ngày)', value: Fmt.price(asNum(asMap(s['events'])[e.$2]) ?? 0))),
          for (final e in [('Kiểm tra Xanh', 'GREEN'), ('Kiểm tra Vàng', 'YELLOW'), ('Kiểm tra Đỏ', 'RED')]) SizedBox(width: 160, child: KpiTile(label: e.$1, value: Fmt.price(asNum(asMap(s['pretrade'])[e.$2]) ?? 0), valueColor: c.levelColor(e.$2))),
        ]),
      ),
      const SizedBox(height: 16),
      cfg.when(
        loading: () => const SkeletonCard(),
        error: (e, _) => ErrorBox(e),
        data: (rows) => Column(children: [for (final r in rows.where((r) => r['group'] == 'risk')) Padding(padding: const EdgeInsets.only(bottom: 12), child: ConfigCard(key: ValueKey(r['key']), row: r, onChanged: () => ref.invalidate(getProvider('/admin/config'))))]),
      ),
      const _MarginLists(),
    ]);
  }
}

class _MarginLists extends ConsumerStatefulWidget {
  const _MarginLists();
  @override
  ConsumerState<_MarginLists> createState() => _MarginListsState();
}

class _MarginListsState extends ConsumerState<_MarginLists> {
  final ctl = TextEditingController();
  bool loaded = false, editing = false, busy = false;

  Future<void> _import() async {
    final picked = await FilePicker.pickFiles(type: FileType.custom, allowedExtensions: ['csv', 'txt', 'xlsx']);
    if (picked.isEmpty) return;
    final replace = await showDialog<bool>(context: context, builder: (ctx) => AlertDialog(title: const Text('Nhập danh sách ký quỹ'), content: const Text('Tệp có 2 cột (công ty chứng khoán, mã) hoặc mỗi cột một công ty. Thay toàn bộ danh sách hiện có hay bổ sung?'),
        actions: [TextButton(onPressed: () => Navigator.pop(ctx), child: const Text('Hủy')), OutlinedButton(onPressed: () => Navigator.pop(ctx, false), child: const Text('Bổ sung')), FilledButton(onPressed: () => Navigator.pop(ctx, true), child: const Text('Thay toàn bộ'))]));
    if (replace == null) return;
    setState(() => busy = true);
    try {
      final bytes = await picked.first.xFile.readAsBytes();
      final r = asMap(await ref.read(apiProvider).upload('/admin/margin-lists/import', bytes, picked.first.name, query: {'replace': replace}));
      loaded = false;
      ref.invalidate(getProvider('/admin/margin-lists'));
      final unknown = (r['unknown_symbols'] as List? ?? []);
      if (mounted) showToast(context, 'Đã nhập ${asMap(r['imported']).entries.map((e) => '${e.key}: ${e.value} mã').join(', ')}${unknown.isNotEmpty ? ' · ${unknown.length} mã không có trong danh sách niêm yết (${unknown.take(5).join(', ')})' : ''}');
    } on ApiException catch (e) {
      if (mounted) showToast(context, e.message, error: true);
    } finally {
      if (mounted) setState(() => busy = false);
    }
  }

  @override
  Widget build(BuildContext context) {
    final c = context.vn;
    final data = ref.watch(getMapProvider('/admin/margin-lists'));
    return data.when(
      loading: () => const Skeleton(),
      error: (e, _) => const SizedBox.shrink(),
      data: (m) {
        if (!loaded) {
          ctl.text = m.entries.map((e) => '${e.key}: ${(e.value as List).join(', ')}').join('\n');
          loaded = true;
        }
        return AppCard(child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
          Row(children: [
            Expanded(child: Text('Danh sách mã cho vay ký quỹ theo công ty chứng khoán', style: Theme.of(context).textTheme.titleMedium)),
            TextButton(onPressed: () => setState(() => editing = !editing), child: Text(editing ? 'Đóng' : 'Sửa tay')),
            FilledButton.icon(onPressed: busy ? null : _import, icon: const Icon(Icons.upload_file, size: 16), label: const Text('Nhập file')),
          ]),
          Text('Dùng cho Kiểm tra trước khi mua (mã có được vay ký quỹ ở công ty của người dùng không).', style: TextStyle(color: c.muted, fontSize: 12.5)),
          const SizedBox(height: 10),
          if (m.isEmpty) Text('Chưa có danh sách nào. Nhập file CSV/Excel từ công ty chứng khoán.', style: TextStyle(color: c.faint, fontSize: 13)),
          Wrap(spacing: 10, runSpacing: 10, children: [
            for (final e in m.entries)
              Container(
                width: 260, padding: const EdgeInsets.all(12),
                decoration: BoxDecoration(color: c.surface2, borderRadius: BorderRadius.circular(10)),
                child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
                  Row(children: [Expanded(child: Text(e.key, style: const TextStyle(fontWeight: FontWeight.w700))), Text('${(e.value as List).length} mã', style: TextStyle(color: c.muted, fontSize: 12))]),
                  const SizedBox(height: 4),
                  Text((e.value as List).take(24).join(', ') + ((e.value as List).length > 24 ? '…' : ''), style: TextStyle(fontSize: 12, color: c.muted), maxLines: 3, overflow: TextOverflow.ellipsis),
                ]),
              ),
          ]),
          if (editing) ...[
            const SizedBox(height: 10),
            Text('Mỗi dòng: TÊN CTCK: MÃ1, MÃ2, …', style: TextStyle(color: c.muted, fontSize: 12)),
            TextField(controller: ctl, minLines: 3, maxLines: 10, style: const TextStyle(fontFamily: 'monospace', fontSize: 12)),
            const SizedBox(height: 8),
            Align(alignment: Alignment.centerRight, child: FilledButton(onPressed: () async {
              final body = <String, List<String>>{};
              for (final ln in ctl.text.split('\n')) {
                final i = ln.indexOf(':');
                if (i <= 0) continue;
                body[ln.substring(0, i).trim()] = ln.substring(i + 1).split(',').map((s) => s.trim().toUpperCase()).where((s) => s.isNotEmpty).toList();
              }
              try {
                await ref.read(apiProvider).put('/admin/margin-lists', data: body);
                loaded = false;
                ref.invalidate(getProvider('/admin/margin-lists'));
                if (context.mounted) showToast(context, 'Đã lưu danh sách ký quỹ');
              } on ApiException catch (e) {
                if (context.mounted) showToast(context, e.message, error: true);
              }
            }, child: const Text('Lưu'))),
          ],
        ]));
      },
    );
  }
}
