import 'package:flutter/material.dart';
import 'package:flutter_animate/flutter_animate.dart';

import '../../core/responsive.dart';
import '../../core/theme.dart';

/// Bordered card (no shadow, spec 7).
class AppCard extends StatelessWidget {
  final Widget child;
  final EdgeInsets? padding;
  final Color? color;
  final Color? borderColor;
  final VoidCallback? onTap;
  final bool dashed;
  const AppCard({super.key, required this.child, this.padding, this.color, this.borderColor, this.onTap, this.dashed = false});

  @override
  Widget build(BuildContext context) {
    final c = context.vn;
    final r = context.isPhone ? 16.0 : 14.0;
    final box = Container(
      decoration: BoxDecoration(color: color ?? c.surface, borderRadius: BorderRadius.circular(r), border: Border.all(color: borderColor ?? c.line, width: dashed ? 1.5 : 1)),
      child: Material(type: MaterialType.transparency, child: Padding(padding: padding ?? const EdgeInsets.all(16), child: child)),
    );
    if (onTap == null) return box;
    return Material(color: Colors.transparent, child: InkWell(borderRadius: BorderRadius.circular(r), onTap: onTap, child: box));
  }
}

class SectionHeader extends StatelessWidget {
  final String title;
  final String? subtitle;
  final Widget? trailing;
  final EdgeInsets padding;
  const SectionHeader(this.title, {super.key, this.subtitle, this.trailing, this.padding = const EdgeInsets.only(bottom: 10)});
  @override
  Widget build(BuildContext context) => Padding(
        padding: padding,
        child: Row(children: [
          Expanded(child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
            Text(title, style: Theme.of(context).textTheme.titleMedium),
            if (subtitle != null) Padding(padding: const EdgeInsets.only(top: 2), child: Text(subtitle!, style: Theme.of(context).textTheme.bodySmall)),
          ])),
          if (trailing != null) trailing!,
        ]),
      );
}

class EmptyState extends StatelessWidget {
  final IconData icon;
  final String message;
  final String? actionLabel;
  final VoidCallback? onAction;
  const EmptyState({super.key, this.icon = Icons.inbox_outlined, required this.message, this.actionLabel, this.onAction});
  @override
  Widget build(BuildContext context) => Center(
        child: Padding(
          padding: const EdgeInsets.all(28),
          child: Column(mainAxisSize: MainAxisSize.min, children: [
            Icon(icon, size: 40, color: context.vn.faint),
            const SizedBox(height: 12),
            Text(message, textAlign: TextAlign.center, style: TextStyle(color: context.vn.muted)),
            if (actionLabel != null) ...[const SizedBox(height: 14), FilledButton(onPressed: onAction, child: Text(actionLabel!))],
          ]),
        ),
      ).animate().fadeIn(duration: 250.ms);
}

class ErrorBox extends StatelessWidget {
  final Object error;
  final VoidCallback? onRetry;
  const ErrorBox(this.error, {super.key, this.onRetry});
  @override
  Widget build(BuildContext context) => AppCard(
        child: Row(children: [
          Icon(Icons.error_outline, color: context.vn.down),
          const SizedBox(width: 10),
          Expanded(child: Text(error.toString(), style: TextStyle(color: context.vn.text))),
          if (onRetry != null) TextButton(onPressed: onRetry, child: const Text('Thử lại')),
        ]),
      );
}

/// Shimmer skeleton block.
class Skeleton extends StatelessWidget {
  final double height;
  final double? width;
  final double radius;
  const Skeleton({super.key, this.height = 16, this.width, this.radius = 8});
  @override
  Widget build(BuildContext context) {
    final c = context.vn;
    return Container(height: height, width: width, decoration: BoxDecoration(color: c.surface2, borderRadius: BorderRadius.circular(radius)))
        .animate(onPlay: (ctl) => context.reduceMotion ? null : ctl.repeat())
        .shimmer(duration: 1400.ms, color: c.line.withValues(alpha: 0.6));
  }
}

class SkeletonCard extends StatelessWidget {
  final int lines;
  const SkeletonCard({super.key, this.lines = 3});
  @override
  Widget build(BuildContext context) => AppCard(
        child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
          const Skeleton(height: 18, width: 160),
          const SizedBox(height: 12),
          for (var i = 0; i < lines; i++) ...[Skeleton(width: i.isEven ? double.infinity : 220), const SizedBox(height: 8)],
        ]),
      );
}

class SkeletonList extends StatelessWidget {
  final int count;
  const SkeletonList({super.key, this.count = 4});
  @override
  Widget build(BuildContext context) => SingleChildScrollView(physics: const NeverScrollableScrollPhysics(), child: Column(children: [for (var i = 0; i < count; i++) Padding(padding: const EdgeInsets.only(bottom: 12), child: SkeletonCard(lines: 2))]));
}

/// Small rounded label.
class Pill extends StatelessWidget {
  final String text;
  final Color color;
  final Color? bg;
  final bool dashed;
  final IconData? icon;
  final double fontSize;
  const Pill(this.text, {super.key, required this.color, this.bg, this.dashed = false, this.icon, this.fontSize = 12});
  @override
  Widget build(BuildContext context) => Container(
        padding: const EdgeInsets.symmetric(horizontal: 8, vertical: 3),
        decoration: BoxDecoration(color: bg ?? color.withValues(alpha: 0.16), borderRadius: BorderRadius.circular(6), border: dashed ? Border.all(color: color, width: 1) : null),
        child: Row(mainAxisSize: MainAxisSize.min, children: [
          if (icon != null) ...[Icon(icon, size: 13, color: color), const SizedBox(width: 4)],
          Text(text, style: TextStyle(color: color, fontSize: fontSize, fontWeight: FontWeight.w700)),
        ]),
      );
}

/// Animated number for KPI tiles.
class AnimatedCounter extends StatelessWidget {
  final num value;
  final String Function(num) format;
  final TextStyle? style;
  const AnimatedCounter({super.key, required this.value, required this.format, this.style});
  @override
  Widget build(BuildContext context) => TweenAnimationBuilder<double>(
        tween: Tween(begin: 0, end: value.toDouble()),
        duration: context.reduceMotion ? Duration.zero : 700.ms,
        curve: Curves.easeOutCubic,
        builder: (_, v, __) => Text(format(v), style: style),
      );
}

class KpiTile extends StatelessWidget {
  final String label;
  final String value;
  final String? note;
  final Color? valueColor;
  final num? animateFrom;
  final String Function(num)? format;
  final Widget? child;
  const KpiTile({super.key, required this.label, required this.value, this.note, this.valueColor, this.animateFrom, this.format, this.child});
  @override
  Widget build(BuildContext context) {
    final c = context.vn;
    final style = TextStyle(fontSize: 20, fontWeight: FontWeight.w700, color: valueColor ?? c.text, fontFeatures: const [FontFeature.tabularFigures()]);
    return AppCard(
      padding: const EdgeInsets.all(14),
      child: Column(crossAxisAlignment: CrossAxisAlignment.start, mainAxisSize: MainAxisSize.min, children: [
        Text(label, style: TextStyle(color: c.faint, fontSize: 12)),
        const SizedBox(height: 6),
        animateFrom != null && format != null ? AnimatedCounter(value: animateFrom!, format: format!, style: style) : Text(value, style: style),
        if (note != null) Padding(padding: const EdgeInsets.only(top: 4), child: Text(note!, style: TextStyle(color: c.muted, fontSize: 12))),
        if (child != null) Padding(padding: const EdgeInsets.only(top: 8), child: child),
      ]),
    );
  }
}

void showToast(BuildContext context, String message, {bool error = false, String? actionLabel, VoidCallback? onAction}) {
  final m = ScaffoldMessenger.maybeOf(context);
  if (m == null) return;
  m.hideCurrentSnackBar();
  m.showSnackBar(SnackBar(
    content: Row(children: [Icon(error ? Icons.error_outline : Icons.check_circle_outline, color: error ? const Color(0xFFFF8A8F) : const Color(0xFF5FD896), size: 20), const SizedBox(width: 10), Expanded(child: Text(message))]),
    duration: const Duration(seconds: 4),
    action: actionLabel != null ? SnackBarAction(label: actionLabel, textColor: const Color(0xFF9CC2FF), onPressed: onAction ?? () {}) : null,
  ));
}

Future<bool> confirmDialog(BuildContext context, {required String title, required String message, String confirmLabel = 'Xác nhận', bool danger = false}) async {
  final c = context.vn;
  final r = await showDialog<bool>(
    context: context,
    builder: (ctx) => AlertDialog(
      title: Text(title),
      content: Text(message),
      actions: [
        TextButton(onPressed: () => Navigator.pop(ctx, false), child: const Text('Hủy')),
        FilledButton(style: danger ? FilledButton.styleFrom(backgroundColor: c.down) : null, onPressed: () => Navigator.pop(ctx, true), child: Text(confirmLabel)),
      ],
    ),
  );
  return r ?? false;
}

/// Section-level banner (yellow for connection / data staleness).
class InfoBanner extends StatelessWidget {
  final String text;
  final Color color;
  final IconData icon;
  final Widget? trailing;
  const InfoBanner(this.text, {super.key, required this.color, this.icon = Icons.info_outline, this.trailing});
  @override
  Widget build(BuildContext context) => Container(
        width: double.infinity,
        padding: const EdgeInsets.symmetric(horizontal: 14, vertical: 8),
        color: color.withValues(alpha: 0.18),
        child: Row(children: [Icon(icon, size: 16, color: color), const SizedBox(width: 8), Expanded(child: Text(text, style: TextStyle(color: color, fontSize: 12.5, fontWeight: FontWeight.w600))), if (trailing != null) trailing!]),
      );
}

/// Shown on every screen when the loss circuit breaker is active (spec: no close button).
class DefensiveBanner extends StatelessWidget {
  final String? releaseAt;
  final String? reason;
  final VoidCallback? onWhy;
  const DefensiveBanner({super.key, this.releaseAt, this.reason, this.onWhy});
  @override
  Widget build(BuildContext context) {
    final c = context.vn;
    return InfoBanner('Chế độ phòng thủ${releaseAt != null ? ' đến $releaseAt' : ''}. Không có gợi ý mua mới.', color: c.down, icon: Icons.shield_outlined,
        trailing: TextButton(onPressed: onWhy, child: Text('Xem lý do', style: TextStyle(color: c.downText, fontSize: 12.5))));
  }
}

/// Purple-outlined Ask-AI button.
class AskAiButton extends StatelessWidget {
  final String label;
  final VoidCallback onPressed;
  final bool compact;
  const AskAiButton({super.key, this.label = 'Hỏi AI', required this.onPressed, this.compact = false});
  @override
  Widget build(BuildContext context) {
    final c = context.vn;
    if (compact) return IconButton(onPressed: onPressed, tooltip: label, icon: Icon(Icons.auto_awesome, color: c.ai));
    return OutlinedButton.icon(
      onPressed: onPressed,
      style: OutlinedButton.styleFrom(foregroundColor: c.ai, side: BorderSide(color: c.ai), padding: const EdgeInsets.symmetric(horizontal: 12, vertical: 10)),
      icon: const Icon(Icons.auto_awesome, size: 16),
      label: Text(label, style: const TextStyle(fontWeight: FontWeight.w600, fontSize: 13)),
    );
  }
}

/// Progress bar to a limit: <50% grey, 50–80% orange, >80% red.
class LimitBar extends StatelessWidget {
  final String label;
  final double value;
  final double limit;
  final String valueText;
  const LimitBar({super.key, required this.label, required this.value, required this.limit, required this.valueText});
  @override
  Widget build(BuildContext context) {
    final c = context.vn;
    final ratio = limit == 0 ? 0.0 : (value.abs() / limit).clamp(0.0, 1.0);
    final color = ratio > 0.8 ? c.down : (ratio >= 0.5 ? const Color(0xFFF08A3D) : c.muted);
    return Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
      Row(children: [Expanded(child: Text(label, style: TextStyle(color: c.muted, fontSize: 12.5))), Text(valueText, style: TextStyle(color: color, fontSize: 12.5, fontWeight: FontWeight.w600))]),
      const SizedBox(height: 6),
      ClipRRect(borderRadius: BorderRadius.circular(4), child: TweenAnimationBuilder<double>(tween: Tween(begin: 0, end: ratio), duration: 600.ms, builder: (_, v, __) => LinearProgressIndicator(value: v, minHeight: 6, color: color, backgroundColor: c.surface2))),
    ]);
  }
}

class LabeledValue extends StatelessWidget {
  final String label;
  final String value;
  final Color? color;
  final bool big;
  const LabeledValue(this.label, this.value, {super.key, this.color, this.big = false});
  @override
  Widget build(BuildContext context) => Column(crossAxisAlignment: CrossAxisAlignment.start, mainAxisSize: MainAxisSize.min, children: [
        Text(label, style: TextStyle(color: context.vn.faint, fontSize: 11.5)),
        const SizedBox(height: 2),
        Text(value, style: TextStyle(color: color ?? context.vn.text, fontSize: big ? 16 : 13.5, fontWeight: FontWeight.w600, fontFeatures: const [FontFeature.tabularFigures()])),
      ]);
}

/// Staggered entrance for list children.
extension StaggerX on Widget {
  Widget stagger(BuildContext context, int index, {int step = 40}) => context.reduceMotion ? this : animate(delay: (index * step).ms).fadeIn(duration: 260.ms).slideY(begin: 0.06, end: 0, curve: Curves.easeOutCubic);
}

class DisclaimerText extends StatelessWidget {
  const DisclaimerText({super.key});
  @override
  Widget build(BuildContext context) => Padding(
        padding: const EdgeInsets.symmetric(vertical: 10),
        child: Text('Thông tin chỉ mang tính tham khảo, không phải lời khuyên mua bán. Bạn tự chịu trách nhiệm với quyết định đầu tư.', style: TextStyle(color: context.vn.faint, fontSize: 11.5)),
      );
}

class Segmented<T> extends StatelessWidget {
  final List<(T, String)> options;
  final T value;
  final ValueChanged<T> onChanged;
  const Segmented({super.key, required this.options, required this.value, required this.onChanged});
  @override
  Widget build(BuildContext context) => SingleChildScrollView(
        scrollDirection: Axis.horizontal,
        physics: const ClampingScrollPhysics(),
        child: SegmentedButton<T>(
          segments: [for (final o in options) ButtonSegment(value: o.$1, label: Text(o.$2))],
          selected: {value},
          onSelectionChanged: (s) => onChanged(s.first),
          showSelectedIcon: false,
        ),
      );
}
