import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../../../core/api.dart';
import '../../../core/format.dart';
import '../../../core/providers.dart';
import '../../../core/responsive.dart';
import '../../../core/theme.dart';
import '../../../shared/widgets/common.dart';
import '../admin_common.dart';

/// A06 – Thông báo chung: compose (title, body, channels), phone preview, history with sent / read counts.
class BroadcastsPage extends ConsumerStatefulWidget {
  const BroadcastsPage({super.key});
  @override
  ConsumerState<BroadcastsPage> createState() => _BroadcastsPageState();
}

class _BroadcastsPageState extends ConsumerState<BroadcastsPage> {
  final title = TextEditingController(), body = TextEditingController();
  final channels = {'push', 'telegram'};
  bool sending = false;

  @override
  Widget build(BuildContext context) {
    final c = context.vn;
    final hist = ref.watch(getListProvider('/admin/broadcasts'));
    final compose = AppCard(child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
      Text('Soạn thông báo', style: Theme.of(context).textTheme.titleMedium),
      const SizedBox(height: 8),
      TextField(controller: title, maxLength: 120, decoration: const InputDecoration(labelText: 'Tiêu đề'), onChanged: (_) => setState(() {})),
      const SizedBox(height: 4),
      TextField(controller: body, minLines: 4, maxLines: 8, maxLength: 1000, decoration: const InputDecoration(labelText: 'Nội dung'), onChanged: (_) => setState(() {})),
      const SizedBox(height: 8),
      Text('Kênh gửi', style: TextStyle(color: c.muted, fontSize: 12.5)),
      const SizedBox(height: 4),
      Wrap(spacing: 6, children: [for (final ch in const [('push', 'Thông báo đẩy'), ('telegram', 'Telegram'), ('email', 'Email')]) FilterChip(label: Text(ch.$2), selected: channels.contains(ch.$1), onSelected: (v) => setState(() => v ? channels.add(ch.$1) : channels.remove(ch.$1)))]),
      Text('Trong ứng dụng luôn hiện ở mục Cảnh báo của mọi người dùng đang hoạt động.', style: TextStyle(color: c.faint, fontSize: 11.5)),
      const SizedBox(height: 12),
      Align(alignment: Alignment.centerRight, child: FilledButton.icon(
        onPressed: title.text.trim().isEmpty || sending ? null : () async {
          if (!await confirmDialog(context, title: 'Gửi cho tất cả người dùng?', message: '"${title.text.trim()}" sẽ gửi tới mọi tài khoản đang hoạt động qua ${channels.isEmpty ? 'trong ứng dụng' : channels.join(', ')}. Không thu hồi được.', confirmLabel: 'Gửi')) return;
          setState(() => sending = true);
          try {
            final r = asMap(await ref.read(apiProvider).post('/admin/broadcasts', data: {'title': title.text.trim(), 'body': body.text.trim(), 'channels': channels.toList()}));
            title.clear();
            body.clear();
            ref.invalidate(getProvider('/admin/broadcasts'));
            if (context.mounted) showToast(context, 'Đã gửi tới ${r['sent_count']} người dùng');
          } on ApiException catch (e) {
            if (context.mounted) showToast(context, e.message, error: true);
          } finally {
            if (mounted) setState(() => sending = false);
          }
        },
        icon: const Icon(Icons.send, size: 16), label: Text(sending ? 'Đang gửi…' : 'Gửi thông báo'),
      )),
    ]));
    final preview = AppCard(
      color: const Color(0xFF0B1119), borderColor: const Color(0xFF233040),
      child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
        Text('Xem trước trên điện thoại', style: TextStyle(color: const Color(0xFF8E9BAC), fontSize: 11)),
        const SizedBox(height: 8),
        Container(
          padding: const EdgeInsets.all(12),
          decoration: BoxDecoration(color: const Color(0xFF121A25), borderRadius: BorderRadius.circular(12), border: Border.all(color: const Color(0xFF233040))),
          child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
            Row(children: [const Icon(Icons.campaign_outlined, size: 16, color: Color(0xFF9CC2FF)), const SizedBox(width: 6), Text('Vinatrade · bây giờ', style: TextStyle(color: const Color(0xFF8E9BAC), fontSize: 11))]),
            const SizedBox(height: 4),
            Text(title.text.isEmpty ? 'Tiêu đề thông báo' : title.text, style: const TextStyle(color: Color(0xFFE8EEF5), fontWeight: FontWeight.w700, fontSize: 14)),
            Text(body.text.isEmpty ? 'Nội dung thông báo sẽ hiện ở đây…' : body.text, style: const TextStyle(color: Color(0xFFA3B0C0), fontSize: 13), maxLines: 6, overflow: TextOverflow.ellipsis),
          ]),
        ),
      ]),
    );
    final history = AppCard(child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
      Text('Lịch sử thông báo đã gửi', style: Theme.of(context).textTheme.titleMedium),
      hist.when(
        loading: () => const Skeleton(),
        error: (e, _) => const SizedBox.shrink(),
        data: (rows) => rows.isEmpty
            ? Padding(padding: const EdgeInsets.only(top: 8), child: Text('Chưa gửi thông báo nào.', style: TextStyle(color: c.muted, fontSize: 13)))
            : Column(children: [
                for (final b in rows)
                  ListTile(
                    dense: true, contentPadding: EdgeInsets.zero,
                    title: Text(b['title'].toString(), maxLines: 1, overflow: TextOverflow.ellipsis, style: const TextStyle(fontWeight: FontWeight.w600, fontSize: 13.5)),
                    subtitle: Text('${Fmt.dateTime(Fmt.parseDate(b['created_at']))} · ${(b['channels'] as List? ?? []).join(', ')}', style: TextStyle(fontSize: 11.5, color: c.muted)),
                    trailing: Column(mainAxisAlignment: MainAxisAlignment.center, crossAxisAlignment: CrossAxisAlignment.end, children: [Text('${b['sent_count']} người', style: const TextStyle(fontSize: 12.5, fontWeight: FontWeight.w600)), Text('${b['read_count']} đã đọc', style: TextStyle(fontSize: 11.5, color: c.up))]),
                    onTap: () => showDialog<void>(context: context, builder: (ctx) => AlertDialog(title: Text(b['title'].toString()), content: SizedBox(width: 420, child: Text(b['body']?.toString() ?? '')), actions: [TextButton(onPressed: () => Navigator.pop(ctx), child: const Text('Đóng'))])),
                  ),
              ]),
      ),
    ]));
    return Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
      const AdminHeader('Thông báo chung', subtitle: 'Gửi một thông báo tới toàn bộ người dùng đang hoạt động. Xem trước trên điện thoại trước khi gửi.'),
      if (context.isDesktop)
        Row(crossAxisAlignment: CrossAxisAlignment.start, children: [Expanded(child: compose), const SizedBox(width: 16), SizedBox(width: 340, child: Column(children: [preview, const SizedBox(height: 16), history]))])
      else ...[compose, const SizedBox(height: 16), preview, const SizedBox(height: 16), history],
    ]);
  }
}
