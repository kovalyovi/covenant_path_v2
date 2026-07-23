// The missionary transfer schedule surfaced on the Baptisms page: a highlighted "next transfer in N
// days" banner, plus a stake-leader-only "Manage" modal to add / adjust / remove the dates. The data
// lives in `transfer_dates` (per-stake, RLS-scoped); reads/writes go through useDashboard. Ricky's
// Mission-KPIs app pulls the same schedule from our broker so both apps share one source of truth.

import { useState } from 'react';
import { useDashboard } from '../hooks/useDashboard';
import { nextTransfer } from '../logic/transfers';
import { dayOnly, fmtLong } from '../logic/dates';
import { Icon } from './Icon';
import { IconButton } from './ui';
import { Modal } from './Modal';
import { useToast } from './Toast';

/** "Next transfer is in N days (date)" — a highlighted note on the Baptisms page. Renders nothing when
 *  the stake has no upcoming transfer scheduled. Stake leaders get a "Manage" affordance to edit it. */
export function NextTransferBanner() {
  const d = useDashboard();
  const [managing, setManaging] = useState(false);
  const canManage = d.enrollStatus?.viewerIsStakeLeader === true;
  const next = nextTransfer(d.transferDates, dayOnly(new Date()));

  // No schedule / nothing ahead: show nothing to consumers, but still let a stake leader open Manage to
  // seed the first dates (via the small "Set transfer dates" link) — otherwise there'd be no entry point.
  if (!next) {
    if (!canManage) return null;
    return (
      <>
        <div className="banner banner--info" role="status">
          <span className="row" style={{ gap: 8 }}>
            <Icon name="date_range" size={18} color="var(--primary)" />
            No transfer dates set yet.
          </span>
          <button type="button" className="btn btn--text" onClick={() => setManaging(true)}>
            Set transfer dates
          </button>
        </div>
        {managing && <ManageTransferDates onClose={() => setManaging(false)} />}
      </>
    );
  }

  const when =
    next.daysUntil === 0 ? 'today' : next.daysUntil === 1 ? 'in 1 day' : `in ${next.daysUntil} days`;
  return (
    <>
      <div className="banner banner--info" role="status">
        <span className="row" style={{ gap: 8 }}>
          <Icon name="date_range" size={18} color="var(--primary)" />
          <span>
            Next transfer is <strong>{when}</strong> ({fmtLong(next.date)}).
          </span>
        </span>
        {canManage && (
          <IconButton icon="edit" label="Manage transfer dates" size={18} onClick={() => setManaging(true)} />
        )}
      </div>
      {managing && <ManageTransferDates onClose={() => setManaging(false)} />}
    </>
  );
}

/** Stake-leader editor for the schedule: adjust a date in place, remove one, or add a new transfer
 *  (transfer_id derived from the date, e.g. `t-2026-07-23`, so ward goals can reference the cycle). */
function ManageTransferDates({ onClose }: { onClose: () => void }) {
  const d = useDashboard();
  const toast = useToast();
  const [adding, setAdding] = useState('');
  const [busy, setBusy] = useState(false);

  async function edit(transferId: string, date: string) {
    if (!date) return;
    setBusy(true);
    try {
      await d.upsertTransferDate({ transferId, date });
    } catch (e) {
      toast.show({ message: `Could not save: ${e instanceof Error ? e.message : e}` });
    } finally {
      setBusy(false);
    }
  }

  async function add() {
    if (!adding) return;
    setBusy(true);
    try {
      await d.upsertTransferDate({ transferId: `t-${adding}`, date: adding });
      setAdding('');
    } catch (e) {
      toast.show({ message: `Could not add: ${e instanceof Error ? e.message : e}` });
    } finally {
      setBusy(false);
    }
  }

  async function remove(id?: string) {
    if (!id) return;
    setBusy(true);
    try {
      await d.deleteTransferDate(id);
    } catch (e) {
      toast.show({ message: `Could not remove: ${e instanceof Error ? e.message : e}` });
    } finally {
      setBusy(false);
    }
  }

  return (
    <Modal open onClose={onClose} title="Transfer dates">
      <div className="stack" style={{ gap: 12, padding: 4 }}>
        <p className="muted" style={{ margin: 0 }}>
          The mission’s transfer schedule. It drives the “next transfer” note and ward goals.
        </p>
        {d.transferDates.length > 0 && (
          <div className="stack" style={{ gap: 6 }}>
            {d.transferDates.map((t) => (
              <div key={t.transfer_id} className="row" style={{ gap: 8, alignItems: 'center' }}>
                <input
                  className="input"
                  type="date"
                  defaultValue={t.transfer_date}
                  disabled={busy}
                  onChange={(e) => void edit(t.transfer_id, e.target.value)}
                  style={{ flex: 1 }}
                />
                <IconButton icon="close" label="Remove this transfer date" size={18} onClick={() => void remove(t.id)} />
              </div>
            ))}
          </div>
        )}
        <div className="row" style={{ gap: 8, alignItems: 'flex-end' }}>
          <label className="field" style={{ flex: 1 }}>
            <span>Add a transfer date</span>
            <input
              className="input"
              type="date"
              value={adding}
              disabled={busy}
              onChange={(e) => setAdding(e.target.value)}
            />
          </label>
          <button type="button" className="btn btn--filled" disabled={busy || !adding} onClick={() => void add()}>
            Add
          </button>
        </div>
        <div className="row" style={{ gap: 8, justifyContent: 'flex-end' }}>
          <button type="button" className="btn btn--text" onClick={onClose}>Done</button>
        </div>
      </div>
    </Modal>
  );
}
