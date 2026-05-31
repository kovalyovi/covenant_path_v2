import 'package:flutter/material.dart';

import '../theme/tokens.dart';

/// Content-shaped loading skeletons (replace spinners for content loads). A sheen sweeps across
/// grey placeholder blocks shaped like the real content, so the layout doesn't jump when data
/// arrives — the skeleton already occupies the final shape. Hand-rolled (no package) to keep the
/// one Flutter codebase dependency-light.
///
/// Wrap any tree of [SkeletonBox]/[SkeletonLine] in a [Shimmer], or use the ready-made
/// [MemberListSkeleton] / [SyncSettingsSkeleton] / [CardSkeleton] for the common views.
class Shimmer extends StatefulWidget {
  const Shimmer({super.key, required this.child});
  final Widget child;

  @override
  State<Shimmer> createState() => _ShimmerState();
}

class _ShimmerState extends State<Shimmer> with SingleTickerProviderStateMixin {
  late final AnimationController _c =
      AnimationController(vsync: this, duration: const Duration(milliseconds: 1400))..repeat();

  @override
  void dispose() {
    _c.dispose();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) {
    final cs = Theme.of(context).colorScheme;
    final base = cs.surfaceContainerHighest;
    final highlight = Color.alphaBlend(cs.onSurface.withValues(alpha: 0.08), base);
    return AnimatedBuilder(
      animation: _c,
      builder: (context, child) => ShaderMask(
        blendMode: BlendMode.srcATop,
        shaderCallback: (bounds) {
          final slide = (2 * _c.value - 1) * bounds.width; // sweep -w → +w
          return LinearGradient(
            begin: Alignment.centerLeft,
            end: Alignment.centerRight,
            colors: [base, highlight, base],
            stops: const [0.25, 0.5, 0.75],
            transform: _GradientSlide(slide),
          ).createShader(bounds);
        },
        child: child,
      ),
      child: widget.child,
    );
  }
}

/// Slides the gradient horizontally so the sheen sweeps across the whole skeleton tree.
class _GradientSlide extends GradientTransform {
  const _GradientSlide(this.dx);
  final double dx;
  @override
  Matrix4? transform(Rect bounds, {TextDirection? textDirection}) =>
      Matrix4.translationValues(dx, 0, 0);
}

/// A single rounded grey block. The [Shimmer] paints the moving sheen over it; here we just lay out
/// the shape (a solid fill the ShaderMask can mask).
class SkeletonBox extends StatelessWidget {
  const SkeletonBox({super.key, this.width, this.height = 14, this.radius = 6});
  final double? width;
  final double height;
  final double radius;
  @override
  Widget build(BuildContext context) => Container(
        width: width,
        height: height,
        decoration: BoxDecoration(
          color: Theme.of(context).colorScheme.surfaceContainerHighest,
          borderRadius: BorderRadius.circular(radius),
        ),
      );
}

/// A text-line placeholder spanning [widthFactor] (0..1) of the available width.
class SkeletonLine extends StatelessWidget {
  const SkeletonLine({super.key, this.widthFactor = 1.0, this.height = 12});
  final double widthFactor;
  final double height;
  @override
  Widget build(BuildContext context) => Align(
        alignment: Alignment.centerLeft,
        child: FractionallySizedBox(
          alignment: Alignment.centerLeft,
          widthFactor: widthFactor.clamp(0.0, 1.0),
          child: SkeletonBox(height: height),
        ),
      );
}

/// Skeleton for the dashboard member/list views: avatar + two-line rows.
class MemberListSkeleton extends StatelessWidget {
  const MemberListSkeleton({super.key, this.rows = 8});
  final int rows;
  @override
  Widget build(BuildContext context) {
    return Shimmer(
      child: ListView.builder(
        padding: const EdgeInsets.fromLTRB(
            AppSpacing.lg, AppSpacing.lg, AppSpacing.lg, AppSpacing.xxl),
        itemCount: rows,
        itemBuilder: (_, __) => const Padding(
          padding: EdgeInsets.only(bottom: AppSpacing.md),
          child: Row(children: [
            SkeletonBox(width: 44, height: 44, radius: 22),
            SizedBox(width: AppSpacing.md),
            Expanded(
              child: Column(
                crossAxisAlignment: CrossAxisAlignment.start,
                children: [
                  SkeletonLine(widthFactor: 0.5, height: 13),
                  SizedBox(height: AppSpacing.sm),
                  SkeletonLine(widthFactor: 0.3, height: 11),
                ],
              ),
            ),
            SizedBox(width: AppSpacing.md),
            SkeletonBox(width: 52, height: 22, radius: 20),
          ]),
        ),
      ),
    );
  }
}

/// Skeleton for the Sync-settings sheet: title + label/value rows + a button block. Shown the
/// instant the sheet opens so it never jumps from blank → content.
class SyncSettingsSkeleton extends StatelessWidget {
  const SyncSettingsSkeleton({super.key, this.rows = 5});
  final int rows;
  @override
  Widget build(BuildContext context) {
    return Shimmer(
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        mainAxisSize: MainAxisSize.min,
        children: [
          const SkeletonBox(width: 160, height: 22),
          const SizedBox(height: AppSpacing.lg),
          for (var i = 0; i < rows; i++)
            const Padding(
              padding: EdgeInsets.symmetric(vertical: AppSpacing.sm),
              child: Row(children: [
                SizedBox(width: 110, child: SkeletonLine(widthFactor: 0.7, height: 12)),
                SizedBox(width: AppSpacing.md),
                Expanded(child: SkeletonLine(widthFactor: 0.6, height: 12)),
              ]),
            ),
          const SizedBox(height: AppSpacing.lg),
          const SkeletonBox(width: double.infinity, height: 44, radius: 8),
        ],
      ),
    );
  }
}

/// Generic skeleton of a few text lines for detail/secondary panels (comments, etc.).
class CardSkeleton extends StatelessWidget {
  const CardSkeleton({super.key, this.lines = 3});
  final int lines;
  @override
  Widget build(BuildContext context) {
    return Shimmer(
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        mainAxisSize: MainAxisSize.min,
        children: [
          for (var i = 0; i < lines; i++)
            Padding(
              padding: const EdgeInsets.symmetric(vertical: AppSpacing.xs),
              child: SkeletonLine(widthFactor: i.isEven ? 0.9 : 0.6),
            ),
        ],
      ),
    );
  }
}
