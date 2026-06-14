// Full-time / assigned missionaries for a ward, from the stake's synced `missionaries` map (keyed by
// UNIT NAME on `stakes.missionaries`). The bulk payload gives COMPANIONSHIPS (#3a): each entry is a
// companionship — its missionaries (with avatar photos from /api/v5/sync/files) + a SHARED phone/email.
// Tolerant of the older flat shape (one missionary per row) for stakes not yet re-synced.

import { useDashboard } from '../hooks/useDashboard';
import { Icon } from './Icon';
import { Avatar, SectionCard } from './ui';

export type MissionaryRec = Record<string, unknown>;

interface MPerson { uuid?: string; name?: string; email?: string; type?: string; photo_url?: string }
export interface Companionship { phone?: string; email?: string; mission_name?: string; missionaries: MPerson[] }

/** Normalize either shape to a list of companionships (an old flat record = a 1-person companionship). */
function normalize(recs: MissionaryRec[]): Companionship[] {
  return (recs ?? []).map((r) => {
    const ms = (r as { missionaries?: unknown }).missionaries;
    if (Array.isArray(ms)) return r as unknown as Companionship;
    return { phone: r['phone'] as string, email: r['email'] as string, missionaries: [r as unknown as MPerson] };
  });
}

/** The assigned missionary COMPANIONSHIPS for a unit (by unit name), or [] when none are synced. */
export function useUnitMissionaries(unitName: string | null | undefined): Companionship[] {
  const { missionaries } = useDashboard();
  if (!unitName) return [];
  return normalize(missionaries[unitName] ?? []);
}

function Contact({ phone, email }: { phone?: string; email?: string }) {
  if (!phone && !email) return null;
  return (
    <span className="row" style={{ gap: 10, flexWrap: 'wrap' }}>
      {phone && (
        <a className="row tiny" href={`tel:${phone}`} style={{ gap: 3, color: 'var(--primary)' }}>
          <Icon name="account" size={12} /> {phone}
        </a>
      )}
      {email && (
        <a className="row tiny" href={`mailto:${email}`} style={{ gap: 3, color: 'var(--primary)', wordBreak: 'break-all' }}>
          <Icon name="mail" size={12} /> {email}
        </a>
      )}
    </span>
  );
}

/** Compact companionship rows (used inside a person card / unit card / Leadership tab). */
export function MissionaryStrip({ missionaries }: { missionaries: MissionaryRec[] | Companionship[] }) {
  const comps = normalize(missionaries as MissionaryRec[]);
  if (comps.length === 0) return null;
  return (
    <div className="stack" style={{ gap: 10 }}>
      {comps.map((c, i) => (
        <div key={i} className="stack" style={{ gap: 4 }}>
          <div className="row" style={{ gap: 10, flexWrap: 'wrap', alignItems: 'center' }}>
            {c.missionaries.map((m, j) => (
              <span key={j} className="row" style={{ gap: 6, alignItems: 'center' }}>
                <Avatar name={m.name ?? '?'} photoUrl={m.photo_url} size={28} />
                <span className="small">{m.name}</span>
              </span>
            ))}
          </div>
          <Contact phone={c.phone} email={c.email} />
        </div>
      ))}
    </div>
  );
}

/** Detail-style companionship list with photos + shared contact (person detail / by-unit section). */
export function MissionariesSection({
  unitName,
  title = 'Full-Time Missionaries',
}: {
  unitName: string | null | undefined;
  title?: string;
}) {
  const comps = useUnitMissionaries(unitName);
  return (
    <SectionCard title={title} icon="volunteer">
      {comps.length === 0 ? (
        <p className="muted">No assigned missionaries on record for {unitName ? `${unitName}.` : 'this unit.'}</p>
      ) : (
        <div className="stack" style={{ gap: 12 }}>
          {comps.map((c, i) => (
            <div key={i} className="stack" style={{ gap: 6 }}>
              <div className="stack" style={{ gap: 6 }}>
                {c.missionaries.map((m, j) => (
                  <div key={j} className="row" style={{ gap: 8, alignItems: 'center' }}>
                    <Avatar name={m.name ?? '?'} photoUrl={m.photo_url} size={34} />
                    <div style={{ minWidth: 0 }}>
                      <div>{m.name ?? '—'}</div>
                      {m.type && <div className="tiny muted">{m.type}</div>}
                    </div>
                  </div>
                ))}
              </div>
              <Contact phone={c.phone} email={c.email} />
              {i < comps.length - 1 && <hr className="divider" />}
            </div>
          ))}
        </div>
      )}
    </SectionCard>
  );
}
