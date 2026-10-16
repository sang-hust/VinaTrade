import 'package:flutter/material.dart';
import 'package:google_fonts/google_fonts.dart';

/// Market + rating colors per UI spec 5.x, as a ThemeExtension (spec 17.1).
@immutable
class VNColors extends ThemeExtension<VNColors> {
  final Color up, down, ref, ceil, floor, accent, link, ai, bg, surface, surface2, line, lineSoft, text, muted, faint;
  final Color strongBuy, buy, hold, reduce, sell, strongBuyBg, buyBg, holdBg, reduceBg, sellBg;
  final Color urgent, urgentBg, urgentBorder, risk, riskBg, riskBorder, suggest, suggestBg;

  const VNColors({
    required this.up, required this.down, required this.ref, required this.ceil, required this.floor, required this.accent, required this.link, required this.ai,
    required this.bg, required this.surface, required this.surface2, required this.line, required this.lineSoft, required this.text, required this.muted, required this.faint,
    required this.strongBuy, required this.buy, required this.hold, required this.reduce, required this.sell,
    required this.strongBuyBg, required this.buyBg, required this.holdBg, required this.reduceBg, required this.sellBg,
    required this.urgent, required this.urgentBg, required this.urgentBorder, required this.risk, required this.riskBg, required this.riskBorder, required this.suggest, required this.suggestBg,
  });

  static const dark = VNColors(
    up: Color(0xFF2FBF71), down: Color(0xFFF0545A), ref: Color(0xFFF2B33D), ceil: Color(0xFFC38BFF), floor: Color(0xFF43C7E6), accent: Color(0xFF2F6FE0), link: Color(0xFF7FB0FF), ai: Color(0xFFB9A2FF),
    bg: Color(0xFF0B1119), surface: Color(0xFF121A25), surface2: Color(0xFF0E1520), line: Color(0xFF233040), lineSoft: Color(0xFF1C2634), text: Color(0xFFE8EEF5), muted: Color(0xFFA3B0C0), faint: Color(0xFF8E9BAC),
    strongBuy: Color(0xFF5FD896), buy: Color(0xFF7FDCAB), hold: Color(0xFFD3DCE6), reduce: Color(0xFFFF8A8F), sell: Color(0xFFF0545A),
    strongBuyBg: Color(0xFF173A2A), buyBg: Color(0xFF15301F), holdBg: Color(0xFF1B2532), reduceBg: Color(0xFF3D2326), sellBg: Color(0xFF3D2326),
    urgent: Color(0xFFFF8A8F), urgentBg: Color(0xFF3D2326), urgentBorder: Color(0xFF4A2A2E), risk: Color(0xFFF2B33D), riskBg: Color(0xFF2E2614), riskBorder: Color(0xFF4A3F22), suggest: Color(0xFF9CC2FF), suggestBg: Color(0xFF172A4A),
  );

  static const light = VNColors(
    up: Color(0xFF0E9F4F), down: Color(0xFFD93A3F), ref: Color(0xFFB98900), ceil: Color(0xFF9B4DCA), floor: Color(0xFF0A9CB0), accent: Color(0xFF2F6FE0), link: Color(0xFF2457C5), ai: Color(0xFF6D4FD8),
    bg: Color(0xFFF4F6FA), surface: Color(0xFFFFFFFF), surface2: Color(0xFFEEF2F8), line: Color(0xFFDCE3EE), lineSoft: Color(0xFFE8EDF4), text: Color(0xFF13213A), muted: Color(0xFF5B6B86), faint: Color(0xFF94A3BB),
    strongBuy: Color(0xFF0E9F4F), buy: Color(0xFF46B97A), hold: Color(0xFF5B6B86), reduce: Color(0xFFC24A4F), sell: Color(0xFFD93A3F),
    strongBuyBg: Color(0xFFE2F5EA), buyBg: Color(0xFFE6F6EC), holdBg: Color(0xFFEEF2F8), reduceBg: Color(0xFFFBE7E8), sellBg: Color(0xFFFBE7E8),
    urgent: Color(0xFFD93A3F), urgentBg: Color(0xFFFBE7E8), urgentBorder: Color(0xFFF2C5C7), risk: Color(0xFFB98900), riskBg: Color(0xFFFFF4D6), riskBorder: Color(0xFFF0DFA6), suggest: Color(0xFF2457C5), suggestBg: Color(0xFFE4ECFB),
  );

  /// Dark-mode text variant for up/down (spec 5.2).
  Color get upText => bg == dark.bg ? const Color(0xFF5FD896) : up;
  Color get downText => bg == dark.bg ? const Color(0xFFFF8A8F) : down;

  Color priceColor(num? price, num? refPrice, num? ceiling, num? floorPrice) {
    if (price == null || refPrice == null) return text;
    if (ceiling != null && price >= ceiling) return ceil;
    if (floorPrice != null && price <= floorPrice) return floor;
    if (price > refPrice) return upText;
    if (price < refPrice) return downText;
    return ref;
  }

  Color changeColor(num? v) => v == null ? muted : (v > 0 ? upText : (v < 0 ? downText : ref));

  Color ratingColor(String? r) => switch (r) { 'STRONG_BUY' => strongBuy, 'BUY' => buy, 'HOLD' => hold, 'REDUCE' => reduce, 'SELL' => sell, _ => muted };
  Color ratingBg(String? r) => switch (r) { 'STRONG_BUY' => strongBuyBg, 'BUY' => buyBg, 'HOLD' => holdBg, 'REDUCE' => reduceBg, 'SELL' => sellBg, _ => surface2 };
  Color scoreColor(num? s) => s == null ? muted : (s >= 80 ? strongBuy : (s >= 65 ? buy : (s >= 50 ? hold : (s >= 35 ? reduce : sell))));
  Color priorityColor(String? p) => switch (p) { 'URGENT' => urgent, 'RISK' => risk, 'SUGGEST' => suggest, 'HIGH' => accent, 'INFO' => muted, _ => muted };
  Color priorityBg(String? p) => switch (p) { 'URGENT' => urgentBg, 'RISK' => riskBg, 'SUGGEST' => suggestBg, _ => surface2 };
  Color regimeColor(String? r) => switch (r) { 'UPTREND' => up, 'PRESSURE' => ref, 'CORRECTION' => const Color(0xFFF08A3D), 'DOWNTREND' => down, _ => muted };
  Color levelColor(String? l) => switch (l) { 'GREEN' => up, 'YELLOW' => ref, 'RED' => down, 'LOW' => up, 'MEDIUM' => ref, 'HIGH' => down, _ => muted };

  @override
  VNColors copyWith() => this;

  @override
  VNColors lerp(ThemeExtension<VNColors>? other, double t) => t < 0.5 ? this : (other as VNColors? ?? this);
}

extension VNColorsX on BuildContext {
  VNColors get vn => Theme.of(this).extension<VNColors>()!;
}

ThemeData buildTheme(Brightness b) {
  final c = b == Brightness.dark ? VNColors.dark : VNColors.light;
  final base = ThemeData(brightness: b, useMaterial3: true, colorSchemeSeed: c.accent, scaffoldBackgroundColor: c.bg);
  final scheme = base.colorScheme.copyWith(primary: c.accent, surface: c.surface, onSurface: c.text, outline: c.line, error: c.down);
  final family = GoogleFonts.beVietnamPro().fontFamily;
  final text = base.textTheme.apply(fontFamily: family, bodyColor: c.text, displayColor: c.text);
  final tabular = text.copyWith(
    bodyLarge: text.bodyLarge?.copyWith(fontSize: 15, fontFeatures: const [FontFeature.tabularFigures()]),
    bodyMedium: text.bodyMedium?.copyWith(fontSize: 14, fontFeatures: const [FontFeature.tabularFigures()]),
    bodySmall: text.bodySmall?.copyWith(fontSize: 12.5, color: c.muted, fontFeatures: const [FontFeature.tabularFigures()]),
    labelSmall: text.labelSmall?.copyWith(fontSize: 11.5, color: c.faint),
    labelMedium: text.labelMedium?.copyWith(fontSize: 12.5, color: c.muted),
    titleMedium: text.titleMedium?.copyWith(fontSize: 16, fontWeight: FontWeight.w600),
    titleLarge: text.titleLarge?.copyWith(fontSize: 22, fontWeight: FontWeight.w600),
    headlineMedium: text.headlineMedium?.copyWith(fontSize: 34, fontWeight: FontWeight.w700, fontFeatures: const [FontFeature.tabularFigures()]),
  );
  return base.copyWith(
    colorScheme: scheme,
    textTheme: tabular,
    extensions: [c],
    cardTheme: CardThemeData(color: c.surface, elevation: 0, margin: EdgeInsets.zero, shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(14), side: BorderSide(color: c.line))),
    dividerTheme: DividerThemeData(color: c.lineSoft, thickness: 1, space: 1),
    appBarTheme: AppBarTheme(backgroundColor: c.surface, foregroundColor: c.text, elevation: 0, surfaceTintColor: Colors.transparent, titleTextStyle: tabular.titleLarge),
    inputDecorationTheme: InputDecorationTheme(
      filled: true, fillColor: c.surface2, isDense: true,
      border: OutlineInputBorder(borderRadius: BorderRadius.circular(10), borderSide: BorderSide(color: c.line)),
      enabledBorder: OutlineInputBorder(borderRadius: BorderRadius.circular(10), borderSide: BorderSide(color: c.line)),
      focusedBorder: OutlineInputBorder(borderRadius: BorderRadius.circular(10), borderSide: BorderSide(color: c.accent, width: 1.5)),
      errorBorder: OutlineInputBorder(borderRadius: BorderRadius.circular(10), borderSide: BorderSide(color: c.down)),
      labelStyle: TextStyle(color: c.muted), hintStyle: TextStyle(color: c.faint),
    ),
    filledButtonTheme: FilledButtonThemeData(style: FilledButton.styleFrom(backgroundColor: c.accent, foregroundColor: Colors.white, shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(10)), padding: const EdgeInsets.symmetric(horizontal: 16, vertical: 12), textStyle: const TextStyle(fontWeight: FontWeight.w600))),
    outlinedButtonTheme: OutlinedButtonThemeData(style: OutlinedButton.styleFrom(foregroundColor: c.text, side: BorderSide(color: c.line), shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(10)), padding: const EdgeInsets.symmetric(horizontal: 14, vertical: 12))),
    textButtonTheme: TextButtonThemeData(style: TextButton.styleFrom(foregroundColor: c.link, shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(8)))),
    chipTheme: ChipThemeData(backgroundColor: c.surface2, selectedColor: c.accent.withValues(alpha: 0.18), side: BorderSide(color: c.line), labelStyle: TextStyle(color: c.text, fontSize: 12.5), shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(8)), padding: const EdgeInsets.symmetric(horizontal: 8, vertical: 4), showCheckmark: false),
    segmentedButtonTheme: SegmentedButtonThemeData(style: SegmentedButton.styleFrom(selectedBackgroundColor: c.accent.withValues(alpha: 0.2), selectedForegroundColor: c.text, foregroundColor: c.muted, side: BorderSide(color: c.line), textStyle: const TextStyle(fontSize: 12.5, fontWeight: FontWeight.w500), visualDensity: VisualDensity.compact)),
    navigationBarTheme: NavigationBarThemeData(backgroundColor: c.surface, indicatorColor: c.accent.withValues(alpha: 0.18), height: 68, labelTextStyle: WidgetStateProperty.resolveWith((s) => TextStyle(fontSize: 11.5, fontWeight: s.contains(WidgetState.selected) ? FontWeight.w700 : FontWeight.w500, color: s.contains(WidgetState.selected) ? c.text : c.muted)), iconTheme: WidgetStateProperty.resolveWith((s) => IconThemeData(color: s.contains(WidgetState.selected) ? c.link : c.muted, size: 24))),
    tabBarTheme: TabBarThemeData(labelColor: c.text, unselectedLabelColor: c.muted, indicatorColor: c.accent, dividerColor: c.lineSoft, labelStyle: const TextStyle(fontWeight: FontWeight.w600, fontSize: 13.5), unselectedLabelStyle: const TextStyle(fontSize: 13.5)),
    dialogTheme: DialogThemeData(backgroundColor: c.surface, shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(16))),
    bottomSheetTheme: BottomSheetThemeData(backgroundColor: c.surface, shape: const RoundedRectangleBorder(borderRadius: BorderRadius.vertical(top: Radius.circular(22))), showDragHandle: true),
    snackBarTheme: SnackBarThemeData(backgroundColor: b == Brightness.dark ? const Color(0xFF1E2A3A) : const Color(0xFF13213A), contentTextStyle: const TextStyle(color: Colors.white), behavior: SnackBarBehavior.floating, shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(10))),
    dataTableTheme: DataTableThemeData(headingTextStyle: TextStyle(color: c.faint, fontSize: 12, fontWeight: FontWeight.w500), dataTextStyle: TextStyle(color: c.text, fontSize: 13.5, fontFeatures: const [FontFeature.tabularFigures()]), dividerThickness: 1, headingRowHeight: 40, dataRowMinHeight: 40, dataRowMaxHeight: 44),
    switchTheme: SwitchThemeData(thumbColor: WidgetStateProperty.resolveWith((s) => s.contains(WidgetState.selected) ? Colors.white : c.muted), trackColor: WidgetStateProperty.resolveWith((s) => s.contains(WidgetState.selected) ? c.accent : c.surface2)),
    listTileTheme: ListTileThemeData(iconColor: c.muted, textColor: c.text),
    iconTheme: IconThemeData(color: c.muted, size: 22),
    dropdownMenuTheme: DropdownMenuThemeData(textStyle: TextStyle(color: c.text, fontSize: 13.5)),
    popupMenuTheme: PopupMenuThemeData(color: c.surface, shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(10), side: BorderSide(color: c.line))),
    progressIndicatorTheme: ProgressIndicatorThemeData(color: c.accent, linearTrackColor: c.surface2),
  );
}
