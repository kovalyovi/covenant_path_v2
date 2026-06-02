// The ad-hoc convert-integration report sheet (#73) — React port of `_ReportSheet`. Renders the
// totals, most-needed steps, and the per-member outstanding list, with an "Email to me" action.

import { Modal } from './Modal';
import { Button } from './ui';

interface Outstanding {
  name?: string;
  unit?: string;
  missing?: string[];
}

export function ReportSheet({
  open,
  onClose,
  report,
  onEmail,
}: {
  open: boolean;
  onClose: () => void;
  report: Record<string, unknown>;
  onEmail: () => Promise<void>;
}) {
  const total = Number(report['total'] ?? 0);
  const onTrack = Number(report['on_track'] ?? 0);
  const outstanding = ((report['outstanding'] as Outstanding[]) ?? []);
  const byMilestone = ((report['by_milestone'] as Array<[string, number]>) ?? []);
  const title = String(report['stake_name'] ?? 'Convert report');

  return (
    <Modal
      open={open}
      onClose={onClose}
      sheet
      title={title}
      actions={
        <Button
          variant="filled"
          icon="mail"
          onClick={async () => {
            await onEmail();
            onClose();
          }}
        >
          Email to me
        </Button>
      }
    >
      <p>
        {total} new members · {onTrack} on track · {outstanding.length} need attention
      </p>
      <hr className="divider" />
      {byMilestone.length > 0 && (
        <>
          <h3 style={{ fontSize: '0.95rem' }}>Most-needed steps</h3>
          {byMilestone.map((kv, i) => (
            <div key={i} className="row" style={{ justifyContent: 'space-between', padding: '2px 0' }}>
              <span>{kv[0]}</span>
              <strong>{kv[1]}</strong>
            </div>
          ))}
          <hr className="divider" />
        </>
      )}
      {outstanding.length === 0 ? (
        <p style={{ textAlign: 'center', padding: '20px 0' }}>Everyone in scope is on track. 🎉</p>
      ) : (
        <>
          <h3 style={{ fontSize: '0.95rem' }}>Outstanding by member</h3>
          {outstanding.map((o, i) => (
            <div key={i} style={{ padding: '4px 0' }}>
              <strong>
                {o.name}
                {o.unit ? ` · ${o.unit}` : ''}
              </strong>
              <p className="small muted">{(o.missing ?? []).join(', ')}</p>
            </div>
          ))}
        </>
      )}
    </Modal>
  );
}
