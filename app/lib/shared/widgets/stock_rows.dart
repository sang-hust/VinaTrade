import 'package:flutter/material.dart';
import 'package:go_router/go_router.dart';

import '../../core/format.dart';
import '../../core/responsive.dart';
import '../../core/theme.dart';
import 'common.dart';
import 'score.dart';

/// Column spec for StockTable.
class StockCol {
  final String key;
  final String label;
  final double width;
  final bool numeric;
  final Widget Function(BuildContext, Map<String, dynamic>)? build;
  const StockCol(this.key, this.label, {this.width = 90, this.numeric = true, this.build});
}

Widget priceCell(BuildContext ctx, Map<String, dynamic> r) {
  final c = ctx.vn;
  return Text(Fmt.price(asNum(r['price'])), style: TextStyle(color: c.priceColor(asNum(r['price']), asNum(r['ref_price']), asNum(r['ceiling']), asNum(r['floor'])), fontWeight: FontWeight.w600));
}

Widget changeCell(BuildContext ctx, Map<String, dynamic> r) => Text(Fmt.pct(asNum(r['change_pct'])), style: TextStyle(color: ctx.vn.changeColor(asNum(r['change_pct']))));

const stdCols = [
  StockCol('price', 'Giá (VNĐ)', width: 90, build: priceCell),
  StockCol('change_pct', '+/−', width: 72, build: changeCell),
  StockCol('trend3', 'N·T·D', width: 70, build: _trendCell),
  StockCol('score', 'Điểm', width: 120, build: _scoreCell),
  StockCol('rating', 'Khuyến nghị', width: 120, numeric: false, build: _ratingCell),
  StockCol('entry', 'Vùng mua', width: 120, build: _entryCell),
  StockCol('stop_loss', 'Cắt lỗ', width: 80, build: _stopCell),
  StockCol('risk', 'Rủi ro', width: 96, build: riskCell),
];

Widget _trendCell(BuildContext ctx, Map<String, dynamic> r) => TrendChips(r['trend3']?.toString());
Widget _scoreCell(BuildContext ctx, Map<String, dynamic> r) => ScoreGauge(score: asNum(r['score']), compact: true);
Widget _ratingCell(BuildContext ctx, Map<String, dynamic> r) => Align(alignment: Alignment.centerLeft, child: RatingChip(r['rating_hz']?.toString() ?? r['rating']?.toString()));
Widget _entryCell(BuildContext ctx, Map<String, dynamic> r) => Text(r['entry_low'] == null ? Fmt.dash : '${Fmt.price(asNum(r['entry_low']))}–${Fmt.price(asNum(r['entry_high']))}', style: TextStyle(color: ctx.vn.muted, fontSize: 12.5));
Widget _stopCell(BuildContext ctx, Map<String, dynamic> r) => Text(Fmt.price(asNum(r['stop_loss'])), style: TextStyle(color: ctx.vn.downText, fontSize: 12.5));
/// Total-risk cell: level word coloured by risk (falls back to the company-risk score on old rows). Always shown (BR-20).
Widget riskCell(BuildContext ctx, Map<String, dynamic> r) {
  final c = ctx.vn;
  final total = asNum(r['risk_total']);
  final level = r['risk_total_level']?.toString() ?? (asNum(r['risk_score']) == null ? null : ((asNum(r['risk_score'])! >= 60) ? 'HIGH' : (asNum(r['risk_score'])! >= 35 ? 'MEDIUM' : 'LOW')));
  if (level == null) return Text(Fmt.dash, style: TextStyle(color: c.faint));
  final col = {'LOW': c.up, 'MEDIUM': c.ref, 'HIGH': c.downText}[level] ?? c.muted;
  return Row(mainAxisSize: MainAxisSize.min, children: [
    StatusDot(col, size: 7), const SizedBox(width: 5),
    Text({'LOW': 'Thấp', 'MEDIUM': 'Trung bình', 'HIGH': 'Cao'}[level]!, style: TextStyle(color: col, fontWeight: FontWeight.w600, fontSize: 12.5)),
    if (total != null) Text(' ${Fmt.score(total)}', style: TextStyle(color: c.faint, fontSize: 11.5)),
  ]);
}

/// Risk pill for cards: "Rủi ro thấp / trung bình / cao".
Widget riskPill(BuildContext ctx, Map<String, dynamic> r, {double fontSize = 10}) {
  final c = ctx.vn;
  final level = r['risk_total_level']?.toString() ?? ((asNum(r['risk_score']) ?? 0) >= 60 ? 'HIGH' : null);
  if (level == null) return const SizedBox.shrink();
  return Pill('Rủi ro ${{'LOW': 'thấp', 'MEDIUM': 'trung bình', 'HIGH': 'cao'}[level]}', color: {'LOW': c.up, 'MEDIUM': c.ref, 'HIGH': c.down}[level]!, fontSize: fontSize);
}

/// Desktop: sticky-first-column table (horizontal scroll for the rest); phone/tablet: card list.
class StockTable extends StatelessWidget {
  final List<Map<String, dynamic>> rows;
  final List<StockCol> columns;
  final Widget Function(BuildContext, Map<String, dynamic>)? trailing;
  final String? subtitleKey; // e.g. 'event' shown under symbol
  final bool highlightChanged;
  final void Function(Map<String, dynamic>)? onTap;
  final double minWidth;
  final bool shrink;
  const StockTable({super.key, required this.rows, this.columns = stdCols, this.trailing, this.subtitleKey, this.highlightChanged = true, this.onTap, this.minWidth = 900, this.shrink = false});

  static const rowH = 44.0;
  static const headH = 36.0;
  static const firstW = 150.0;

  void _open(BuildContext ctx, Map<String, dynamic> r) => onTap != null ? onTap!(r) : ctx.push('/stocks/${r['symbol']}');

  @override
  Widget build(BuildContext context) {
    if (rows.isEmpty) return const SizedBox.shrink();
    if (context.isPhone || context.layout == Layout.tablet) return _cards(context);
    final c = context.vn;
    final headStyle = TextStyle(color: c.faint, fontSize: 12, fontWeight: FontWeight.w500);
    Widget cell(double w, Widget child, {bool head = false}) => SizedBox(width: w, height: head ? headH : rowH, child: Padding(padding: const EdgeInsets.symmetric(horizontal: 6), child: Align(alignment: Alignment.centerLeft, child: child)));
    Color? rowColor(Map<String, dynamic> r) => r['rating_changed'] == true && highlightChanged ? c.accent.withValues(alpha: 0.08) : null;
    final left = Column(children: [
      cell(firstW, Text('Mã', style: headStyle), head: true),
      for (final r in rows)
        InkWell(
          onTap: () => _open(context, r),
          child: Container(
            color: rowColor(r), decoration: rowColor(r) == null ? BoxDecoration(border: Border(top: BorderSide(color: c.lineSoft))) : null,
            child: cell(firstW, Row(children: [
              Hero(tag: 'sym-${r['symbol']}', child: Material(color: Colors.transparent, child: Text(r['symbol'].toString(), style: TextStyle(fontWeight: FontWeight.w700, color: c.text)))),
              const SizedBox(width: 6),
              Expanded(child: Text((subtitleKey != null ? r[subtitleKey] : null)?.toString() ?? r['name']?.toString() ?? '', maxLines: 2, overflow: TextOverflow.ellipsis, style: TextStyle(color: c.muted, fontSize: 11))),
            ])),
          ),
        ),
    ]);
    final right = Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
      Row(children: [for (final col in columns) cell(col.width, Text(col.label, style: headStyle), head: true), if (trailing != null) cell(110, const SizedBox(), head: true)]),
      for (final r in rows)
        InkWell(
          onTap: () => _open(context, r),
          child: Container(
            color: rowColor(r), decoration: rowColor(r) == null ? BoxDecoration(border: Border(top: BorderSide(color: c.lineSoft))) : null,
            child: Row(children: [
              for (final col in columns) cell(col.width, col.build != null ? col.build!(context, r) : Text(r[col.key]?.toString() ?? Fmt.dash)),
              if (trailing != null) cell(110, trailing!(context, r)),
            ]),
          ),
        ),
    ]);
    return Row(crossAxisAlignment: CrossAxisAlignment.start, children: [
      Container(decoration: BoxDecoration(border: Border(right: BorderSide(color: c.line))), child: left),
      Expanded(child: SingleChildScrollView(scrollDirection: Axis.horizontal, child: right)),
    ]);
  }

  Widget _cards(BuildContext context) => Column(children: [
        for (var i = 0; i < rows.length; i++)
          Padding(padding: const EdgeInsets.only(bottom: 10), child: StockCard(rows[i], subtitleKey: subtitleKey, trailing: trailing, onTap: () => _open(context, rows[i])).stagger(context, i)),
      ]);
}

class StockCard extends StatelessWidget {
  final Map<String, dynamic> r;
  final String? subtitleKey;
  final Widget Function(BuildContext, Map<String, dynamic>)? trailing;
  final VoidCallback? onTap;
  const StockCard(this.r, {super.key, this.subtitleKey, this.trailing, this.onTap});
  @override
  Widget build(BuildContext context) {
    final c = context.vn;
    final sub = (subtitleKey != null ? r[subtitleKey] : null)?.toString() ?? r['name']?.toString();
    final rating = r['rating_hz']?.toString() ?? r['rating']?.toString();
    return AppCard(
      padding: const EdgeInsets.all(12),
      onTap: onTap,
      borderColor: r['rating_changed'] == true ? c.accent.withValues(alpha: 0.6) : null,
      child: Row(children: [
        Expanded(
          child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
            Row(children: [
              Hero(tag: 'sym-${r['symbol']}', child: Material(color: Colors.transparent, child: Text(r['symbol'].toString(), style: TextStyle(fontWeight: FontWeight.w700, fontSize: 16, color: c.text)))),
              const SizedBox(width: 8),
              TrendChips(r['trend3']?.toString()),
              if (r['is_chase'] == true) ...[const SizedBox(width: 6), Pill('Mua đuổi', color: c.ref, fontSize: 10)],
              const SizedBox(width: 6), riskPill(context, r),
            ]),
            if (sub != null) Padding(padding: const EdgeInsets.only(top: 2), child: Text(sub, maxLines: 2, overflow: TextOverflow.ellipsis, style: TextStyle(color: c.muted, fontSize: 12))),
            const SizedBox(height: 6),
            Row(children: [
              Text(Fmt.price(asNum(r['price'])), style: TextStyle(color: c.priceColor(asNum(r['price']), asNum(r['ref_price']), asNum(r['ceiling']), asNum(r['floor'])), fontWeight: FontWeight.w700, fontSize: 15)),
              const SizedBox(width: 8),
              Text(Fmt.pct(asNum(r['change_pct'])), style: TextStyle(color: c.changeColor(asNum(r['change_pct'])), fontSize: 13)),
              if (r['rating_changed'] == true) ...[const SizedBox(width: 8), Pill('Đổi khuyến nghị', color: c.link, fontSize: 10)],
            ]),
            if (asMap(r['risk_numbers'])['text'] != null) Padding(padding: const EdgeInsets.only(top: 4), child: Text(asMap(r['risk_numbers'])['text'].toString(), maxLines: 3, overflow: TextOverflow.ellipsis, style: TextStyle(color: c.muted, fontSize: 11.5, height: 1.3))),
          ]),
        ),
        const SizedBox(width: 10),
        Column(crossAxisAlignment: CrossAxisAlignment.end, children: [
          Container(
            padding: const EdgeInsets.symmetric(horizontal: 10, vertical: 6),
            decoration: BoxDecoration(color: c.ratingBg(rating), borderRadius: BorderRadius.circular(8)),
            child: Column(children: [
              Text(Fmt.score(asNum(r['score'])), style: TextStyle(fontSize: 18, fontWeight: FontWeight.w700, color: c.ratingColor(rating))),
              Text(r['rating_vi']?.toString() ?? ratingVi[rating] ?? '—', style: TextStyle(fontSize: 11, color: c.ratingColor(rating), fontWeight: FontWeight.w600)),
            ]),
          ),
          if (trailing != null) Padding(padding: const EdgeInsets.only(top: 6), child: trailing!(context, r)),
        ]),
      ]),
    );
  }
}

/// Compact "Mua" button used in table rows (always goes through the pretrade sheet).
class BuyButton extends StatelessWidget {
  final VoidCallback onPressed;
  final String label;
  const BuyButton({super.key, required this.onPressed, this.label = 'Mua'});
  @override
  Widget build(BuildContext context) => SizedBox(height: 30, child: FilledButton(onPressed: onPressed, style: FilledButton.styleFrom(padding: const EdgeInsets.symmetric(horizontal: 12), visualDensity: VisualDensity.compact), child: Text(label, style: const TextStyle(fontSize: 12.5))));
}
