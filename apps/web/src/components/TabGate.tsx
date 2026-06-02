// Per-tab loading/error/empty gate — the React equivalent of the Flutter `_Body` FutureBuilder.
// Shows the content-shaped skeleton while loading, a friendly error, the empty state when there are
// no members (except the Table tab, which renders its own header even when empty), else the children.

import type { ReactNode } from 'react';
import { useDashboard } from '../hooks/useDashboard';
import { MemberListSkeleton } from './Skeletons';
import { EmptyState } from './EmptyState';

export function TabGate({ allowEmpty = false, children }: { allowEmpty?: boolean; children: ReactNode }) {
  const d = useDashboard();
  if (d.loading) return <MemberListSkeleton />;
  if (d.error) {
    return (
      <div className="center-col" style={{ minHeight: '50vh' }}>
        <p style={{ textAlign: 'center', whiteSpace: 'pre-line' }}>Could not load data:{'\n'}{d.error}</p>
      </div>
    );
  }
  if (d.members.length === 0 && !allowEmpty) return <EmptyState enrollStatus={d.enrollStatus} />;
  return <>{children}</>;
}
