import 'package:flutter/material.dart';

/// Breakpoints (UI spec 7): <600 phone, 600–1023 tablet, ≥1024 desktop, ≥1440 wide.
enum Layout { phone, tablet, desktop, wide }

Layout layoutOf(BuildContext context) {
  final w = MediaQuery.sizeOf(context).width;
  if (w < 600) return Layout.phone;
  if (w < 1024) return Layout.tablet;
  if (w < 1440) return Layout.desktop;
  return Layout.wide;
}

extension LayoutX on BuildContext {
  Layout get layout => layoutOf(this);
  bool get isPhone => layout == Layout.phone;
  bool get isDesktop => layout == Layout.desktop || layout == Layout.wide;
  bool get isWide => layout == Layout.wide;
  double get pagePadding => isPhone ? 16 : (layout == Layout.tablet ? 24 : 44);
  double get gap => isPhone ? 12 : 16;
  bool get reduceMotion => MediaQuery.of(this).disableAnimations;
}

/// Max content width for reading comfort on wide screens.
class PageBody extends StatelessWidget {
  final Widget child;
  final double maxWidth;
  final EdgeInsets? padding;
  const PageBody({super.key, required this.child, this.maxWidth = 1360, this.padding});
  @override
  Widget build(BuildContext context) => Align(
        alignment: Alignment.topCenter,
        child: ConstrainedBox(constraints: BoxConstraints(maxWidth: maxWidth), child: Padding(padding: padding ?? EdgeInsets.symmetric(horizontal: context.pagePadding, vertical: context.gap), child: child)),
      );
}
