import 'package:flutter/material.dart';
import 'package:flutter_svg/flutter_svg.dart';

/// Vinatrade visual identity v1.0 (assets/brand, guidelines in docs/vinatrade-brand-guidelines.txt).
/// Mark = blue "rising line × V". Never tint the mark red/green with the market.
class BrandMark extends StatelessWidget {
  final double size;
  final bool light;
  const BrandMark({super.key, this.size = 28, this.light = false});
  @override
  Widget build(BuildContext context) => SvgPicture.asset(
        light ? 'assets/brand/logo/vinatrade-mark-light.svg' : 'assets/brand/logo/vinatrade-mark.svg',
        width: size,
        height: size,
        semanticsLabel: 'Vinatrade',
      );
}

/// Horizontal lockup (mark + wordmark). Light wordmark on dark surfaces, dark wordmark on light surfaces.
/// Minimum width 144 px — below that use [BrandMark] alone.
class BrandLockup extends StatelessWidget {
  final double height;
  final bool onLight;
  const BrandLockup({super.key, this.height = 28, this.onLight = false});
  @override
  Widget build(BuildContext context) {
    final light = onLight || Theme.of(context).brightness == Brightness.light;
    return SvgPicture.asset(
      light ? 'assets/brand/logo/vinatrade-lockup-dark.svg' : 'assets/brand/logo/vinatrade-lockup.svg',
      height: height,
      semanticsLabel: 'Vinatrade',
    );
  }
}

/// 24 px line icons (1.8 px stroke). Tinted with [color] so active/inactive/light-theme states work.
enum BrandIcons {
  market, analysis, watchlist, portfolio, screener, alerts, account, admin, askAi, preTradeCheck, lossGuard, actionItems,
  ifThenPlan, insiderTrading, foreignFlow, corporateEvents, news, stopLoss, takeProfit;

  String get asset => 'assets/brand/icons/${name.replaceAllMapped(RegExp(r'[A-Z]'), (m) => '-${m[0]!.toLowerCase()}')}.svg';
}

class BrandIcon extends StatelessWidget {
  final BrandIcons icon;
  final double size;
  final Color? color;
  const BrandIcon(this.icon, {super.key, this.size = 22, this.color});
  @override
  Widget build(BuildContext context) {
    final c = color ?? IconTheme.of(context).color ?? Theme.of(context).colorScheme.onSurface;
    return SvgPicture.asset(icon.asset, width: size, height: size, colorFilter: ColorFilter.mode(c, BlendMode.srcIn));
  }
}

/// Text-free 360×280 illustrations for empty states.
enum EmptyArt {
  watchlist, portfolio, alerts;

  String get asset => 'assets/brand/empty/$name.svg';
}

class EmptyIllustration extends StatelessWidget {
  final EmptyArt art;
  final double width;
  const EmptyIllustration(this.art, {super.key, this.width = 220});
  @override
  Widget build(BuildContext context) => SvgPicture.asset(art.asset, width: width, height: width * 280 / 360);
}
