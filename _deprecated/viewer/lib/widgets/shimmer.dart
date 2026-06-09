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

/// One member-row placeholder: avatar + two text lines + a trailing status chip. Shared by the
/// list skeleton and the Golden-Hour per-unit grid skeleton so they stay visually identical.
class SkeletonMemberRow extends StatelessWidget {
  const SkeletonMemberRow({super.key});
  @override
  Widget build(BuildContext context) => const Padding(
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
        itemBuilder: (_, __) => const SkeletonMemberRow(),
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

/// A rounded, outlined placeholder shaped exactly like a [SectionCard] (same radius, border, margin
/// and padding) so KPI/Golden-Hour skeletons occupy the real card footprint — no layout jump when
/// the data arrives. (N8)
class _SkelCard extends StatelessWidget {
  const _SkelCard({required this.child});
  final Widget child;
  @override
  Widget build(BuildContext context) => Container(
        margin: const EdgeInsets.symmetric(vertical: 6),
        padding: const EdgeInsets.all(16),
        decoration: BoxDecoration(
          borderRadius: BorderRadius.circular(16),
          border: Border.all(color: Theme.of(context).colorScheme.outlineVariant),
        ),
        child: child,
      );
}

/// One Golden-Hour "completion" stat: big % + label + a progress bar — matches `_PctStat` (width 124).
class _SkelPctStat extends StatelessWidget {
  const _SkelPctStat();
  @override
  Widget build(BuildContext context) => const SizedBox(
        width: 124,
        child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
          SkeletonBox(width: 54, height: 22),
          SizedBox(height: 8),
          SkeletonLine(widthFactor: 0.85, height: 11),
          SizedBox(height: 8),
          SkeletonBox(width: 110, height: 5, radius: 4),
        ]),
      );
}

/// N8: content-shaped skeleton for the Golden-Hour tab — the section toggle, org filter chips and
/// window selector, the "Golden Hour completion" card (a wrap of % stats), then the per-unit grid.
/// Mirrors `_GoldenHourView` so nothing shifts when the data lands.
class GoldenHourSkeleton extends StatelessWidget {
  const GoldenHourSkeleton({super.key});
  @override
  Widget build(BuildContext context) {
    return Shimmer(
      child: ListView(
        padding: const EdgeInsets.fromLTRB(14, 16, 14, 96),
        children: [
          // New Members / Being Taught segmented toggle
          const Center(child: SkeletonBox(width: 300, height: 38, radius: 19)),
          const SizedBox(height: AppSpacing.md),
          // org filter chips (WML / EQ / RS)
          const Center(
            child: Wrap(spacing: 6, children: [
              SkeletonBox(width: 64, height: 32, radius: 16),
              SkeletonBox(width: 56, height: 32, radius: 16),
              SkeletonBox(width: 56, height: 32, radius: 16),
            ]),
          ),
          const SizedBox(height: AppSpacing.md),
          // Week / Month / Year / All window selector
          const Center(child: SkeletonBox(width: 260, height: 36, radius: 18)),
          const SizedBox(height: AppSpacing.md),
          // section title + sort/view controls
          const Row(mainAxisAlignment: MainAxisAlignment.spaceBetween, children: [
            SkeletonBox(width: 170, height: 20),
            SkeletonBox(width: 120, height: 30, radius: 15),
          ]),
          const SizedBox(height: AppSpacing.sm),
          // "Golden Hour completion" card — a wrap of % stats
          _SkelCard(
            child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
              const SkeletonBox(width: 190, height: 18),
              const SizedBox(height: 16),
              Wrap(spacing: 18, runSpacing: 12, children: [
                for (var i = 0; i < 6; i++) const _SkelPctStat(),
              ]),
            ]),
          ),
          const SizedBox(height: AppSpacing.md),
          // per-unit grid: unit header + member rows
          for (var u = 0; u < 2; u++) ...[
            const SkeletonBox(width: 140, height: 16),
            const SizedBox(height: AppSpacing.md),
            for (var i = 0; i < 3; i++) const SkeletonMemberRow(),
            const SizedBox(height: AppSpacing.md),
          ],
        ],
      ),
    );
  }
}

/// Two stacked label/number blocks side by side — matches the KPI cards' big-stat pair.
class _SkelStat extends StatelessWidget {
  const _SkelStat();
  @override
  Widget build(BuildContext context) => const Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          SkeletonLine(widthFactor: 0.6, height: 11),
          SizedBox(height: 6),
          SkeletonBox(width: 50, height: 24),
        ],
      );
}

/// A KPI chart card placeholder: icon + title, an optional window selector (Baptisms), the two big
/// stats, the 170-px chart area, and a caption line — shaped like `_BaptismsCard`/`_MetricChartCard`.
class _SkelChartCard extends StatelessWidget {
  const _SkelChartCard({this.withWindowSelector = false});
  final bool withWindowSelector;
  @override
  Widget build(BuildContext context) {
    return _SkelCard(
      child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
        const Row(children: [
          SkeletonBox(width: 32, height: 32, radius: 10),
          SizedBox(width: 10),
          SkeletonBox(width: 150, height: 18),
        ]),
        const SizedBox(height: 14),
        if (withWindowSelector) ...const [
          Center(child: SkeletonBox(width: 260, height: 34, radius: 17)),
          SizedBox(height: 14),
        ],
        const Row(children: [
          Expanded(child: _SkelStat()),
          SizedBox(width: 28),
          Expanded(child: _SkelStat()),
        ]),
        const SizedBox(height: 16),
        const SkeletonBox(width: double.infinity, height: 170, radius: 12),
        const SizedBox(height: 12),
        const SkeletonLine(widthFactor: 0.7, height: 11),
      ]),
    );
  }
}

/// One "Overview" stat (width 124): big number + label — matches `_StatGridCard`'s cells.
class _SkelOverviewStat extends StatelessWidget {
  const _SkelOverviewStat();
  @override
  Widget build(BuildContext context) => const SizedBox(
        width: 124,
        child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
          SkeletonBox(width: 46, height: 26),
          SizedBox(height: 8),
          SkeletonLine(widthFactor: 0.8, height: 11),
        ]),
      );
}

/// N8: content-shaped skeleton for the KPIs tab — the big header + period selector, two chart cards
/// (the first with the Baptisms window selector) and the "Overview" stat grid. Mirrors `_KpiView`.
class KpiSkeleton extends StatelessWidget {
  const KpiSkeleton({super.key});
  @override
  Widget build(BuildContext context) {
    return Shimmer(
      child: ListView(
        padding: const EdgeInsets.fromLTRB(14, 16, 14, 96),
        children: [
          // big header: accent bar + title + subtitle
          const Row(crossAxisAlignment: CrossAxisAlignment.start, children: [
            SkeletonBox(width: 4, height: 34, radius: 2),
            SizedBox(width: 10),
            Expanded(
              child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
                SkeletonBox(width: 90, height: 24),
                SizedBox(height: 8),
                SkeletonLine(widthFactor: 0.65, height: 12),
              ]),
            ),
          ]),
          const SizedBox(height: 14),
          // Month / Year / All period selector
          const Center(child: SkeletonBox(width: 220, height: 36, radius: 18)),
          const SizedBox(height: 14),
          // Baptisms card (with its own window selector) + a metric chart card
          const _SkelChartCard(withWindowSelector: true),
          const _SkelChartCard(),
          // "Overview" stat grid
          _SkelCard(
            child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
              const SkeletonBox(width: 110, height: 18),
              const SizedBox(height: 16),
              Wrap(spacing: 24, runSpacing: 16, children: [
                for (var i = 0; i < 4; i++) const _SkelOverviewStat(),
              ]),
            ]),
          ),
        ],
      ),
    );
  }
}
