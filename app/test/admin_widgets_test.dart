import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:vinatrade/core/theme.dart';
import 'package:vinatrade/features/admin/admin_common.dart';

Widget _wrap(Widget child, {double width = 900}) => ProviderScope(child: MaterialApp(theme: buildTheme(Brightness.light), home: Scaffold(body: Center(child: SizedBox(width: width, child: SingleChildScrollView(child: child))))));

void main() {
  testWidgets('AdminHeader hiện tiêu đề, mô tả và nút hành động', (tester) async {
    await tester.pumpWidget(_wrap(AdminHeader('Người dùng', subtitle: '16 tài khoản.', actions: [OutlinedButton(onPressed: () {}, child: const Text('Tạo mã mời'))])));
    expect(find.text('Người dùng'), findsOneWidget);
    expect(find.text('16 tài khoản.'), findsOneWidget);
    expect(find.text('Tạo mã mời'), findsOneWidget);
  });

  testWidgets('DiffView chỉ hiện trường thay đổi, dạng trước → sau', (tester) async {
    await tester.pumpWidget(_wrap(const DiffView(before: {'value': {'fee_pct': 0.15, 'tax_pct': 0.1}}, after: {'value': {'fee_pct': 0.1, 'tax_pct': 0.1}})));
    final rich = tester.widgetList<RichText>(find.byType(RichText)).map((r) => r.text.toPlainText()).join('\n');
    expect(rich, contains('fee_pct: 0.15 → 0.1'));
    expect(rich, isNot(contains('tax_pct')));
  });

  testWidgets('DiffView không đổi → "Không đổi"', (tester) async {
    await tester.pumpWidget(_wrap(const DiffView(before: {'a': 1}, after: {'a': 1})));
    expect(find.text('Không đổi'), findsOneWidget);
  });

  testWidgets('HeatCell tô màu theo ngưỡng 60/50 và làm mờ ô dưới 30 lần', (tester) async {
    await tester.pumpWidget(_wrap(const Row(children: [HeatCell(winRate: 66, samples: 312), HeatCell(winRate: 52, samples: 141), HeatCell(winRate: 38, samples: 22)])));
    expect(find.textContaining('66%', findRichText: true), findsOneWidget);
    expect(find.textContaining('(22 lần)', findRichText: true), findsOneWidget);
    final ops = tester.widgetList<Opacity>(find.byType(Opacity)).map((o) => o.opacity).toList();
    expect(ops, [1, 1, 0.5]);
    final c = VNColors.light;
    expect(winRateColor(c, 66), c.up);
    expect(winRateColor(c, 52), c.ref);
    expect(winRateColor(c, 38), c.down);
  });

  testWidgets('ConfigCard dạng form: nhãn, đơn vị, mặc định, nút Lưu chỉ bật khi sửa', (tester) async {
    final row = {
      'key': 'market.fees', 'label': 'Phí, thuế và thanh toán', 'description': 'Phí, thuế mặc định', 'kind': 'form', 'group': 'market',
      'value': {'fee_pct': 0.15, 'tax_pct': 0.1, 'settlement_days': 2}, 'default': {'fee_pct': 0.15, 'tax_pct': 0.1, 'settlement_days': 2},
      'fields': [
        {'key': 'fee_pct', 'label': 'Phí giao dịch', 'unit': '%', 'type': 'number'},
        {'key': 'tax_pct', 'label': 'Thuế bán', 'unit': '%', 'type': 'number'},
        {'key': 'settlement_days', 'label': 'Chu kỳ thanh toán', 'unit': 'ngày (T+)', 'type': 'int'},
      ],
      'updated_by': 'admin@vinatrade.vn', 'updated_at': DateTime.now().toIso8601String(),
    };
    await tester.pumpWidget(_wrap(ConfigCard(row: row, onChanged: () {})));
    expect(find.text('Phí, thuế và thanh toán'), findsOneWidget);
    expect(find.text('Phí giao dịch'), findsOneWidget);
    expect(find.text('ngày (T+)'), findsOneWidget);
    expect(find.text('Mặc định'), findsOneWidget); // pill: value equals default
    expect(find.textContaining('Sửa lần cuối: admin@vinatrade.vn'), findsOneWidget);
    expect(find.text('Lịch sử'), findsOneWidget);
    final save = tester.widget<FilledButton>(find.widgetWithText(FilledButton, 'Lưu'));
    expect(save.onPressed, isNull);
    await tester.enterText(find.widgetWithText(TextField, 'Phí giao dịch'), '0.1');
    await tester.pump();
    expect(tester.widget<FilledButton>(find.widgetWithText(FilledButton, 'Lưu')).onPressed, isNotNull);
    expect(find.text('Hủy'), findsOneWidget);
  });

  testWidgets('ConfigCard dạng bool hiện công tắc, không có nút Lưu', (tester) async {
    await tester.pumpWidget(_wrap(ConfigCard(row: const {'key': 'signals.explain_with_ai', 'label': 'AI viết câu kết luận', 'description': 'Dùng AI viết câu kết luận', 'kind': 'bool', 'value': true, 'default': true}, onChanged: () {})));
    expect(find.byType(Switch), findsOneWidget);
    expect(find.widgetWithText(FilledButton, 'Lưu'), findsNothing);
  });

  test('nhãn tiếng Việt cho trạng thái, hành động và tên mục', () {
    expect(jobStatusVi['DONE'], 'Thành công');
    expect(signalTypeVi['SELL'], 'Giảm tỷ trọng');
    expect(auditActionVi['STRATEGY_VERSION'], 'Bật phiên bản chiến lược');
    expect(sectionTitle('overview'), 'Tổng quan hệ thống');
    expect(sectionTitle('config'), 'Cấu hình chấm điểm');
    expect(adminSections.map((s) => s.$1), contains('performance'));
    expect(fmtDuration(972000), '16 phút 12 giây');
    expect(fmtDuration(900), '0.9 giây');
  });
}
