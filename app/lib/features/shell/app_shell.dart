import 'package:flutter/material.dart';
import '../../shared/widgets/brand.dart';
import 'package:flutter/services.dart';
import 'package:flutter_animate/flutter_animate.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:go_router/go_router.dart';

import '../../core/format.dart';
import '../../core/providers.dart';
import '../../core/responsive.dart';
import '../../core/session.dart';
import '../../core/theme.dart';
import '../../core/ws.dart';
import '../../shared/widgets/common.dart';
import '../ai/ai_panel.dart';

const _desktopNav = [('/', 'Thị trường', BrandIcons.market), ('/analysis', 'Phân tích', BrandIcons.analysis), ('/watch', 'Theo dõi', BrandIcons.watchlist), ('/portfolio', 'Danh mục', BrandIcons.portfolio), ('/screener', 'Bộ lọc', BrandIcons.screener), ('/alerts', 'Cảnh báo', BrandIcons.alerts)];
const _phoneNav = [('/', 'Thị trường', BrandIcons.market), ('/watch', 'Theo dõi', BrandIcons.watchlist), ('/alerts', 'Cảnh báo', BrandIcons.alerts), ('/portfolio', 'Danh mục', BrandIcons.portfolio), ('/account', 'Tài khoản', BrandIcons.account)];

bool _matches(String location, String path) {
  final p = Uri.parse(location).path;
  if (path == '/') return p == '/';
  if (path == '/analysis') return p.startsWith('/analysis') || p.startsWith('/stocks');
  if (path == '/portfolio') return p.startsWith('/portfolio') || p.startsWith('/plans');
  return p.startsWith(path);
}

class AppShell extends ConsumerStatefulWidget {
  final String location;
  final Widget child;
  const AppShell({super.key, required this.location, required this.child});
  @override
  ConsumerState<AppShell> createState() => _AppShellState();
}

class _AppShellState extends ConsumerState<AppShell> {
  bool _aiOpen = false;
  Map<String, dynamic> _aiContext = {};

  void openAi(Map<String, dynamic> ctx) {
    if (context.isDesktop) {
      setState(() {
        _aiContext = ctx;
        _aiOpen = true;
      });
    } else {
      context.push(Uri(path: '/ai', queryParameters: {for (final e in ctx.entries) if (e.value != null) e.key: e.value.toString()}).toString());
    }
  }

  @override
  Widget build(BuildContext context) {
    final session = ref.watch(sessionProvider);
    final rt = ref.watch(realtimeProvider);
    final c = context.vn;
    if (session.loading) {
      return Scaffold(body: Center(child: Column(mainAxisSize: MainAxisSize.min, children: [
        const BrandMark(size: 64).animate(onPlay: (ctl) => ctl.repeat(reverse: true)).scale(begin: const Offset(0.95, 0.95), end: const Offset(1.05, 1.05), duration: 700.ms),
        const SizedBox(height: 14),
        Text('Vinatrade', style: TextStyle(fontWeight: FontWeight.w700, fontSize: 18, color: c.text)),
      ])));
    }
    final defensive = session.defensive || rt.guardMode == 'DEFENSIVE';
    final cap = asNum(session.guard['equity_cap_pct']);
    final banner = defensive
        ? DefensiveBanner(releaseAt: _fmtDate(session.guard['release_at']), reason: session.guard['reason']?.toString(), onWhy: () => context.push('/portfolio?tab=risk'))
        : (cap != null ? InfoBanner('Danh mục giảm ${Fmt.num_(asNum(session.guard['drawdown_pct']))}% từ đỉnh: giữ tối đa ${Fmt.num_(cap, decimals: 0)}% cổ phiếu.', color: c.ref, icon: Icons.trending_down, trailing: TextButton(onPressed: () => context.push('/portfolio?tab=risk'), child: Text('Chi tiết', style: TextStyle(color: c.ref, fontSize: 12.5)))) : null);
    final body = Column(children: [
      if (banner != null) banner,
      if (!rt.connected && session.authenticated && !session.loading) InfoBanner('Mất kết nối thời gian thực. Đang hiển thị dữ liệu gần nhất.', color: c.ref, icon: Icons.wifi_off),
      Expanded(child: widget.child),
    ]);
    return AiPanelScope(
      open: openAi,
      child: context.isPhone ? _phone(context, body, session, rt) : _desktop(context, body, session, rt),
    );
  }

  String? _fmtDate(dynamic v) {
    final d = Fmt.parseDate(v);
    return d == null ? null : Fmt.date(d);
  }

  Widget _phone(BuildContext context, Widget body, SessionState s, RealtimeState rt) {
    final idx = _phoneNav.indexWhere((n) => _matches(widget.location, n.$1));
    final unread = rt.unread > 0 ? rt.unread : s.unread;
    return Scaffold(
      body: SafeArea(bottom: false, child: body),
      bottomNavigationBar: NavigationBar(
        selectedIndex: idx < 0 ? 0 : idx,
        onDestinationSelected: (i) => context.go(_phoneNav[i].$1),
        destinations: [
          for (final n in _phoneNav)
            NavigationDestination(
              icon: n.$1 == '/alerts' && unread > 0 ? Badge(label: Text('$unread'), child: BrandIcon(n.$3, color: context.vn.muted)) : BrandIcon(n.$3, color: context.vn.muted),
              selectedIcon: n.$1 == '/alerts' && unread > 0 ? Badge(label: Text('$unread'), child: BrandIcon(n.$3, color: context.vn.accent)) : BrandIcon(n.$3, color: context.vn.accent),
              label: n.$2,
            ),
        ],
      ),
    );
  }

  Widget _desktop(BuildContext context, Widget body, SessionState s, RealtimeState rt) {
    final c = context.vn;
    final unread = rt.unread > 0 ? rt.unread : s.unread;
    final w = MediaQuery.sizeOf(context).width;
    // Three widths: roomy (labels on every tab), compact (icons + active label), tight (also icon-only search/AI).
    final compact = w < 1400;
    final tight = w < 1100;
    final aiWidth = (w * 0.42).clamp(320.0, 400.0);
    return CallbackShortcuts(
      bindings: {
        const SingleActivator(LogicalKeyboardKey.keyK, control: true): () => showSymbolSearch(context),
        const SingleActivator(LogicalKeyboardKey.keyK, meta: true): () => showSymbolSearch(context),
      },
      child: Focus(
        autofocus: true,
        child: Scaffold(
          body: Column(children: [
            // Top bar: background runs under the status bar; content stays inside the safe area (iPad, notches, landscape).
            Container(
              decoration: BoxDecoration(color: c.surface, border: Border(bottom: BorderSide(color: c.line))),
              child: SafeArea(
                bottom: false,
                child: SizedBox(
                  height: 60,
                  child: Padding(
                    padding: EdgeInsets.symmetric(horizontal: compact ? 12 : 24),
                    child: Row(children: [
                      InkWell(
                        onTap: () => context.go('/'),
                        borderRadius: BorderRadius.circular(8),
                        child: Row(mainAxisSize: MainAxisSize.min, children: [
                          if (compact) const BrandMark(size: 30) else const BrandLockup(height: 30),
                        ]),
                      ),
                      SizedBox(width: compact ? 10 : 20),
                      // Navigation takes the remaining width and scrolls if it does not fit, so the actions on the right are never pushed off-screen.
                      Expanded(
                        child: ShaderMask(
                          shaderCallback: (r) => LinearGradient(colors: [Colors.white, Colors.white, Colors.white.withValues(alpha: 0)], stops: const [0, 0.94, 1]).createShader(r),
                          blendMode: BlendMode.dstIn,
                          child: SingleChildScrollView(
                            scrollDirection: Axis.horizontal,
                            child: Row(children: [
                              for (final n in _desktopNav) _NavItem(label: n.$2, icon: n.$3, active: _matches(widget.location, n.$1), compact: compact, onTap: () => context.go(n.$1)),
                              const SizedBox(width: 16),
                            ]),
                          ),
                        ),
                      ),
                      const SizedBox(width: 8),
                      if (tight)
                        IconButton(tooltip: 'Tìm mã (Ctrl K)', onPressed: () => showSymbolSearch(context), icon: const Icon(Icons.search))
                      else
                        SizedBox(
                          width: compact ? 160 : 240,
                          child: InkWell(
                            onTap: () => showSymbolSearch(context),
                            borderRadius: BorderRadius.circular(10),
                            child: Container(
                              height: 38, padding: const EdgeInsets.symmetric(horizontal: 10),
                              decoration: BoxDecoration(color: c.surface2, borderRadius: BorderRadius.circular(10), border: Border.all(color: c.line)),
                              child: Row(children: [Icon(Icons.search, size: 18, color: c.faint), const SizedBox(width: 8), Expanded(child: Text('Tìm mã…', maxLines: 1, overflow: TextOverflow.ellipsis, style: TextStyle(color: c.faint, fontSize: 13))), if (!compact) Pill('Ctrl K', color: c.faint, bg: c.surface, fontSize: 10)]),
                            ),
                          ),
                        ),
                      const SizedBox(width: 6),
                      AskAiButton(compact: compact, onPressed: () => openAi({'screen': 'market'})),
                      IconButton(tooltip: 'Cảnh báo', onPressed: () => context.go('/alerts'), icon: unread > 0 ? Badge(label: Text('$unread'), child: BrandIcon(BrandIcons.alerts, color: c.text)) : BrandIcon(BrandIcons.alerts, color: c.text)),
                      if (s.isAdmin)
                        (compact
                            ? IconButton(tooltip: 'Quản trị', onPressed: () => context.go('/admin/overview'), icon: BrandIcon(BrandIcons.admin, color: c.text))
                            : TextButton.icon(onPressed: () => context.go('/admin/overview'), icon: BrandIcon(BrandIcons.admin, size: 18, color: c.link), label: const Text('Quản trị'))),
                      const SizedBox(width: 4),
                      Tooltip(
                        message: 'Tài khoản',
                        child: InkWell(
                          onTap: () => context.go('/account'),
                          borderRadius: BorderRadius.circular(20),
                          child: CircleAvatar(radius: 17, backgroundColor: c.accent.withValues(alpha: 0.25), child: Text((s.user['full_name']?.toString() ?? '?').characters.first.toUpperCase(), style: TextStyle(color: c.text, fontWeight: FontWeight.w700))),
                        ),
                      ),
                    ]),
                  ),
                ),
              ),
            ),
            const IndexStrip(),
            Expanded(
              child: SafeArea(
                top: false,
                bottom: false,
                child: Row(children: [
                  Expanded(child: body),
                  if (_aiOpen)
                    Container(
                      width: aiWidth,
                      decoration: BoxDecoration(color: c.surface, border: Border(left: BorderSide(color: c.line))),
                      child: AiPanel(context_: _aiContext, onClose: () => setState(() => _aiOpen = false)),
                    ).animate().slideX(begin: 0.2, duration: 250.ms, curve: Curves.easeOutCubic).fadeIn(),
                ]),
              ),
            ),
          ]),
        ),
      ),
    );
  }
}

class _NavItem extends StatelessWidget {
  final String label;
  final BrandIcons icon;
  final bool active, compact;
  final VoidCallback onTap;
  const _NavItem({required this.label, required this.icon, required this.active, required this.compact, required this.onTap});
  @override
  Widget build(BuildContext context) {
    final c = context.vn;
    return Padding(
      padding: const EdgeInsets.only(right: 4),
      child: InkWell(
        onTap: onTap,
        borderRadius: BorderRadius.circular(8),
        child: AnimatedContainer(
          duration: 200.ms,
          padding: EdgeInsets.symmetric(horizontal: compact ? 8 : 12, vertical: 8),
          decoration: BoxDecoration(color: active ? c.surface2 : Colors.transparent, borderRadius: BorderRadius.circular(8), border: Border(bottom: BorderSide(color: active ? c.accent : Colors.transparent, width: 2))),
          child: Row(children: [BrandIcon(icon, size: 19, color: active ? c.text : c.muted), if (!compact || active) ...[const SizedBox(width: 6), Text(label, style: TextStyle(color: active ? c.text : c.muted, fontWeight: active ? FontWeight.w700 : FontWeight.w500, fontSize: 13.5))]]),
        ),
      ),
    );
  }
}

/// Index strip under the desktop top bar.
class IndexStrip extends ConsumerWidget {
  const IndexStrip({super.key});
  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final c = context.vn;
    final ov = ref.watch(getMapProvider('/market/overview'));
    final w = MediaQuery.sizeOf(context).width;
    final pad = MediaQuery.paddingOf(context);
    return Container(
      height: 36,
      padding: EdgeInsets.only(left: (w < 1400 ? 12 : 24) + pad.left, right: (w < 1400 ? 12 : 24) + pad.right),
      decoration: BoxDecoration(color: c.surface2, border: Border(bottom: BorderSide(color: c.line))),
      child: ov.when(
        data: (d) => Row(children: [
          Expanded(
            child: SingleChildScrollView(
              scrollDirection: Axis.horizontal,
              child: Row(children: [
                for (final i in asList(d['indexes']))
                  Padding(
                    padding: const EdgeInsets.only(right: 22),
                    child: Row(children: [
                      Text(i['label'].toString(), style: TextStyle(color: c.faint, fontSize: 12)),
                      const SizedBox(width: 6),
                      Text(Fmt.index(asNum(i['value'])), style: TextStyle(fontWeight: FontWeight.w700, fontSize: 12.5, color: c.changeColor(asNum(i['change_pct'])))),
                      const SizedBox(width: 4),
                      Text(Fmt.pct(asNum(i['change_pct'])), style: TextStyle(fontSize: 11.5, color: c.changeColor(asNum(i['change_pct'])))),
                    ]),
                  ),
              ]),
            ),
          ),
          if (w >= 900) ...[
            const SizedBox(width: 12),
            Text(d['session']?.toString() ?? '', maxLines: 1, overflow: TextOverflow.ellipsis, style: TextStyle(color: c.faint, fontSize: 12)),
          ],
        ]),
        loading: () => const SizedBox.shrink(),
        error: (e, _) => Row(children: [Icon(Icons.cloud_off, size: 14, color: c.faint), const SizedBox(width: 6), Text('Không tải được chỉ số', style: TextStyle(color: c.faint, fontSize: 12))]),
      ),
    );
  }
}

/// Command palette: symbol search (Ctrl/Cmd+K).
Future<void> showSymbolSearch(BuildContext context, {void Function(Map<String, dynamic>)? onPick}) async {
  final picked = await showDialog<Map<String, dynamic>>(context: context, barrierColor: Colors.black54, builder: (_) => const _SearchDialog());
  if (picked == null) return;
  if (onPick != null) {
    onPick(picked);
  } else if (context.mounted) {
    context.push('/stocks/${picked['symbol']}');
  }
}

class _SearchDialog extends ConsumerStatefulWidget {
  const _SearchDialog();
  @override
  ConsumerState<_SearchDialog> createState() => _SearchDialogState();
}

class _SearchDialogState extends ConsumerState<_SearchDialog> {
  String q = '';
  int sel = 0;
  @override
  Widget build(BuildContext context) {
    final c = context.vn;
    final res = ref.watch(stockSearchProvider(q));
    final rows = res.value ?? [];
    return Dialog(
      alignment: Alignment.topCenter,
      insetPadding: const EdgeInsets.only(top: 80, left: 16, right: 16),
      child: ConstrainedBox(
        constraints: const BoxConstraints(maxWidth: 560),
        child: Column(mainAxisSize: MainAxisSize.min, children: [
          Padding(
            padding: const EdgeInsets.all(12),
            child: CallbackShortcuts(
              bindings: {
                const SingleActivator(LogicalKeyboardKey.arrowDown): () => setState(() => sel = (sel + 1).clamp(0, rows.isEmpty ? 0 : rows.length - 1)),
                const SingleActivator(LogicalKeyboardKey.arrowUp): () => setState(() => sel = (sel - 1).clamp(0, rows.isEmpty ? 0 : rows.length - 1)),
              },
              child: TextField(
                autofocus: true,
                decoration: const InputDecoration(prefixIcon: Icon(Icons.search), hintText: 'Nhập mã hoặc tên công ty (có dấu hoặc không dấu)'),
                textCapitalization: TextCapitalization.characters,
                onChanged: (v) => setState(() {
                  q = v;
                  sel = 0;
                }),
                onSubmitted: (_) => rows.isNotEmpty ? Navigator.pop(context, rows[sel.clamp(0, rows.length - 1)]) : null,
              ),
            ),
          ),
          if (res.isLoading) const LinearProgressIndicator(minHeight: 2),
          Flexible(
            child: ListView(shrinkWrap: true, children: [
              for (final (i, r) in rows.indexed)
                ListTile(
                  selected: i == sel,
                  selectedTileColor: c.surface2,
                  leading: Text(r['symbol'].toString(), style: TextStyle(fontWeight: FontWeight.w700, color: c.text)),
                  title: Text(r['name']?.toString() ?? '', maxLines: 1, overflow: TextOverflow.ellipsis),
                  subtitle: Text('${r['exchange'] ?? ''}${r['industry'] != null ? ' · ${r['industry']}' : ''}', style: TextStyle(fontSize: 11.5, color: c.faint)),
                  trailing: r['price'] != null ? Text(Fmt.price(asNum(r['price'])), style: TextStyle(color: c.changeColor(asNum(r['change_pct'])), fontWeight: FontWeight.w600)) : null,
                  onTap: () => Navigator.pop(context, r),
                ),
              if (q.isNotEmpty && rows.isEmpty && !res.isLoading) Padding(padding: const EdgeInsets.all(16), child: Text('Không tìm thấy mã nào', style: TextStyle(color: c.muted))),
            ]),
          ),
        ]),
      ),
    );
  }
}
