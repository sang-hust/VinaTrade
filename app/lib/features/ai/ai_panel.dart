import 'package:flutter/material.dart';
import 'package:flutter_animate/flutter_animate.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:go_router/go_router.dart';

import '../../core/api.dart';
import '../../core/format.dart';
import '../../core/session.dart';
import '../../core/theme.dart';
import '../../shared/widgets/common.dart';

/// Lets any screen open the AI panel (side panel on desktop, page on phone) with context.
class AiPanelScope extends InheritedWidget {
  final void Function(Map<String, dynamic> ctx) open;
  const AiPanelScope({super.key, required this.open, required super.child});
  static AiPanelScope? of(BuildContext c) => c.dependOnInheritedWidgetOfExactType<AiPanelScope>();
  @override
  bool updateShouldNotify(AiPanelScope old) => false;
}

void openAi(BuildContext context, Map<String, dynamic> ctx) {
  final s = AiPanelScope.of(context);
  if (s != null) {
    s.open(ctx);
  } else {
    context.push(Uri(path: '/ai', queryParameters: {for (final e in ctx.entries) if (e.value != null) e.key: e.value.toString()}).toString());
  }
}

class _Msg {
  final String role;
  String text;
  List<Map<String, dynamic>> cards;
  bool streaming;
  _Msg(this.role, this.text, {this.cards = const [], this.streaming = false});
}

class AiPanel extends ConsumerStatefulWidget {
  final Map<String, dynamic> context_;
  final VoidCallback? onClose;
  final String? conversationId;
  const AiPanel({super.key, required this.context_, this.onClose, this.conversationId});
  @override
  ConsumerState<AiPanel> createState() => _AiPanelState();
}

class _AiPanelState extends ConsumerState<AiPanel> {
  String? _cid;
  final List<_Msg> _msgs = [];
  List<String> _suggestions = [];
  final _input = TextEditingController();
  final _scroll = ScrollController();
  bool _busy = false;
  bool _showHistory = false;

  @override
  void initState() {
    super.initState();
    _cid = widget.conversationId;
    _cid == null ? _create() : _load(_cid!);
  }

  @override
  void didUpdateWidget(covariant AiPanel old) {
    super.didUpdateWidget(old);
    if (old.context_['symbol'] != widget.context_['symbol'] || old.context_['screen'] != widget.context_['screen']) _create();
  }

  Map<String, dynamic> get _ctx => {for (final e in widget.context_.entries) if (e.value != null && e.value.toString().isNotEmpty) e.key: e.value};

  Future<void> _create() async {
    try {
      final r = asMap(await ref.read(apiProvider).post('/ai/conversations', data: {'context': _ctx}));
      setState(() {
        _cid = r['id'];
        _msgs.clear();
        _suggestions = (r['suggestions'] as List? ?? []).map((e) => e.toString()).toList();
      });
    } on ApiException catch (e) {
      if (mounted) showToast(context, e.message, error: true);
    }
  }

  Future<void> _load(String id) async {
    final r = asMap(await ref.read(apiProvider).get('/ai/conversations/$id'));
    setState(() {
      _cid = id;
      _msgs
        ..clear()
        ..addAll(asList(r['messages']).map((m) => _Msg(m['role'], m['content'] ?? '', cards: asList(m['data_cards']))));
      _suggestions = (r['suggestions'] as List? ?? []).map((e) => e.toString()).toList();
      _showHistory = false;
    });
    _jump();
  }

  void _jump() => WidgetsBinding.instance.addPostFrameCallback((_) => _scroll.hasClients ? _scroll.animateTo(_scroll.position.maxScrollExtent + 80, duration: 200.ms, curve: Curves.easeOut) : null);

  Future<void> _send(String text) async {
    if (text.trim().isEmpty || _busy || _cid == null) return;
    _input.clear();
    final reply = _Msg('assistant', '', streaming: true);
    setState(() {
      _msgs.add(_Msg('user', text.trim()));
      _msgs.add(reply);
      _busy = true;
    });
    _jump();
    try {
      await for (final ev in ref.read(apiProvider).sse('/ai/conversations/$_cid/messages', {'content': text.trim(), 'context': _ctx})) {
        if (!mounted) return;
        switch (ev['type']) {
          case 'text':
            setState(() => reply.text += ev['delta']?.toString() ?? '');
          case 'card':
            setState(() => reply.cards = [...reply.cards, asMap(ev['data'])]);
          case 'error':
            setState(() => reply.text += '\n${ev['message']}');
          case 'done':
            setState(() => reply.streaming = false);
        }
        _jump();
      }
      ref.read(sessionProvider.notifier).patchLocal({'ai_questions_left': (ref.read(sessionProvider).aiLeft - 1).clamp(0, 999)});
    } on ApiException catch (e) {
      setState(() => reply.text = e.message);
    } finally {
      if (mounted) setState(() {
        _busy = false;
        reply.streaming = false;
      });
    }
  }

  @override
  Widget build(BuildContext context) {
    final c = context.vn;
    final left = ref.watch(sessionProvider).aiLeft;
    return Column(children: [
      Container(
        padding: const EdgeInsets.fromLTRB(16, 12, 8, 12),
        decoration: BoxDecoration(border: Border(bottom: BorderSide(color: c.line))),
        child: Row(children: [
          Icon(Icons.auto_awesome, color: c.ai, size: 20),
          const SizedBox(width: 8),
          Expanded(child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
            Text(_ctx['symbol'] != null ? 'Hỏi AI về ${_ctx['symbol']}' : 'Hỏi AI', style: const TextStyle(fontWeight: FontWeight.w700)),
            Text('Còn $left câu hỏi hôm nay', style: TextStyle(color: c.faint, fontSize: 11.5)),
          ])),
          IconButton(tooltip: 'Lịch sử', onPressed: () => setState(() => _showHistory = !_showHistory), icon: const Icon(Icons.history, size: 20)),
          IconButton(tooltip: 'Hội thoại mới', onPressed: _create, icon: const Icon(Icons.add_comment_outlined, size: 20)),
          if (widget.onClose != null) IconButton(onPressed: widget.onClose, icon: const Icon(Icons.close, size: 20)),
        ]),
      ),
      Expanded(
        child: _showHistory
            ? _History(onPick: _load)
            : ListView(
                controller: _scroll,
                padding: const EdgeInsets.all(14),
                children: [
                  if (_msgs.isEmpty)
                    Padding(
                      padding: const EdgeInsets.only(bottom: 12),
                      child: Text('Trợ lý chỉ dùng số liệu trong hệ thống Vinatrade và luôn ghi nguồn. Hãy hỏi về một mã, ngành, danh mục của bạn hoặc nhờ lập bộ lọc.', style: TextStyle(color: c.muted, fontSize: 13)),
                    ),
                  for (final m in _msgs) _bubble(m),
                  if (_suggestions.isNotEmpty && !_busy)
                    Padding(
                      padding: const EdgeInsets.only(top: 8),
                      child: Wrap(spacing: 6, runSpacing: 6, children: [for (final s in _suggestions) ActionChip(label: Text(s, style: const TextStyle(fontSize: 12)), onPressed: () => _send(s), side: BorderSide(color: c.ai.withValues(alpha: 0.5)))]),
                    ),
                ],
              ),
      ),
      Container(
        padding: const EdgeInsets.fromLTRB(12, 8, 12, 12),
        decoration: BoxDecoration(border: Border(top: BorderSide(color: c.line))),
        child: Column(children: [
          Row(children: [
            Expanded(child: TextField(controller: _input, minLines: 1, maxLines: 3, decoration: const InputDecoration(hintText: 'Hỏi về mã, ngành, danh mục…'), onSubmitted: _send, textInputAction: TextInputAction.send)),
            const SizedBox(width: 8),
            IconButton.filled(onPressed: _busy || left <= 0 ? null : () => _send(_input.text), style: IconButton.styleFrom(backgroundColor: c.ai), icon: _busy ? const SizedBox(width: 16, height: 16, child: CircularProgressIndicator(strokeWidth: 2, color: Colors.white)) : const Icon(Icons.send, size: 18)),
          ]),
          const SizedBox(height: 6),
          Text('Thông tin chỉ mang tính tham khảo, không phải lời khuyên mua bán.', style: TextStyle(color: c.faint, fontSize: 10.5)),
        ]),
      ),
    ]);
  }

  Widget _bubble(_Msg m) {
    final c = context.vn;
    final user = m.role == 'user';
    return Align(
      alignment: user ? Alignment.centerRight : Alignment.centerLeft,
      child: Container(
        margin: const EdgeInsets.only(bottom: 10),
        padding: const EdgeInsets.symmetric(horizontal: 12, vertical: 10),
        constraints: const BoxConstraints(maxWidth: 340),
        decoration: BoxDecoration(color: user ? c.accent.withValues(alpha: 0.25) : c.surface2, borderRadius: BorderRadius.circular(12), border: Border.all(color: user ? Colors.transparent : c.line)),
        child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
          for (final card in m.cards) _card(card),
          if (m.text.isEmpty && m.streaming) Row(mainAxisSize: MainAxisSize.min, children: [for (var i = 0; i < 3; i++) Container(width: 6, height: 6, margin: const EdgeInsets.only(right: 4), decoration: BoxDecoration(color: c.ai, shape: BoxShape.circle)).animate(onPlay: (ctl) => ctl.repeat()).fadeIn(delay: (i * 150).ms, duration: 400.ms).fadeOut(delay: 450.ms)])
          else _Markdownish(m.text),
        ]),
      ),
    ).animate().fadeIn(duration: 200.ms);
  }

  Widget _card(Map<String, dynamic> card) {
    final c = context.vn;
    final d = asMap(card['data']);
    if (card['kind'] == 'get_market_regime') {
      return Container(margin: const EdgeInsets.only(bottom: 8), padding: const EdgeInsets.all(10), decoration: BoxDecoration(color: c.surface, borderRadius: BorderRadius.circular(8), border: Border.all(color: c.line)), child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [Text('VN-Index ${Fmt.index(asNum(d['vnindex']))}', style: const TextStyle(fontWeight: FontWeight.w700)), Text(d['headline']?.toString() ?? '', style: TextStyle(fontSize: 12, color: c.muted))]));
    }
    return InkWell(
      onTap: d['symbol'] != null ? () => context.push('/stocks/${d['symbol']}') : null,
      child: Container(
        margin: const EdgeInsets.only(bottom: 8), padding: const EdgeInsets.all(10),
        decoration: BoxDecoration(color: c.surface, borderRadius: BorderRadius.circular(8), border: Border.all(color: c.line)),
        child: Row(children: [
          Expanded(child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
            Text('${d['symbol'] ?? ''} ${d['name'] ?? ''}', style: const TextStyle(fontWeight: FontWeight.w700, fontSize: 13)),
            Text('${Fmt.price(asNum(d['price']))} đ · ${Fmt.pct(asNum(d['change_pct']))}', style: TextStyle(fontSize: 12, color: c.changeColor(asNum(d['change_pct'])))),
            if (d['stop_loss'] != null) Text('Vùng mua ${Fmt.price(asNum(d['entry_low']))}–${Fmt.price(asNum(d['entry_high']))} · Cắt lỗ ${Fmt.price(asNum(d['stop_loss']))}', style: TextStyle(fontSize: 11, color: c.muted)),
          ])),
          if (d['score_mid'] != null) Column(children: [Text(Fmt.score(asNum(d['score_mid'])), style: TextStyle(fontWeight: FontWeight.w700, fontSize: 18, color: c.scoreColor(asNum(d['score_mid'])))), Text(d['rating_vi']?.toString() ?? '', style: TextStyle(fontSize: 10.5, color: c.muted))]),
        ]),
      ),
    );
  }
}

/// Minimal rich text: **bold**, bullet lines.
class _Markdownish extends StatelessWidget {
  final String text;
  const _Markdownish(this.text);
  @override
  Widget build(BuildContext context) {
    final c = context.vn;
    final lines = text.split('\n');
    return Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
      for (final ln in lines)
        Padding(
          padding: const EdgeInsets.only(bottom: 3),
          child: RichText(text: TextSpan(style: TextStyle(color: c.text, fontSize: 13.5, height: 1.4), children: _spans(ln.startsWith('- ') || ln.startsWith('• ') ? '• ${ln.substring(2)}' : ln))),
        ),
    ]);
  }

  List<InlineSpan> _spans(String s) {
    final out = <InlineSpan>[];
    final re = RegExp(r'\*\*(.+?)\*\*');
    var i = 0;
    for (final m in re.allMatches(s)) {
      if (m.start > i) out.add(TextSpan(text: s.substring(i, m.start)));
      out.add(TextSpan(text: m.group(1), style: const TextStyle(fontWeight: FontWeight.w700)));
      i = m.end;
    }
    if (i < s.length) out.add(TextSpan(text: s.substring(i)));
    return out;
  }
}

class _History extends ConsumerWidget {
  final void Function(String id) onPick;
  const _History({required this.onPick});
  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final api = ref.watch(apiProvider);
    return FutureBuilder(
      future: api.get('/ai/conversations'),
      builder: (_, snap) {
        if (!snap.hasData) return const Center(child: CircularProgressIndicator());
        final rows = asList(snap.data);
        if (rows.isEmpty) return const EmptyState(icon: Icons.chat_bubble_outline, message: 'Chưa có hội thoại nào');
        return ListView(children: [for (final r in rows) ListTile(title: Text(r['title']?.toString() ?? 'Hội thoại', maxLines: 1, overflow: TextOverflow.ellipsis), subtitle: Text(Fmt.relative(Fmt.parseDate(r['updated_at']))), onTap: () => onPick(r['id']))]);
      },
    );
  }
}
