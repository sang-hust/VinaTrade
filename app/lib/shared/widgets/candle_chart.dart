import 'dart:math' as math;
import 'dart:ui' show PointMode;

import 'package:flutter/gestures.dart';
import 'package:flutter/material.dart';

import '../../core/format.dart';
import '../../core/responsive.dart';
import '../../core/theme.dart';

class Candle {
  final DateTime t;
  final double o, h, l, c;
  final double v;
  final double? ma20, ma50, ma200, rsi, macd, macdS, macdH, volMa20;
  const Candle({required this.t, required this.o, required this.h, required this.l, required this.c, required this.v, this.ma20, this.ma50, this.ma200, this.rsi, this.macd, this.macdS, this.macdH, this.volMa20});

  factory Candle.fromJson(Map<String, dynamic> j) => Candle(
        t: DateTime.parse(j['t']), o: asDouble(j['o']) ?? 0, h: asDouble(j['h']) ?? 0, l: asDouble(j['l']) ?? 0, c: asDouble(j['c']) ?? 0, v: asDouble(j['v']) ?? 0,
        ma20: asDouble(j['ma20']), ma50: asDouble(j['ma50']), ma200: asDouble(j['ma200']), rsi: asDouble(j['rsi']), macd: asDouble(j['macd']), macdS: asDouble(j['macd_s']), macdH: asDouble(j['macd_h']), volMa20: asDouble(j['vol_ma20']));
}

class BaseBox {
  final DateTime start;
  final DateTime? end;
  final double high, low;
  final int length;
  final String status;
  const BaseBox({required this.start, this.end, required this.high, required this.low, required this.length, required this.status});
  factory BaseBox.fromJson(Map<String, dynamic> j) => BaseBox(start: DateTime.parse(j['start_date']), end: j['end_date'] == null ? null : DateTime.parse(j['end_date']), high: asDouble(j['base_high']) ?? 0, low: asDouble(j['base_low']) ?? 0, length: asInt(j['length_days']) ?? 0, status: j['status']?.toString() ?? '');
}

/// Candlestick chart with MA lines, volume, trade-plan levels, base rectangles, zoom/pan and crosshair.
class CandleChart extends StatefulWidget {
  final List<Candle> candles;
  final List<BaseBox> bases;
  final double? entryLow, entryHigh, stopLoss, takeProfit1, takeProfit2;
  final bool showMa;
  final bool showIndicators; // RSI / MACD panes
  final double height;
  const CandleChart({super.key, required this.candles, this.bases = const [], this.entryLow, this.entryHigh, this.stopLoss, this.takeProfit1, this.takeProfit2, this.showMa = true, this.showIndicators = false, this.height = 380});

  @override
  State<CandleChart> createState() => _CandleChartState();
}

class _CandleChartState extends State<CandleChart> with SingleTickerProviderStateMixin {
  int _visible = 90;
  int _end = 0; // index of last visible candle (exclusive offset from end)
  Offset? _cross;
  double _baseVisible = 90;
  late final AnimationController _reveal = AnimationController(vsync: this, duration: const Duration(milliseconds: 700))..forward();

  @override
  void dispose() {
    _reveal.dispose();
    super.dispose();
  }

  @override
  void didUpdateWidget(covariant CandleChart old) {
    super.didUpdateWidget(old);
    if (old.candles.length != widget.candles.length) {
      _end = 0;
      _reveal.forward(from: 0);
    }
  }

  @override
  Widget build(BuildContext context) {
    final n = widget.candles.length;
    if (n == 0) return SizedBox(height: widget.height, child: Center(child: Text('Chưa có dữ liệu giá', style: TextStyle(color: context.vn.muted))));
    final vis = _visible.clamp(20, n);
    final endIdx = (n - _end).clamp(vis, n);
    final slice = widget.candles.sublist(endIdx - vis, endIdx);
    return Listener(
      onPointerSignal: (e) {
        if (e is PointerScrollEvent) {
          setState(() => _visible = (_visible + (e.scrollDelta.dy > 0 ? 8 : -8)).clamp(20, n));
        }
      },
      child: GestureDetector(
        onScaleStart: (d) {
          _baseVisible = _visible.toDouble();
          _cross = null;
        },
        onScaleUpdate: (d) {
          setState(() {
            if (d.pointerCount >= 2 || d.scale != 1.0) {
              _visible = (_baseVisible / d.scale).round().clamp(20, n);
            } else {
              final perCandle = (context.size?.width ?? 300) / vis;
              final shift = (d.focalPointDelta.dx / perCandle).round();
              if (shift != 0) _end = (_end + shift).clamp(0, n - vis);
            }
          });
        },
        onLongPressStart: (d) => setState(() => _cross = d.localPosition),
        onLongPressMoveUpdate: (d) => setState(() => _cross = d.localPosition),
        onLongPressEnd: (_) => setState(() => _cross = null),
        onTapUp: (d) => setState(() => _cross = _cross == null ? d.localPosition : null),
        child: MouseRegion(
          onHover: (e) => setState(() => _cross = e.localPosition),
          onExit: (_) => setState(() => _cross = null),
          child: AnimatedBuilder(
            animation: _reveal,
            builder: (_, __) => CustomPaint(
              size: Size(double.infinity, widget.height),
              painter: _CandlePainter(
                slice, widget.bases, context.vn, Theme.of(context).textTheme.bodySmall!,
                entryLow: widget.entryLow, entryHigh: widget.entryHigh, stop: widget.stopLoss, tp1: widget.takeProfit1, tp2: widget.takeProfit2,
                showMa: widget.showMa, showInd: widget.showIndicators, cross: _cross, reveal: context.reduceMotion ? 1 : Curves.easeOutCubic.transform(_reveal.value),
              ),
            ),
          ),
        ),
      ),
    );
  }
}

class _CandlePainter extends CustomPainter {
  final List<Candle> d;
  final List<BaseBox> bases;
  final VNColors c;
  final TextStyle ts;
  final double? entryLow, entryHigh, stop, tp1, tp2;
  final bool showMa, showInd;
  final Offset? cross;
  final double reveal;
  _CandlePainter(this.d, this.bases, this.c, this.ts, {this.entryLow, this.entryHigh, this.stop, this.tp1, this.tp2, required this.showMa, required this.showInd, this.cross, required this.reveal});

  static const _axisW = 64.0;

  @override
  void paint(Canvas canvas, Size size) {
    final n = d.length;
    if (n == 0) return;
    final plotW = size.width - _axisW;
    final indH = showInd ? 110.0 : 0.0;
    final volH = 60.0;
    final priceH = size.height - volH - indH - 22;
    final cw = plotW / n;
    double lo = d.map((e) => e.l).reduce(math.min), hi = d.map((e) => e.h).reduce(math.max);
    for (final v in [stop, tp1, tp2, entryLow, entryHigh]) {
      if (v != null && v > 0) {
        lo = math.min(lo, v);
        hi = math.max(hi, v);
      }
    }
    for (final b in bases) {
      if (b.status != 'FAILED' && _visibleBase(b)) {
        lo = math.min(lo, b.low);
        hi = math.max(hi, b.high);
      }
    }
    final pad = (hi - lo) * 0.06;
    lo -= pad;
    hi += pad;
    double y(double p) => (hi - p) / (hi - lo) * priceH;
    double x(int i) => i * cw + cw / 2;
    final vmax = d.map((e) => e.v).fold<double>(0, math.max);
    final grid = Paint()..color = c.lineSoft..strokeWidth = 1;
    // grid + price axis
    for (var k = 0; k <= 4; k++) {
      final yy = priceH * k / 4;
      canvas.drawLine(Offset(0, yy), Offset(plotW, yy), grid);
      _label(canvas, Fmt.price(hi - (hi - lo) * k / 4), Offset(plotW + 6, yy - 7), c.faint);
    }
    // bases
    for (final b in bases) {
      if (b.status == 'FAILED') continue;
      final i0 = d.indexWhere((e) => !e.t.isBefore(b.start));
      if (i0 < 0) continue;
      final i1 = b.end == null ? n - 1 : d.lastIndexWhere((e) => !e.t.isAfter(b.end!));
      if (i1 < i0) continue;
      final rect = Rect.fromLTRB(i0 * cw, y(b.high), (i1 + 1) * cw, y(b.low));
      canvas.drawRect(rect, Paint()..color = (b.status == 'BROKEN_OUT' ? c.up : c.accent).withValues(alpha: 0.08));
      canvas.drawRect(rect, Paint()..color = (b.status == 'BROKEN_OUT' ? c.up : c.accent).withValues(alpha: 0.5)..style = PaintingStyle.stroke..strokeWidth = 1);
      _label(canvas, 'nền ${b.length} phiên', Offset(rect.left + 4, rect.top + 2), c.muted, size: 10);
    }
    // entry zone
    if (entryLow != null && entryHigh != null && entryHigh! > entryLow!) {
      canvas.drawRect(Rect.fromLTRB(0, y(entryHigh!), plotW, y(entryLow!)), Paint()..color = c.up.withValues(alpha: 0.10));
    }
    // candles (revealed progressively)
    final shown = (n * reveal).ceil().clamp(1, n);
    final bodyW = math.max(1.0, cw * 0.62);
    for (var i = 0; i < shown; i++) {
      final e = d[i];
      final up = e.c >= e.o;
      final col = up ? c.up : c.down;
      final p = Paint()..color = col..strokeWidth = 1;
      canvas.drawLine(Offset(x(i), y(e.h)), Offset(x(i), y(e.l)), p);
      final top = y(math.max(e.o, e.c)), bot = y(math.min(e.o, e.c));
      canvas.drawRect(Rect.fromLTWH(x(i) - bodyW / 2, top, bodyW, math.max(1, bot - top)), Paint()..color = col);
      // volume
      final vh = vmax > 0 ? e.v / vmax * (volH - 6) : 0.0;
      canvas.drawRect(Rect.fromLTWH(x(i) - bodyW / 2, priceH + 4 + (volH - 6 - vh), bodyW, vh), Paint()..color = col.withValues(alpha: 0.45));
    }
    // MA lines
    if (showMa) {
      _line(canvas, d.map((e) => e.ma20).toList(), x, y, const Color(0xFF7FB0FF), shown);
      _line(canvas, d.map((e) => e.ma50).toList(), x, y, const Color(0xFFF08A3D), shown);
      _line(canvas, d.map((e) => e.ma200).toList(), x, y, c.ceil, shown);
    }
    // vol MA
    if (vmax > 0) {
      final pts = <Offset>[];
      for (var i = 0; i < shown; i++) {
        final m = d[i].volMa20;
        if (m != null) pts.add(Offset(x(i), priceH + 4 + (volH - 6 - m / vmax * (volH - 6))));
      }
      if (pts.length > 1) canvas.drawPoints(PointMode.polygon, pts, Paint()..color = c.muted..strokeWidth = 1);
    }
    // plan levels
    void level(double? v, Color col, String name) {
      if (v == null || v <= 0) return;
      final yy = y(v);
      _dashed(canvas, Offset(0, yy), Offset(plotW, yy), col);
      final r = RRect.fromRectAndRadius(Rect.fromLTWH(plotW + 2, yy - 8, _axisW - 4, 16), const Radius.circular(3));
      canvas.drawRRect(r, Paint()..color = col);
      _label(canvas, Fmt.price(v), Offset(plotW + 6, yy - 7), Colors.white, size: 10.5, bold: true);
      _label(canvas, name, Offset(4, yy - 13), col, size: 10);
    }
    level(stop, c.down, 'Cắt lỗ');
    level(tp1, c.up, 'Chốt lời 1');
    level(tp2, c.up, 'Chốt lời 2');
    // indicator pane (RSI + MACD histogram)
    if (showInd) {
      final top = priceH + volH + 8;
      canvas.drawLine(Offset(0, top), Offset(plotW, top), grid);
      final rsiH = indH * 0.5, macdH = indH * 0.5;
      // RSI
      double yr(double v) => top + rsiH - v / 100 * rsiH;
      for (final lvl in [30.0, 70.0]) {
        _dashed(canvas, Offset(0, yr(lvl)), Offset(plotW, yr(lvl)), c.lineSoft, dash: 3);
      }
      final rsiPts = <Offset>[];
      for (var i = 0; i < shown; i++) {
        if (d[i].rsi != null) rsiPts.add(Offset(x(i), yr(d[i].rsi!)));
      }
      if (rsiPts.length > 1) canvas.drawPoints(PointMode.polygon, rsiPts, Paint()..color = c.ai..strokeWidth = 1.2);
      _label(canvas, 'RSI ${d.last.rsi?.toStringAsFixed(0) ?? '—'}', Offset(4, top + 2), c.faint, size: 10);
      // MACD hist
      final mTop = top + rsiH;
      final mh = d.map((e) => (e.macdH ?? 0).abs()).fold<double>(0, math.max);
      if (mh > 0) {
        final mid = mTop + macdH / 2;
        for (var i = 0; i < shown; i++) {
          final v = d[i].macdH ?? 0;
          final hh = v / mh * (macdH / 2 - 4);
          canvas.drawRect(Rect.fromLTWH(x(i) - bodyW / 2, hh >= 0 ? mid - hh : mid, bodyW, hh.abs()), Paint()..color = (v >= 0 ? c.up : c.down).withValues(alpha: 0.6));
        }
        final mp = <Offset>[], sp = <Offset>[];
        final mm = d.map((e) => math.max((e.macd ?? 0).abs(), (e.macdS ?? 0).abs())).fold<double>(0, math.max);
        for (var i = 0; i < shown; i++) {
          if (d[i].macd != null && mm > 0) mp.add(Offset(x(i), mid - d[i].macd! / mm * (macdH / 2 - 4)));
          if (d[i].macdS != null && mm > 0) sp.add(Offset(x(i), mid - d[i].macdS! / mm * (macdH / 2 - 4)));
        }
        if (mp.length > 1) canvas.drawPoints(PointMode.polygon, mp, Paint()..color = c.link..strokeWidth = 1);
        if (sp.length > 1) canvas.drawPoints(PointMode.polygon, sp, Paint()..color = c.ref..strokeWidth = 1);
      }
      _label(canvas, 'MACD', Offset(4, mTop + 2), c.faint, size: 10);
    }
    // time axis
    final step = math.max(1, n ~/ 6);
    for (var i = 0; i < n; i += step) {
      _label(canvas, Fmt.date(d[i].t, year: n > 200), Offset(x(i) - 16, size.height - 16), c.faint, size: 10);
    }
    // crosshair
    if (cross != null && cross!.dx >= 0 && cross!.dx <= plotW) {
      final i = (cross!.dx / cw).floor().clamp(0, n - 1);
      final e = d[i];
      final cp = Paint()..color = c.muted.withValues(alpha: 0.7)..strokeWidth = 1;
      canvas.drawLine(Offset(x(i), 0), Offset(x(i), size.height - 20), cp);
      if (cross!.dy <= priceH) {
        canvas.drawLine(Offset(0, cross!.dy), Offset(plotW, cross!.dy), cp);
        final pv = hi - cross!.dy / priceH * (hi - lo);
        canvas.drawRRect(RRect.fromRectAndRadius(Rect.fromLTWH(plotW + 2, cross!.dy - 8, _axisW - 4, 16), const Radius.circular(3)), Paint()..color = c.muted);
        _label(canvas, Fmt.price(pv), Offset(plotW + 6, cross!.dy - 7), Colors.white, size: 10.5, bold: true);
      }
      final txt = '${Fmt.date(e.t, year: true)}   M ${Fmt.price(e.o)}  C ${Fmt.price(e.h)}  T ${Fmt.price(e.l)}  Đ ${Fmt.price(e.c)}  KL ${Fmt.volume(e.v)}';
      final tp = TextPainter(text: TextSpan(text: txt, style: ts.copyWith(color: c.text, fontSize: 11, fontWeight: FontWeight.w600)), textDirection: TextDirection.ltr)..layout();
      final bx = (x(i) + 10 + tp.width > plotW) ? x(i) - tp.width - 14 : x(i) + 10;
      canvas.drawRRect(RRect.fromRectAndRadius(Rect.fromLTWH(bx - 4, 4, tp.width + 8, tp.height + 6), const Radius.circular(4)), Paint()..color = c.surface2.withValues(alpha: 0.95));
      tp.paint(canvas, Offset(bx, 7));
    }
  }

  bool _visibleBase(BaseBox b) => d.isNotEmpty && !b.start.isAfter(d.last.t) && (b.end == null || !b.end!.isBefore(d.first.t));

  void _line(Canvas canvas, List<double?> vals, double Function(int) x, double Function(double) y, Color col, int shown) {
    final pts = <Offset>[];
    for (var i = 0; i < shown; i++) {
      if (vals[i] != null) pts.add(Offset(x(i), y(vals[i]!)));
    }
    if (pts.length > 1) {
      final path = Path()..moveTo(pts.first.dx, pts.first.dy);
      for (final p in pts.skip(1)) {
        path.lineTo(p.dx, p.dy);
      }
      canvas.drawPath(path, Paint()..color = col..strokeWidth = 1.3..style = PaintingStyle.stroke);
    }
  }

  void _dashed(Canvas canvas, Offset a, Offset b, Color col, {double dash = 5}) {
    final p = Paint()..color = col..strokeWidth = 1;
    final total = (b - a).distance;
    var t = 0.0;
    while (t < total) {
      final s = a + (b - a) * (t / total);
      final e = a + (b - a) * (math.min(t + dash, total) / total);
      canvas.drawLine(s, e, p);
      t += dash * 2;
    }
  }

  void _label(Canvas canvas, String text, Offset at, Color col, {double size = 11, bool bold = false}) {
    final tp = TextPainter(text: TextSpan(text: text, style: ts.copyWith(color: col, fontSize: size, fontWeight: bold ? FontWeight.w700 : FontWeight.w500)), textDirection: TextDirection.ltr)..layout();
    tp.paint(canvas, at);
  }

  @override
  bool shouldRepaint(covariant _CandlePainter o) => true;
}

/// Tiny line chart for tables / cards.
class Sparkline extends StatelessWidget {
  final List<double> values;
  final double width, height;
  const Sparkline(this.values, {super.key, this.width = 80, this.height = 24});
  @override
  Widget build(BuildContext context) {
    final c = context.vn;
    final up = values.length > 1 && values.last >= values.first;
    return CustomPaint(size: Size(width, height), painter: _SparkPainter(values, up ? c.up : c.down));
  }
}

class _SparkPainter extends CustomPainter {
  final List<double> v;
  final Color col;
  _SparkPainter(this.v, this.col);
  @override
  void paint(Canvas canvas, Size size) {
    if (v.length < 2) return;
    final lo = v.reduce(math.min), hi = v.reduce(math.max);
    final path = Path();
    for (var i = 0; i < v.length; i++) {
      final x = i / (v.length - 1) * size.width;
      final y = hi == lo ? size.height / 2 : (hi - v[i]) / (hi - lo) * (size.height - 2) + 1;
      i == 0 ? path.moveTo(x, y) : path.lineTo(x, y);
    }
    canvas.drawPath(path, Paint()..color = col..strokeWidth = 1.4..style = PaintingStyle.stroke);
  }

  @override
  bool shouldRepaint(covariant _SparkPainter o) => o.v != v;
}
