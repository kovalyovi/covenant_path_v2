// Disclaimer footer + the "About & privacy" and "Rules & definitions" dialogs. Content comes from
// lib/disclaimer.ts (ported verbatim from disclaimer.dart). These are surfaced from Settings; the
// footer sits at the bottom of the login screen.

import { Modal } from './Modal';
import { Button } from './ui';
import { kDisclaimerShort, kDisclaimerLong, kPrivacyNote, rulesSections } from '../lib/disclaimer';

export function DisclaimerFooter() {
  return (
    <p className="tiny muted" style={{ textAlign: 'center', padding: '12px 16px' }}>
      {kDisclaimerShort}
    </p>
  );
}

export function AboutDialog({ open, onClose }: { open: boolean; onClose: () => void }) {
  return (
    <Modal
      open={open}
      onClose={onClose}
      title="About & privacy"
      hideClose
      actions={<Button onClick={onClose}>Close</Button>}
    >
      <p>{kDisclaimerLong}</p>
      <h3 style={{ marginTop: 12, fontSize: '0.95rem' }}>Privacy</h3>
      <p style={{ marginTop: 4 }}>{kPrivacyNote}</p>
    </Modal>
  );
}

export function RulesDialog({ open, onClose }: { open: boolean; onClose: () => void }) {
  return (
    <Modal
      open={open}
      onClose={onClose}
      title="Rules & definitions"
      hideClose
      actions={<Button onClick={onClose}>Close</Button>}
    >
      {rulesSections.map((s) => (
        <section key={s.title} style={{ marginBottom: 12 }}>
          <h3 style={{ fontSize: '0.9rem', fontWeight: 700 }}>{s.title}</h3>
          <ul style={{ margin: '4px 0 0', paddingLeft: 18 }}>
            {s.points.map((p, i) => (
              <li key={i} className="small" style={{ marginBottom: 3 }}>
                {p}
              </li>
            ))}
          </ul>
        </section>
      ))}
    </Modal>
  );
}
