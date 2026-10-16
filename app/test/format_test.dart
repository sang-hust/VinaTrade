import 'package:flutter_test/flutter_test.dart';
import 'package:vinatrade/core/format.dart';

void main() {
  group('Fmt (định dạng số kiểu Việt Nam)', () {
    test('giá đủ đồng với dấu chấm hàng nghìn', () {
      expect(Fmt.price(128500), '128.500');
      expect(Fmt.priceVnd(128500), '128.500 VNĐ');
      expect(Fmt.price(null), '—');
    });
    test('thay đổi luôn có dấu, dấu trừ thật', () {
      expect(Fmt.signed(2000), '+2.000');
      expect(Fmt.signed(-500), '−500');
      expect(Fmt.pct(1.58), '+1,58%');
      expect(Fmt.pct(-0.65), '−0,65%');
      expect(Fmt.change(2000, 1.58), '+2.000 (+1,58%)');
    });
    test('chỉ số hai số lẻ với dấu phẩy', () {
      expect(Fmt.index(1684.27), '1.684,27');
    });
    test('khối lượng và tiền rút gọn', () {
      expect(Fmt.volume(4820000), '4,82 tr');
      expect(Fmt.volume(850000), '850 nghìn');
      expect(Fmt.money(616e9), '616 tỷ');
      expect(Fmt.money(9.6e6), '9,6 tr');
      expect(Fmt.money(1284000000, full: true), '1.284.000.000');
    });
    test('số lượng cổ phiếu', () {
      expect(Fmt.qty(1800), '1.800 cp');
    });
  });
}
