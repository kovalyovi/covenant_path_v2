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

/** Member-row glimmer — mirrors the real `.member-row` (`MemberRow`): avatar + name on the top line,
 *  a metadata line, and (optionally) the Golden-Hour chip strip. Reuses the real classes so the row
 *  geometry is identical and real rows swap in without a jump. Used by the Needs/Leadership lists. */
export function MemberRowSkeleton({ rows = 8, chips = false }: { rows?: number; chips?: boolean }) {
  return (
    <div aria-hidden="true">
      {Array.from({ length: rows }, (_, i) => (
        <div key={i} className="member-row" style={{ pointerEvents: 'none', cursor: 'default' }}>
          <span className="member-row__top">
            <SkeletonBox width={44} height={44} radius={22} />
            <span className="member-row__name">
              <SkeletonBox width={150} height={14} />
            </span>
          </span>
          <span className="member-row__body">
            <span className="member-row__meta">
              <SkeletonBox width={190} height={11} />
            </span>
            {chips && (
              <span className="row" style={{ gap: 6, marginTop: 8, flexWrap: 'wrap' }}>
                {Array.from({ length: 6 }, (_, j) => (
                  <SkeletonBox key={j} width={22} height={22} radius={11} />
                ))}
              </span>
            )}
          </span>
        </div>
      ))}
    </div>
  );
}

/** A section-card-shaped glimmer: the real `.card` > `.card__body` > `.section-card__head` (icon +
 *  title) + a few body lines — the shared shape every `SectionCard` uses, so margins/chrome match. */
export function SectionCardSkeleton({ lines = 3, titleWidth = 130 }: { lines?: number; titleWidth?: number }) {
  return (
    <div className="card" aria-hidden="true">
      <div className="card__body">
        <div className="section-card__head">
          <SkeletonBox width={26} height={26} radius={8} />
          <span className="section-card__title">
            <SkeletonBox width={titleWidth} height={16} />
          </span>
        </div>
        <div className="stack" style={{ gap: 8 }}>
          {Array.from({ length: lines }, (_, i) => (
            <SkeletonLine key={i} widthFactor={i % 2 ? 0.6 : 0.9} />
          ))}
        </div>
      </div>
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

/** #16: small placeholder for the sync-settings schedule / Drive sub-sections while they load, so
 *  they fade in as a skeleton instead of abruptly appearing once their broker call resolves. */
export function SubsectionSkeleton() {
  return (
    <div aria-hidden="true">
      <hr className="divider" />
      <CardSkeleton lines={2} />
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

/** Admin/Ops console skeleton — section-shaped cards shown IMMEDIATELY while the lazy console chunk
 *  downloads (instead of a bare spinner), each with a min-height close to the real panel so content
 *  doesn't jump when it resolves (#28/#29). */
export function AdminSkeleton() {
  const panels = [220, 160, 200, 150, 180];
  return (
    <div className="stack" style={{ gap: 12, padding: 12 }} aria-hidden="true">
      {panels.map((h, i) => (
        <div key={i} className="card">
          <div className="card__body" style={{ minHeight: h }}>
            <SkeletonBox width={i % 2 ? 150 : 200} height={18} />
            <div style={{ height: 14 }} />
            <CardSkeleton lines={4} />
          </div>
        </div>
      ))}
    </div>
  );
}
