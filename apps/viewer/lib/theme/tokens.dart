import 'package:flutter/material.dart';

/// Design tokens — the single source of spacing, radii, and semantic colors so views compose
/// from a shared vocabulary instead of re-inlining magic numbers and `Colors.green.shade600`.
/// Part of the #67 style-system work: change a token here and every view follows.

/// Consistent spacing scale (logical pixels). Use instead of bare SizedBox/EdgeInsets numbers.
abstract final class AppSpacing {
  static const double xs = 4;
  static const double sm = 8;
  static const double md = 12;
  static const double lg = 16;
  static const double xl = 24;
  static const double xxl = 32;

  static const EdgeInsets cardPadding = EdgeInsets.all(14);
  static const EdgeInsets pagePadding = EdgeInsets.all(lg);
  static const SizedBox gapXs = SizedBox(height: xs, width: xs);
  static const SizedBox gapSm = SizedBox(height: sm, width: sm);
  static const SizedBox gapMd = SizedBox(height: md, width: md);
  static const SizedBox gapLg = SizedBox(height: lg, width: lg);
}

abstract final class AppRadius {
  static const Radius sm = Radius.circular(4);
  static const Radius md = Radius.circular(8);
  static const Radius lg = Radius.circular(12);
  static const Radius pill = Radius.circular(20);
  static const BorderRadius cardBorder = BorderRadius.all(md);
  static const BorderRadius pillBorder = BorderRadius.all(pill);
}

/// Semantic status colors — meaning-named (not hue-named) so status chrome stays consistent and
/// a future palette change is one edit. Mid-shades read acceptably on both light and dark surfaces.
abstract final class AppColors {
  static const Color success = Color(0xFF2E7D32); // green 800
  static const Color successFg = Color(0xFF43A047); // green 600 (icons/borders)
  static const Color warning = Color(0xFFEF6C00); // orange 800
  static const Color info = Color(0xFF1E88E5); // blue 600
  static const Color danger = Color(0xFFE53935); // red 600
  static const Color neutral = Color(0xFF616161); // grey 700

  /// A soft tinted background for a status pill/tag of [c].
  static Color tint(Color c) => c.withValues(alpha: 0.12);
}
