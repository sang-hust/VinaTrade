import 'package:intl/intl.dart';

/// Vietnamese number formatting (UI spec 6.2). Prices are integer VND, real minus sign, "—" for missing.
class Fmt {
  static const minus = '−';
  static const dash = '—';

  static String _group(num v, {int decimals = 0}) {
    final neg = v < 0;
    final abs = v.abs();
    final fixed = abs.toStringAsFixed(decimals);
    final parts = fixed.split('.');
    final intPart = parts[0].replaceAllMapped(RegExp(r'\B(?=(\d{3})+(?!\d))'), (m) => '.');
    final s = parts.length > 1 ? '$intPart,${parts[1]}' : intPart;
    return neg ? '$minus$s' : s;
  }

  /// 128500 → "128.500"
  static String price(num? v) => v == null ? dash : _group(v.round());

  /// 128500 → "128.500 VNĐ"
  static String priceVnd(num? v) => v == null ? dash : '${_group(v.round())} VNĐ';

  /// +2000 → "+2.000", -500 → "−500"
  static String signed(num? v, {int decimals = 0}) {
    if (v == null) return dash;
    final s = _group(v, decimals: decimals);
    return v > 0 ? '+$s' : s;
  }

  /// 1.58 → "+1,58%"
  static String pct(num? v, {int decimals = 2, bool sign = true}) {
    if (v == null) return dash;
    final s = _group(v, decimals: decimals);
    return (sign && v > 0 ? '+$s' : s) + '%';
  }

  /// change + pct: "+2.000 (+1,58%)"
  static String change(num? chg, num? pct_) => chg == null && pct_ == null ? dash : '${signed(chg)} (${pct(pct_)})';

  /// index: 1684.27 → "1.684,27"
  static String index(num? v) => v == null ? dash : _group(v, decimals: 2);

  /// volume: 4820000 → "4,82 tr", 850000 → "850 nghìn"
  static String volume(num? v) {
    if (v == null) return dash;
    final a = v.abs();
    if (a >= 1e6) return '${_group(v / 1e6, decimals: 2)} tr';
    if (a >= 1e3) return '${_group(v / 1e3, decimals: 0)} nghìn';
    return _group(v);
  }

  /// money: 616e9 → "616 tỷ", 9.6e6 → "9,6 tr"
  static String money(num? v, {bool full = false}) {
    if (v == null) return dash;
    if (full) return _group(v.round());
    final a = v.abs();
    if (a >= 1e9) return '${_group(v / 1e9, decimals: a >= 100e9 ? 0 : (a >= 10e9 ? 1 : 2))} tỷ';
    if (a >= 1e6) return '${_group(v / 1e6, decimals: a >= 100e6 ? 0 : 1)} tr';
    return _group(v.round());
  }

  static String num_(num? v, {int decimals = 1}) => v == null ? dash : _group(v, decimals: decimals);

  static String score(num? v) => v == null ? dash : v.round().toString();

  static String ratio(num? v) => v == null ? dash : '1 : ${_group(v, decimals: 1)}';

  static String date(DateTime? d, {bool year = false}) => d == null ? dash : DateFormat(year ? 'dd/MM/yyyy' : 'dd/MM').format(d.toLocal());

  static String dateTime(DateTime? d) => d == null ? dash : DateFormat('dd/MM HH:mm').format(d.toLocal());

  static String relative(DateTime? d) {
    if (d == null) return dash;
    final now = DateTime.now();
    final l = d.toLocal();
    final today = DateTime(now.year, now.month, now.day);
    final day = DateTime(l.year, l.month, l.day);
    final diff = today.difference(day).inDays;
    if (diff == 0) return 'Hôm nay ${DateFormat('HH:mm').format(l)}';
    if (diff == 1) return 'Hôm qua ${DateFormat('HH:mm').format(l)}';
    return DateFormat('dd/MM HH:mm').format(l);
  }

  static String dayLabel(DateTime d) {
    final now = DateTime.now();
    final l = d.toLocal();
    final today = DateTime(now.year, now.month, now.day);
    final day = DateTime(l.year, l.month, l.day);
    final diff = today.difference(day).inDays;
    if (diff == 0) return 'Hôm nay';
    if (diff == 1) return 'Hôm qua';
    const days = ['Thứ Hai', 'Thứ Ba', 'Thứ Tư', 'Thứ Năm', 'Thứ Sáu', 'Thứ Bảy', 'Chủ Nhật'];
    return '${days[l.weekday - 1]} ${DateFormat('dd/MM').format(l)}';
  }

  static DateTime? parseDate(dynamic s) => s == null ? null : DateTime.tryParse(s.toString());

  /// Quantity of shares: 1800 → "1.800 cp"
  static String qty(num? v) => v == null ? dash : '${_group(v.round())} cp';

  static String percentOf(num? a, num? b) => (a == null || b == null || b == 0) ? dash : pct(a / b * 100, decimals: 1, sign: false);
}

num? asNum(dynamic v) => v == null ? null : (v is num ? v : num.tryParse(v.toString()));
int? asInt(dynamic v) => asNum(v)?.toInt();
double? asDouble(dynamic v) => asNum(v)?.toDouble();
String? asStr(dynamic v) => v?.toString();
List<Map<String, dynamic>> asList(dynamic v) => (v as List? ?? const []).map((e) => (e as Map).cast<String, dynamic>()).toList();
Map<String, dynamic> asMap(dynamic v) => (v as Map? ?? const {}).cast<String, dynamic>();
