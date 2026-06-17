// Full-time / assigned missionaries for a ward, from the stake's synced `missionaries` map (keyed by
// UNIT NAME on `stakes.missionaries`). The bulk payload gives COMPANIONSHIPS (#3a): each entry is a
// companionship — its missionaries (with avatar photos from /api/v5/sync/files) + a SHARED phone/email.
// Tolerant of the older flat shape (one missionary per row) for stakes not yet re-synced.

import { useState } from 'react';
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

/** Surname out of a missionary name — "Surname, Given" (the synced shape) → the part before the comma,
 *  else the last whitespace token ("Given Surname"). Lower-cased for comparison. */
function surnameOf(name?: string): string {
  const n = (name ?? '').trim();
  if (!n) return '';
  if (n.includes(',')) return n.slice(0, n.indexOf(',')).trim().toLowerCase();
  const parts = n.split(/\s+/);
  return parts[parts.length - 1].toLowerCase();
}

/** A SENIOR (couple) companionship — a husband & wife serving together: two or more missionaries who
 *  share a surname. Young proselytizing companionships are same-gender with DIFFERENT surnames, so a
 *  shared surname cleanly identifies the senior couples. */
export function isSeniorCouple(c: Companionship): boolean {
  const surnames = (c.missionaries ?? []).map((m) => surnameOf(m.name)).filter(Boolean);
  return surnames.length >= 2 && new Set(surnames).size < surnames.length;
}

/** The teaching companionship to show on a per-person BAPTISM card: senior couples removed (they don't
 *  teach toward baptism — but they still appear in the "Missionaries by Unit" section), and capped at
 *  ONE companionship per card. */
export function baptismCardMissionaries(comps: Companionship[]): Companionship[] {
  return comps.filter((c) => !isSeniorCouple(c)).slice(0, 1);
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

/** A small copy-to-clipboard button (icon-only on phones, icon+label on wider screens). */
function CopyBtn({ text, what }: { text: string; what: string }) {
  const [copied, setCopied] = useState(false);
  return (
    <button
      type="button"
      className="contact-btn"
      title={`Copy ${what}`}
      onClick={() => {
        navigator.clipboard?.writeText(text).then(
          () => { setCopied(true); window.setTimeout(() => setCopied(false), 1400); },
          () => {},
        );
      }}
    >
      <Icon name={copied ? 'check' : 'copy'} size={15} />
      <span className="contact-btn__label">{copied ? 'Copied' : 'Copy'}</span>
    </button>
  );
}

/** Phone + email as PLAIN TEXT, each with Copy + a primary action (Call / Email) to the right. The
 *  values are sanitized (no trailing label like "…Morrisville"). Labels hide on small screens. */
function Contact({ phone, email }: { phone?: string; email?: string }) {
  const ph = phoneParts(phone);
  const em = emailParts(email);
  if (!ph && !em) return null;
  return (
    <div className="stack" style={{ gap: 6 }}>
      {ph && (
        <div className="contact-line">
          <span className="contact-line__value">{ph.text}</span>
          <span className="contact-line__actions">
            <CopyBtn text={ph.text} what="number" />
            <a className="contact-btn" href={ph.href} title="Call">
              <Icon name="account" size={15} /><span className="contact-btn__label">Call</span>
            </a>
          </span>
        </div>
      )}
      {em && (
        <div className="contact-line">
          <span className="contact-line__value" style={{ wordBreak: 'break-all' }}>{em.text}</span>
          <span className="contact-line__actions">
            <CopyBtn text={em.text} what="email" />
            <a className="contact-btn" href={em.href} title="Email">
              <Icon name="mail" size={15} /><span className="contact-btn__label">Email</span>
            </a>
          </span>
        </div>
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
          {/* a separator between companionships */}
          {i > 0 && <hr className="divider" style={{ marginBottom: 8 }} />}
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
  title = 'Missionaries',
}: {
  unitName: string | null | undefined;
  title?: string;
}) {
  const comps = useUnitMissionaries(unitName);
  const empty = comps.length === 0;
  return (
    // Highlight a unit with NO assigned missionaries: a warning-tone left border + a warning icon.
    <SectionCard
      title={title}
      icon={empty ? 'warning' : 'volunteer'}
      iconColor={empty ? 'var(--warning)' : undefined}
      tone={empty ? 'warn' : undefined}
    >
      {empty ? (
        <p className="row small" style={{ gap: 6, alignItems: 'center', color: 'var(--warning)' }}>
          <Icon name="warning" size={15} color="var(--warning)" />
          No missionaries assigned {unitName ? `to ${unitName}.` : 'to this unit.'}
        </p>
      ) : (
        <div className="stack" style={{ gap: 12 }}>
          {comps.map((c, i) => (
            <div key={i} className="stack" style={{ gap: 6 }}>
              {i > 0 && <hr className="divider" />}
              <div className="row" style={{ gap: 14, flexWrap: 'wrap', alignItems: 'center' }}>
                {c.missionaries.map((m, j) => (
                  <div key={j} className="row" style={{ gap: 8, alignItems: 'center' }}>
                    <Avatar name={m.name ?? '?'} photoUrl={m.photo_url} size={34} />
                    <span style={{ fontWeight: 600 }}>{m.name ?? '—'}</span>
                  </div>
                ))}
              </div>
              <Contact phone={c.phone} email={c.email} />
            </div>
          ))}
        </div>
      )}
    </SectionCard>
  );
}
