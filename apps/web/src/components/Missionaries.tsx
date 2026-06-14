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

/** Pull a clean phone out of a raw directory value that may carry trailing label text (e.g.
 *  "(919) 555-1234 Morrisville"). `href` is digits-only (a valid `tel:`), `text` is the human number
 *  without the label. Null when no number is present. */
function phoneParts(raw?: string): { href: string; text: string } | null {
  if (!raw) return null;
  const m = /\+?\d[\d().\-\s]{5,}\d/.exec(raw); // first phone-shaped run
  const text = (m ? m[0] : raw).trim();
  const digits = text.replace(/[^\d+]/g, ''); // tel: wants only digits + a leading +
  return digits.replace(/\D/g, '').length >= 7 ? { href: `tel:${digits}`, text } : null;
}

/** Pull a clean email out of a raw value (strip surrounding label text / trailing punctuation). */
function emailParts(raw?: string): { href: string; text: string } | null {
  if (!raw) return null;
  const m = /[^\s,;<>]+@[^\s,;<>]+\.[^\s,;<>]+/.exec(raw);
  if (!m) return null;
  const text = m[0].replace(/[.,;]+$/, '');
  return { href: `mailto:${text}`, text };
}

/** Phone + email as REAL anchors, each on its own row, sanitized so the link is just the number/address
 *  (no trailing label) and copies cleanly. `size` scales the type (default = small). */
function Contact({ phone, email, size = 'small' }: { phone?: string; email?: string; size?: 'tiny' | 'small' }) {
  const ph = phoneParts(phone);
  const em = emailParts(email);
  if (!ph && !em) return null;
  return (
    <div className="stack" style={{ gap: 3 }}>
      {ph && (
        <a className={`row ${size}`} href={ph.href} style={{ gap: 5, color: 'var(--primary)', alignItems: 'center' }}>
          <Icon name="account" size={14} /> {ph.text}
        </a>
      )}
      {em && (
        <a className={`row ${size}`} href={em.href} style={{ gap: 5, color: 'var(--primary)', alignItems: 'center', wordBreak: 'break-all' }}>
          <Icon name="mail" size={14} /> {em.text}
        </a>
      )}
    </div>
  );
}

/** Compact companionship rows (used inside a person card / unit card / Leadership tab). Larger, nicer
 *  type for the leader-facing list, with contact info on its own two rows. */
export function MissionaryStrip({ missionaries }: { missionaries: MissionaryRec[] | Companionship[] }) {
  const comps = normalize(missionaries as MissionaryRec[]);
  if (comps.length === 0) return null;
  return (
    <div className="stack" style={{ gap: 14 }}>
      {comps.map((c, i) => (
        <div key={i} className="stack" style={{ gap: 6 }}>
          <div className="row" style={{ gap: 14, flexWrap: 'wrap', alignItems: 'center' }}>
            {c.missionaries.map((m, j) => (
              <span key={j} className="row" style={{ gap: 8, alignItems: 'center' }}>
                <Avatar name={m.name ?? '?'} photoUrl={m.photo_url} size={36} />
                <span style={{ fontWeight: 600, fontSize: '0.95rem' }}>{m.name}</span>
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
