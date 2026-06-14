// The ad-hoc convert-integration report sheet (#73, reworked #4). The broker builds the stake-wide
// report; this sheet lets a leader narrow it on-screen by UNIT (multi-select) and CATEGORY/step
// (multi-select) before reading it, then email the full report. Nicer, compact layout.

import { useState } from 'react';
import { Modal } from './Modal';
import { Button } from './ui';
import { Icon, type IconName } from './Icon';
import { hexA, status } from '../theme/tokens';

interface Outstanding {
  name?: string;
  unit?: string;
  missing?: string[];
}

/** A never-empty multi-select chip row (deselecting the last re-selects all). */
function ChipMulti({ label, icon, all, selected, onToggle, onReset }: {
  label: string; icon: IconName; all: string[]; selected: Set<string>;
  onToggle: (v: string) => void; onReset: () => void;
}) {
  if (all.length <= 1) return null;
  const isAll = selected.size === all.length;
  return (
    <div className="stack" style={{ gap: 4 }}>
      <span className="row tiny muted" style={{ gap: 4, alignItems: 'center' }}>
        <Icon name={icon} size={13} /> {label}
        {!isAll && (
          <button
            type="button"
            onClick={onReset}
            style={{ border: 'none', background: 'none', color: 'var(--primary)', cursor: 'pointer', font: 'inherit', padding: 0 }}
          >
            · all
          </button>
        )}
      </span>
      <div className="wrap" style={{ gap: 6 }}>
        {all.map((v) => {
          const sel = selected.has(v);
          return (
            <button
              key={v}
              type="button"
              className="chip"
              aria-pressed={sel}
              onClick={() => onToggle(v)}
              style={{
                fontSize: 12,
                background: sel ? hexA(status.info, 0.16) : 'var(--surface)',
                borderColor: sel ? hexA(status.info, 0.7) : 'var(--outline)',
                color: sel ? status.info : 'var(--on-surface-variant)',
                fontWeight: sel ? 700 : 500,
              }}
            >
              {v}
            </button>
          );
        })}
      </div>
    </div>
  );
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
  const outstanding = (report['outstanding'] as Outstanding[]) ?? [];
  const byMilestone = (report['by_milestone'] as Array<[string, number]>) ?? [];
  const title = String(report['stake_name'] ?? 'Convert report');

  const allUnits = [...new Set(outstanding.map((o) => o.unit).filter(Boolean) as string[])].sort();
  const allCats = byMilestone.map((kv) => kv[0]);
  const [units, setUnits] = useState<Set<string>>(new Set(allUnits));
  const [cats, setCats] = useState<Set<string>>(new Set(allCats));

  function toggle(set: Set<string>, all: string[], v: string, setter: (s: Set<string>) => void) {
    const next = new Set(set);
    if (next.has(v)) { if (next.size > 1) next.delete(v); } else next.add(v);
    if (next.size === 0) all.forEach((x) => next.add(x));
    setter(next);
  }

  // Filter the server's outstanding list by the selected units + categories (client-side).
  const filtered = outstanding
    .filter((o) => !o.unit || units.has(o.unit))
    .map((o) => ({ ...o, missing: (o.missing ?? []).filter((m) => cats.size === allCats.length || cats.has(m)) }))
    .filter((o) => o.missing.length > 0);

  // Recompute the per-step counts within the current selection.
  const stepCounts = new Map<string, number>();
  for (const o of filtered) for (const m of o.missing) stepCounts.set(m, (stepCounts.get(m) ?? 0) + 1);
  const steps = [...stepCounts.entries()].sort((a, b) => b[1] - a[1]);

  return (
    <Modal
      open={open}
      onClose={onClose}
      side
      title={title}
      actions={
        <Button
          variant="filled"
          icon="mail"
          onClick={async () => { await onEmail(); onClose(); }}
        >
          Email full report to me
        </Button>
      }
    >
      <div className="stack" style={{ gap: 10 }}>
        <ChipMulti
          label="Units" icon="groups" all={allUnits} selected={units}
          onToggle={(v) => toggle(units, allUnits, v, setUnits)} onReset={() => setUnits(new Set(allUnits))}
        />
        <ChipMulti
          label="Categories" icon="checklist" all={allCats} selected={cats}
          onToggle={(v) => toggle(cats, allCats, v, setCats)} onReset={() => setCats(new Set(allCats))}
        />
      </div>
      <hr className="divider" />
      <p>
        <strong>{filtered.length}</strong> member{filtered.length === 1 ? '' : 's'} need attention
        {units.size < allUnits.length || cats.size < allCats.length ? ' (filtered)' : ''}
      </p>
      <hr className="divider" />
      {steps.length > 0 && (
        <>
          <h3 style={{ fontSize: '0.95rem' }}>Most-needed steps</h3>
          {steps.map((kv, i) => (
            <div key={i} className="row" style={{ justifyContent: 'space-between', padding: '2px 0' }}>
              <span>{kv[0]}</span>
              <strong>{kv[1]}</strong>
            </div>
          ))}
          <hr className="divider" />
        </>
      )}
      {filtered.length === 0 ? (
        <p style={{ textAlign: 'center', padding: '20px 0' }}>Everyone in this selection is on track. 🎉</p>
      ) : (
        <>
          <h3 style={{ fontSize: '0.95rem' }}>Outstanding by member</h3>
          {filtered.map((o, i) => (
            <div key={i} style={{ padding: '4px 0' }}>
              <strong>{o.name}{o.unit ? ` · ${o.unit}` : ''}</strong>
              <p className="small muted">{o.missing.join(', ')}</p>
            </div>
          ))}
        </>
      )}
    </Modal>
  );
}
