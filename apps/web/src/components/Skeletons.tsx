// Content-shaped loading skeletons (replace spinners for content loads) so the layout doesn't jump
// when data arrives. Mirrors apps/viewer/lib/widgets/shimmer.dart (the shimmer sheen is CSS,
// .skeleton in components.css).

export function SkeletonBox({ width, height = 14, radius = 6 }: { width?: number | string; height?: number; radius?: number }) {
  return <span className="skeleton" style={{ display: 'block', width: width ?? '100%', height, borderRadius: radius }} />;
}

export function SkeletonLine({ widthFactor = 1, height = 12 }: { widthFactor?: number; height?: number }) {
  return <SkeletonBox width={`${Math.min(1, Math.max(0, widthFactor)) * 100}%`} height={height} />;
}

/** Skeleton for the dashboard member/list views: avatar + two-line rows. */
export function MemberListSkeleton({ rows = 8 }: { rows?: number }) {
  return (
    <div style={{ padding: 16 }} aria-hidden="true">
      {Array.from({ length: rows }, (_, i) => (
        <div key={i} className="row" style={{ marginBottom: 12, alignItems: 'center' }}>
          <SkeletonBox width={44} height={44} radius={22} />
          <div style={{ flex: 1 }}>
            <SkeletonLine widthFactor={0.5} height={13} />
            <div style={{ height: 8 }} />
            <SkeletonLine widthFactor={0.3} height={11} />
          </div>
          <SkeletonBox width={52} height={22} radius={20} />
        </div>
      ))}
    </div>
  );
}

/** Skeleton for the Sync-settings sheet: title + label/value rows + a button block. */
export function SyncSettingsSkeleton({ rows = 5 }: { rows?: number }) {
  return (
    <div className="stack" style={{ gap: 4, paddingBottom: 16 }} aria-hidden="true">
      <SkeletonBox width={160} height={22} />
      <div style={{ height: 16 }} />
      {Array.from({ length: rows }, (_, i) => (
        <div key={i} className="row" style={{ padding: '8px 0' }}>
          <div style={{ width: 110 }}>
            <SkeletonLine widthFactor={0.7} height={12} />
          </div>
          <div style={{ flex: 1 }}>
            <SkeletonLine widthFactor={0.6} height={12} />
          </div>
        </div>
      ))}
      <div style={{ height: 16 }} />
      <SkeletonBox height={44} radius={8} />
    </div>
  );
}

/** Generic skeleton of a few text lines for detail/secondary panels (comments, etc.). */
export function CardSkeleton({ lines = 3 }: { lines?: number }) {
  return (
    <div className="stack" style={{ gap: 8 }} aria-hidden="true">
      {Array.from({ length: lines }, (_, i) => (
        <SkeletonLine key={i} widthFactor={i % 2 === 0 ? 0.9 : 0.6} />
      ))}
    </div>
  );
}
