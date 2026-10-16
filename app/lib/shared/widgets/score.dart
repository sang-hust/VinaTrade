import 'package:flutter/material.dart';
import 'package:flutter_animate/flutter_animate.dart';

import '../../core/format.dart';
import '../../core/responsive.dart';
import '../../core/theme.dart';
import 'common.dart';

const ratingVi = {'STRONG_BUY': 'Mua mạnh', 'BUY': 'Tích lũy', 'HOLD': 'Nắm giữ', 'REDUCE': 'Giảm tỷ trọng', 'SELL': 'Bán'};
const horizonVi = {'SHORT': 'Ngắn hạn', 'MID': 'Trung hạn', 'LONG': 'Dài hạn'};
const regimeVi = {'UPTREND': 'tăng', 'PRESSURE': 'chịu áp lực', 'CORRECTION': 'điều chỉnh', 'DOWNTREND': 'giảm'};

/// 5-zone score gauge (Bán → Mua mạnh) with white marker. Animated on first paint.
class ScoreGauge extends StatelessWidget {
  final num? score;
  final bool compact;
  final bool showScore;
  const ScoreGauge({super.key, required this.score, this.compact = false, this.showScore = true});

  @override
  Widget build(BuildContext context) {
    final c = context.vn;
    final h = compact ? 6.0 : 10.0;
    final zones = [(35.0, c.sell), (15.0, c.reduce), (15.0, c.hold), (15.0, c.buy), (20.0, c.strongBuy)];
    final bar = LayoutBuilder(builder: (ctx, cons) {
      final w = cons.maxWidth;
      return TweenAnimationBuilder<double>(
        tween: Tween(begin: 0, end: (score ?? 0).toDouble().clamp(0, 100)),
        duration: context.reduceMotion ? Duration.zero : 800.ms,
        curve: Curves.easeOutCubic,
        builder: (_, v, __) => SizedBox(
          height: h + (compact ? 4 : 8),
          child: Stack(clipBehavior: Clip.none, children: [
            Positioned(top: (compact ? 2 : 4), left: 0, right: 0, child: ClipRRect(borderRadius: BorderRadius.circular(h / 2), child: Row(children: [for (final z in zones) Expanded(flex: (z.$1 * 10).round(), child: Container(height: h, color: z.$2.withValues(alpha: 0.55)))]))),
            if (score != null)
              Positioned(left: (w * v / 100 - 2).clamp(0, w - 4), top: 0, child: Container(width: 4, height: h + (compact ? 4 : 8), decoration: BoxDecoration(color: Colors.white, borderRadius: BorderRadius.circular(2), boxShadow: const [BoxShadow(color: Colors.black45, blurRadius: 2)]))),
          ]),
        ),
      );
    });
    if (!showScore) return bar;
    return Row(children: [
      Expanded(child: bar),
      const SizedBox(width: 10),
      SizedBox(width: compact ? 28 : 40, child: Text(Fmt.score(score), textAlign: TextAlign.right, style: TextStyle(fontWeight: FontWeight.w700, fontSize: compact ? 13 : 16, color: c.scoreColor(score), fontFeatures: const [FontFeature.tabularFigures()]))),
    ]);
  }
}

class RatingChip extends StatelessWidget {
  final String? rating;
  final num? score;
  final double fontSize;
  const RatingChip(this.rating, {super.key, this.score, this.fontSize = 12});
  @override
  Widget build(BuildContext context) {
    final c = context.vn;
    final label = ratingVi[rating] ?? '—';
    return Pill(score != null ? '$label · ${Fmt.score(score)}' : label, color: c.ratingColor(rating), bg: c.ratingBg(rating), fontSize: fontSize);
  }
}

/// Short-mid-long trend as ▲▬▼ with colors.
class TrendChips extends StatelessWidget {
  final String? trend3;
  final double size;
  const TrendChips(this.trend3, {super.key, this.size = 13});
  @override
  Widget build(BuildContext context) {
    final c = context.vn;
    final t = (trend3 ?? '▬▬▬').padRight(3, '▬');
    return Row(mainAxisSize: MainAxisSize.min, children: [
      for (final ch in t.characters)
        Padding(padding: const EdgeInsets.only(right: 1), child: Text(ch, style: TextStyle(fontSize: size, color: ch == '▲' ? c.upText : (ch == '▼' ? c.downText : c.faint)))),
    ]);
  }
}

/// Three labelled trend tiles (Ngắn / Trung / Dài).
class TrendTiles extends StatelessWidget {
  final Map<String, dynamic> trend; // {SHORT: UP, MID: FLAT, LONG: DOWN}
  const TrendTiles(this.trend, {super.key});
  @override
  Widget build(BuildContext context) {
    final c = context.vn;
    Widget tile(String k, String label) {
      final v = trend[k]?.toString() ?? 'FLAT';
      final col = v == 'UP' ? c.upText : (v == 'DOWN' ? c.downText : c.faint);
      final sym = v == 'UP' ? '▲ Tăng' : (v == 'DOWN' ? '▼ Giảm' : '▬ Ngang');
      return Expanded(child: Container(padding: const EdgeInsets.symmetric(vertical: 8), decoration: BoxDecoration(color: c.surface2, borderRadius: BorderRadius.circular(8)), child: Column(children: [Text(label, style: TextStyle(color: c.faint, fontSize: 11)), const SizedBox(height: 2), Text(sym, style: TextStyle(color: col, fontWeight: FontWeight.w700, fontSize: 12.5))])));
    }
    return Row(children: [tile('SHORT', 'Ngắn'), const SizedBox(width: 6), tile('MID', 'Trung'), const SizedBox(width: 6), tile('LONG', 'Dài')]);
  }
}

/// Position of price between stop (red) and target (green).
class PriceBar extends StatelessWidget {
  final num? stop;
  final num? target;
  final num? price;
  final num? entry;
  const PriceBar({super.key, required this.stop, required this.target, required this.price, this.entry});
  @override
  Widget build(BuildContext context) {
    final c = context.vn;
    final s = stop, t = target, p = price, e = entry;
    if (s == null || t == null || p == null || t <= s) return Text(Fmt.dash, style: TextStyle(color: c.faint));
    final pos = ((p - s) / (t - s)).clamp(0.0, 1.0);
    final entryPos = e == null ? null : ((e - s) / (t - s)).clamp(0.0, 1.0);
    return LayoutBuilder(builder: (_, cons) {
      final w = cons.maxWidth;
      return SizedBox(
        height: 14,
        child: Stack(children: [
          Positioned(top: 5, left: 0, right: 0, child: Container(height: 4, decoration: BoxDecoration(borderRadius: BorderRadius.circular(2), gradient: LinearGradient(colors: [c.down, c.ref, c.up])))),
          if (entryPos != null) Positioned(left: w * entryPos - 1, top: 3, child: Container(width: 2, height: 8, color: c.muted)),
          Positioned(left: (w * pos - 4).clamp(0, w - 8), top: 2, child: Container(width: 8, height: 10, decoration: BoxDecoration(color: Colors.white, borderRadius: BorderRadius.circular(2), border: Border.all(color: c.bg)))),
        ]),
      );
    });
  }
}

/// Flashes green/red background when the price changes (600 ms, disabled with reduce-motion).
class PriceFlash extends StatefulWidget {
  final num? price;
  final Widget child;
  const PriceFlash({super.key, required this.price, required this.child});
  @override
  State<PriceFlash> createState() => _PriceFlashState();
}

class _PriceFlashState extends State<PriceFlash> {
  Color? _flash;
  num? _last;
  @override
  void didUpdateWidget(covariant PriceFlash old) {
    super.didUpdateWidget(old);
    if (widget.price != null && _last != null && widget.price != _last && !context.reduceMotion) {
      setState(() => _flash = (widget.price! > _last! ? context.vn.up : context.vn.down).withValues(alpha: 0.15));
      Future.delayed(600.ms, () => mounted ? setState(() => _flash = null) : null);
    }
    _last = widget.price;
  }

  @override
  void initState() {
    super.initState();
    _last = widget.price;
  }

  @override
  Widget build(BuildContext context) => AnimatedContainer(duration: 300.ms, decoration: BoxDecoration(color: _flash, borderRadius: BorderRadius.circular(4)), padding: const EdgeInsets.symmetric(horizontal: 2), child: widget.child);
}

/// Hide secondary blocks below the user's detail level. Risk blocks must never be wrapped (BR-20).
class DetailGate extends StatelessWidget {
  final String min; // SIMPLE | STANDARD | FULL
  final String current;
  final Widget child;
  const DetailGate({super.key, required this.min, required this.current, required this.child});
  @override
  Widget build(BuildContext context) {
    const rank = {'SIMPLE': 0, 'STANDARD': 1, 'FULL': 2};
    return (rank[current] ?? 1) >= (rank[min] ?? 1) ? child : const SizedBox.shrink();
  }
}

class StatusDot extends StatelessWidget {
  final Color color;
  final double size;
  const StatusDot(this.color, {super.key, this.size = 8});
  @override
  Widget build(BuildContext context) => Container(width: size, height: size, decoration: BoxDecoration(color: color, shape: BoxShape.circle));
}
