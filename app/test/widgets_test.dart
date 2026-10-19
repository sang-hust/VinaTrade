import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:vinatrade/core/theme.dart';
import 'package:vinatrade/shared/widgets/score.dart';
import 'package:vinatrade/shared/widgets/stock_rows.dart';

Widget _wrap(Widget child, {Brightness b = Brightness.dark}) => MaterialApp(theme: buildTheme(b), home: Scaffold(body: Center(child: SizedBox(width: 300, child: child))));

void main() {
  testWidgets('ScoreGauge hiện điểm và vạch vị trí', (tester) async {
    await tester.pumpWidget(_wrap(const ScoreGauge(score: 84)));
    await tester.pumpAndSettle();
    expect(find.text('84'), findsOneWidget);
  });

  testWidgets('ScoreGauge không có điểm → gạch ngang', (tester) async {
    await tester.pumpWidget(_wrap(const ScoreGauge(score: null)));
    await tester.pumpAndSettle();
    expect(find.text('—'), findsOneWidget);
  });

  testWidgets('RatingChip dịch tên khuyến nghị', (tester) async {
    await tester.pumpWidget(_wrap(const RatingChip('STRONG_BUY', score: 84)));
    expect(find.text('Mua mạnh · 84'), findsOneWidget);
  });

  testWidgets('TrendChips tô màu ▲▬▼', (tester) async {
    await tester.pumpWidget(_wrap(const TrendChips('▲▬▼')));
    expect(find.text('▲'), findsOneWidget);
    expect(find.text('▼'), findsOneWidget);
  });

  testWidgets('DetailGate ẩn khối dưới mức chi tiết', (tester) async {
    await tester.pumpWidget(_wrap(const Column(children: [
      DetailGate(min: 'STANDARD', current: 'SIMPLE', child: Text('ẩn')),
      DetailGate(min: 'STANDARD', current: 'FULL', child: Text('hiện')),
    ])));
    expect(find.text('ẩn'), findsNothing);
    expect(find.text('hiện'), findsOneWidget);
  });

  test('VNColors: màu giá theo quy ước bảng điện', () {
    const c = VNColors.dark;
    expect(c.priceColor(60200, 56300, 60200, 52400), c.ceil);
    expect(c.priceColor(52400, 56300, 60200, 52400), c.floor);
    expect(c.priceColor(57100, 56300, 60200, 52400), c.upText);
    expect(c.priceColor(56300, 56300, 60200, 52400), c.ref);
    expect(c.ratingColor('SELL'), c.sell);
    expect(c.scoreColor(72), c.buy);
  });

  testWidgets('riskCell / riskPill hiện mức rủi ro tổng hợp, kèm dự phòng theo rủi ro DN', (tester) async {
    await tester.pumpWidget(_wrap(Builder(builder: (ctx) => Column(children: [
      riskCell(ctx, const {'risk_total': 18.4, 'risk_total_level': 'LOW'}),
      riskCell(ctx, const {'risk_score': 65}),
      riskPill(ctx, const {'risk_total_level': 'MEDIUM'}),
      riskPill(ctx, const {'risk_score': 10}),
    ]))));
    expect(find.text('Thấp'), findsOneWidget);
    expect(find.text(' 18'), findsOneWidget);
    expect(find.text('Cao'), findsOneWidget);
    expect(find.text('Rủi ro trung bình'), findsOneWidget);
    expect(find.textContaining('Rủi ro'), findsOneWidget);
  });
}
