import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../../../core/providers.dart';
import '../../../core/theme.dart';
import '../../../shared/widgets/common.dart';
import '../admin_common.dart';

/// A05 – Cấu hình chấm điểm & thông số giao dịch: every key as a labelled form with unit, default, last editor and history.
/// Risk keys live on A09; the weights slider on A03.
class ConfigPage extends ConsumerStatefulWidget {
  final String? focusKey;
  const ConfigPage({super.key, this.focusKey});
  @override
  ConsumerState<ConfigPage> createState() => _ConfigPageState();
}

class _ConfigPageState extends ConsumerState<ConfigPage> {
  String group = 'scoring';
  static const groups = [('scoring', 'Chấm điểm & xếp loại'), ('strategy', 'Chiến lược & nền giá'), ('market', 'Thông số sàn'), ('alerts', 'Cảnh báo'), ('ai', 'AI'), ('macro', 'Vĩ mô')];

  @override
  void initState() {
    super.initState();
    if (widget.focusKey != null) group = widget.focusKey!.split('.').first;
    if (group == 'signals') group = 'ai';
    if (group == 'base' || group == 'regime') group = group == 'base' ? 'strategy' : 'scoring';
  }

  @override
  Widget build(BuildContext context) {
    final c = context.vn;
    final rows = ref.watch(getListProvider('/admin/config'));
    return Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
      const AdminHeader('Cấu hình chấm điểm & thông số giao dịch', subtitle: 'Ngưỡng xếp loại, tỷ trọng theo trạng thái thị trường, tham số chiến lược, thông số sàn. Mỗi trường có mô tả, giá trị mặc định, người sửa cuối và lịch sử thay đổi.'),
      Wrap(spacing: 6, runSpacing: 6, children: [for (final g in groups) ChoiceChip(label: Text(g.$2), selected: group == g.$1, onSelected: (_) => setState(() => group = g.$1))]),
      const SizedBox(height: 14),
      rows.when(
        loading: () => const SkeletonList(),
        error: (e, _) => ErrorBox(e),
        data: (list) {
          final visible = list.where((r) => r['group'] == group && r['group'] != 'risk').toList();
          return Column(children: [
            for (final r in visible) Padding(padding: const EdgeInsets.only(bottom: 12), child: ConfigCard(key: ValueKey(r['key']), row: r, highlight: r['key'] == widget.focusKey, onChanged: () => ref.invalidate(getProvider('/admin/config')))),
            if (visible.isEmpty) Text('Không có mục nào.', style: TextStyle(color: c.muted)),
            Padding(padding: const EdgeInsets.only(top: 4), child: Text('Giới hạn rủi ro nằm ở mục Giới hạn rủi ro & ký quỹ. Mọi thay đổi được ghi vào nhật ký kiểm toán và áp dụng từ lần xử lý tới.', style: TextStyle(color: c.faint, fontSize: 12))),
          ]);
        },
      ),
    ]);
  }
}
