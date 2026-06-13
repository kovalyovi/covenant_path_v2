// Manual (leader-added) people being taught + the merge-suggestion UI (item 11). Shown in the
// Being-Taught view. A leader can add a friend/investigator to a unit (name + custom notes) before
// LCR has a record; when the daily sync later brings a matching real record (by name in the same
// unit), a Merge button appears — remote fully overrides, the custom notes are preserved.

import { useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { useDashboard } from '../hooks/useDashboard';
import { mergeSuggestions, planMerge, type ManualMember } from '../logic/manualMembers';
import { SectionCard, IconButton } from './ui';
import { Icon } from './Icon';
import { Modal } from './Modal';
import { useToast } from './Toast';

/** The Being-Taught manual-members block: an "Add" button, any merge suggestions, then the manual
 *  member cards. Returns null only after both lists are empty AND the add dialog is closed. */
export function ManualMembersSection() {
  const d = useDashboard();
  const toast = useToast();
  const navigate = useNavigate();
  const [adding, setAdding] = useState(false);

  // Units the leader can add to: derived from the members they can see (id + name), de-duped.
  const units = unitOptions(d.members);
  const suggestions = mergeSuggestions(d.manualMembers, d.members);

  async function merge(manual: ManualMember, personUuid: string) {
    try {
      await d.mergeManualMember(planMerge(manual, d.members.find((m) => String(m['person_uuid']) === personUuid)!));
      toast.show({ message: 'Merged — the record updated and your notes were kept.' });
    } catch (e) {
      toast.show({ message: `Could not merge: ${e instanceof Error ? e.message : e}` });
    }
  }

  async function remove(id: string) {
    try {
      await d.deleteManualMember(id);
    } catch (e) {
      toast.show({ message: `Could not remove: ${e instanceof Error ? e.message : e}` });
    }
  }

  return (
    <SectionCard
      title="Added by you"
      icon="person_add"
      trailing={<IconButton icon="person_add" label="Add a person being taught" onClick={() => setAdding(true)} />}
    >
      {d.manualMembers.length === 0 ? (
        <p className="muted" style={{ margin: 0 }}>
          Add a friend or investigator you're teaching before they appear in the Church records.
        </p>
      ) : (
        <div className="stack" style={{ gap: 4 }}>
          {d.manualMembers.map((mm) => {
            const sug = suggestions.find((s) => s.manual.id === mm.id);
            return (
              <div key={mm.id} className="manual-member">
                <div className="manual-member__main">
                  <span className="row" style={{ gap: 6, alignItems: 'center' }}>
                    <Icon name="account" size={16} color="var(--on-surface-variant)" />
                    <span style={{ fontWeight: 600 }}>{mm.name}</span>
                    {mm.unit_name && <span className="tiny muted">· {mm.unit_name}</span>}
                  </span>
                  {mm.custom_notes && (
                    <p className="small muted" style={{ margin: '2px 0 0', whiteSpace: 'pre-wrap' }}>
                      {mm.custom_notes}
                    </p>
                  )}
                  {sug && (
                    <div className="manual-member__suggest">
                      <Icon name="info" size={14} color="var(--primary)" />
                      <span className="tiny">
                        A matching record arrived in the sync. Merge to keep your notes on it.
                      </span>
                    </div>
                  )}
                </div>
                <div className="row" style={{ gap: 4 }}>
                  {sug && (
                    <button
                      type="button"
                      className="btn btn--filled"
                      onClick={() => void merge(mm, String(sug.match['person_uuid']))}
                    >
                      Merge
                    </button>
                  )}
                  {sug && (
                    <IconButton
                      icon="visibility"
                      label="View the matched record"
                      size={18}
                      onClick={() => navigate(`/person/${encodeURIComponent(String(sug.match['person_uuid']))}`)}
                    />
                  )}
                  <IconButton icon="close" label="Remove" size={18} onClick={() => void remove(mm.id)} />
                </div>
              </div>
            );
          })}
        </div>
      )}
      {adding && <AddManualDialog units={units} onClose={() => setAdding(false)} />}
    </SectionCard>
  );
}

function AddManualDialog({
  units, onClose,
}: {
  units: Array<{ id: string | null; name: string }>;
  onClose: () => void;
}) {
  const d = useDashboard();
  const toast = useToast();
  const [name, setName] = useState('');
  const [notes, setNotes] = useState('');
  const [unitIdx, setUnitIdx] = useState(0);
  const [saving, setSaving] = useState(false);

  async function save() {
    if (!name.trim()) return;
    setSaving(true);
    try {
      const u = units[unitIdx] ?? units[0] ?? { id: null, name: '' };
      await d.addManualMember({ unitId: u.id, unitName: u.name || null, name, notes });
      toast.show({ message: `Added ${name.trim()}.` });
      onClose();
    } catch (e) {
      toast.show({ message: `Could not add: ${e instanceof Error ? e.message : e}` });
    } finally {
      setSaving(false);
    }
  }

  return (
    <Modal open onClose={onClose} title="Add a person being taught">
      <div className="stack" style={{ gap: 12, padding: 4 }}>
        <label className="field">
          <span>Name</span>
          <input
            className="input"
            placeholder="Given Surname"
            value={name}
            onChange={(e) => setName(e.target.value)}
            autoFocus
          />
        </label>
        {units.length > 1 && (
          <label className="field">
            <span>Unit</span>
            <select
              className="select"
              value={unitIdx}
              onChange={(e) => setUnitIdx(Number(e.target.value))}
            >
              {units.map((u, i) => (
                <option key={u.id ?? u.name} value={i}>{u.name || 'Unit'}</option>
              ))}
            </select>
          </label>
        )}
        <label className="field">
          <span>Custom notes</span>
          <textarea
            className="textarea"
            rows={4}
            placeholder="Anything you want to remember about them…"
            value={notes}
            onChange={(e) => setNotes(e.target.value)}
          />
        </label>
        <div className="row" style={{ gap: 8, justifyContent: 'flex-end' }}>
          <button type="button" className="btn btn--text" disabled={saving} onClick={onClose}>Cancel</button>
          <button type="button" className="btn btn--filled" disabled={saving || !name.trim()} onClick={save}>
            {saving ? 'Adding…' : 'Add'}
          </button>
        </div>
      </div>
    </Modal>
  );
}

/** Distinct (unit_id, unit_name) options from the members the leader can see, sorted by name. A
 *  single-unit leader still gets their one unit; a stake leader gets all their units. */
function unitOptions(members: ReturnType<typeof useDashboard>['members']): Array<{ id: string | null; name: string }> {
  const seen = new Map<string, { id: string | null; name: string }>();
  for (const m of members) {
    const name = String(m['unit_name'] ?? '').trim();
    if (!name) continue;
    const id = (m['unit_id'] as string | null | undefined) ?? null;
    const key = id ?? name;
    if (!seen.has(key)) seen.set(key, { id, name });
  }
  return [...seen.values()].sort((a, b) => a.name.localeCompare(b.name));
}
