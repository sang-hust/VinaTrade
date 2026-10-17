import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:vinatrade/core/theme.dart';
import 'package:vinatrade/features/stock/insights_widgets.dart';

void main() {
  testWidgets('NewsList renders items whose symbols are plain strings (market news card)', (tester) async {
    await tester.pumpWidget(MaterialApp(
      theme: buildTheme(Brightness.dark),
      home: Scaffold(body: SingleChildScrollView(child: NewsList(showSymbols: true, items: [
        {'id': 1, 'title': 'Một quỹ thoát hàng PNJ, vẫn tin FPT', 'summary': 'Tóm tắt', 'url': 'https://cafef.vn/x', 'source': 'CafeF',
         'published_at': '2026-10-16T09:00:00+07:00', 'symbols': ['PNJ', 'FPT'], 'sentiment_label': 'NEGATIVE'},
        {'id': 2, 'title': 'Tin không gắn mã', 'source': 'VnExpress', 'published_at': '2026-10-16T08:00:00+07:00', 'symbols': [], 'sentiment_label': null},
      ]))),
    ));
    await tester.pump(const Duration(seconds: 1));
    expect(tester.takeException(), isNull);
    expect(find.text('PNJ'), findsOneWidget);
    expect(find.text('FPT'), findsOneWidget);
    expect(find.text('Tiêu cực'), findsOneWidget);
  });
}
