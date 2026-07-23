// Manual (leader-added) baptism candidates + the merge-suggestion UI (item 11). A leader can add a
// friend/investigator to a unit — name + notes + an optional baptism date + an optional assigned
// missionary companionship — BEFORE LCR has a record. When the daily sync later brings a matching real
// record (by name in the same unit), a Merge button appears (remote fully overrides, notes preserved);
// the SERVER also auto-merges an exact name+unit match on sync (db.merge_manual_members). Rows are
// editable and removable (temp folks). Shown on the Baptisms page (and Golden Hour's "Being Taught").

import { useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { useDashboard, type ManualMemberInput } from '../hooks/useDashboard';
import { mergeSuggestions, planMerge, type ManualMember } from '../logic/manualMembers';
import { parseMemberDate, fmtMonthDayYear } from '../logic/dates';
import { useUnitMissionaries, MissionaryStrip, type Companionship } from './Missionaries';
import { SectionCard, IconButton } from './ui';
import { Icon } from './Icon';
import { Modal } from './Modal';
import { useToast } from './Toast';

type UnitOpt = { id: string | null; name: string };

/** A short label for a companionship: the missionaries' names joined, else the mission name. */
function compLabel(c: Companionship): string {
  const names = (c.missionaries ?? []).map((m) => m.name).filter(Boolean) as string[];
  return names.length ? names.join(' & ') : c.mission_name || 'Companionship';
}

/** Manual people sorted for the Baptisms context: those with a baptism date first (soonest first),
 *  then the undated, then by name. */
function sortManual(list: ManualMember[]): ManualMember[] {
  return [...list].sort((a, b) => {
    const da = a.baptism_date ?? '';
    const db = b.baptism_date ?? '';
    if (da && db) return da.localeCompare(db);
    if (da) return -1;
    if (db) return 1;
    return a.name.localeCompare(b.name);
  });
}

/** The "Added by you" block: an "Add" button, any merge suggestions, then the manual person cards
 *  (name · unit · baptism date · notes · assigned missionaries) with Edit + Remove. */
export function ManualMembersSection() {
  const d = useDashboard();
  const toast = useToast();
  const navigate = useNavigate();
  const [adding, setAdding] = useState(false);
  const [editing, setEditing] = useState<ManualMember | null>(null);

  const units = unitOptions(d.members);
  const suggestions = mergeSuggestions(d.manualMembers, d.members);
  const people = sortManual(d.manualMembers);

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
      trailing={<IconButton icon="person_add" label="Add a baptism candidate" onClick={() => setAdding(true)} />}
    >
      {people.length === 0 ? (
        <p className="muted" style={{ margin: 0 }}>
          Add someone you’re teaching before they appear in the Church records.
        </p>
      ) : (
        <div className="stack" style={{ gap: 4 }}>
          {people.map((mm) => {
            const sug = suggestions.find((s) => s.manual.id === mm.id);
            const date = parseMemberDate(mm.baptism_date);
            const comp = mm.missionaries && typeof mm.missionaries === 'object'
              ? (mm.missionaries as unknown as Companionship) : null;
            return (
              <div key={mm.id} className="manual-member">
                <div className="manual-member__main">
                  <span className="row" style={{ gap: 6, alignItems: 'center', flexWrap: 'wrap' }}>
                    <Icon name="account" size={16} color="var(--on-surface-variant)" />
                    <span style={{ fontWeight: 600 }}>{mm.name}</span>
                    {mm.unit_name && <span className="tiny muted">· {mm.unit_name}</span>}
                    {date && (
                      <span className="tiny" style={{ color: 'var(--primary)' }}>
                        · <Icon name="water_drop" size={12} /> {fmtMonthDayYear(date)}
                      </span>
                    )}
                  </span>
                  {mm.custom_notes && (
                    <p className="small muted" style={{ margin: '2px 0 0', whiteSpace: 'pre-wrap' }}>
                      {mm.custom_notes}
                    </p>
                  )}
                  {comp && (
                    <div style={{ marginTop: 6 }}>
                      <MissionaryStrip missionaries={[comp as unknown as Record<string, unknown>]} />
                    </div>
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
                  <IconButton icon="edit" label="Edit" size={18} onClick={() => setEditing(mm)} />
                  <IconButton icon="close" label="Remove" size={18} onClick={() => void remove(mm.id)} />
                </div>
              </div>
            );
          })}
        </div>
      )}
      {adding && <ManualMemberDialog units={units} onClose={() => setAdding(false)} />}
      {editing && <ManualMemberDialog units={units} existing={editing} onClose={() => setEditing(null)} />}
    </SectionCard>
  );
}

/** Add / edit a manual baptism candidate: name, unit, baptism date, notes, and an optional missionary
 *  companionship (from the selected unit's synced roster). Doubles as the edit dialog when `existing`. */
function ManualMemberDialog({
  units, existing, onClose,
}: {
  units: UnitOpt[];
  existing?: ManualMember;
  onClose: () => void;
}) {
  const d = useDashboard();
  const toast = useToast();
  const [name, setName] = useState(existing?.name ?? '');
  const [notes, setNotes] = useState(existing?.custom_notes ?? '');
  const [baptismDate, setBaptismDate] = useState(existing?.baptism_date ?? '');
  const foundUnit = units.findIndex((u) =>
    (existing?.unit_id && u.id === existing.unit_id) ||
    (!existing?.unit_id && !!existing?.unit_name && u.name === existing.unit_name));
  const [unitIdx, setUnitIdx] = useState(foundUnit < 0 ? 0 : foundUnit);
  const [saving, setSaving] = useState(false);

  const unitName = units[unitIdx]?.name ?? null;
  const comps = useUnitMissionaries(unitName);
  // Companionship options: the current unit's roster, plus the stored one (if editing and not already
  // present) so an edit never silently drops it. missIdx 0 = "No missionaries", 1..N = compUnion[i-1].
  const existingComp = existing?.missionaries && typeof existing.missionaries === 'object'
    ? (existing.missionaries as unknown as Companionship) : null;
  const compUnion: Companionship[] = [...comps];
  if (existingComp && !compUnion.some((c) => compLabel(c) === compLabel(existingComp))) {
    compUnion.unshift(existingComp);
  }
  const [missIdx, setMissIdx] = useState(() => {
    if (!existingComp) return 0;
    const i = compUnion.findIndex((c) => compLabel(c) === compLabel(existingComp));
    return i < 0 ? 0 : i + 1;
  });
  const chosenComp = missIdx > 0 ? compUnion[missIdx - 1] ?? null : null;

  async function save() {
    if (!name.trim()) return;
    setSaving(true);
    // KNOWN EDGE (low): with no units loaded (brand-new stake) this falls back to a null unit_id — fine
    // for a STAKE leader (role unit_id null → RLS passes); a WARD leader would hit an RLS denial (caught
    // by the toast) until their first sync populates `units`.
    const u = units[unitIdx] ?? units[0] ?? { id: null, name: '' };
    const input: ManualMemberInput = {
      unitId: u.id,
      unitName: u.name || null,
      name,
      notes,
      baptismDate: baptismDate || null,
      missionaries: (chosenComp as unknown as Record<string, unknown>) ?? null,
    };
    try {
      if (existing) await d.updateManualMember(existing.id, input);
      else await d.addManualMember(input);
      toast.show({ message: existing ? `Updated ${name.trim()}.` : `Added ${name.trim()}.` });
      onClose();
    } catch (e) {
      toast.show({ message: `Could not save: ${e instanceof Error ? e.message : e}` });
    } finally {
      setSaving(false);
    }
  }

  return (
    <Modal open onClose={onClose} title={existing ? 'Edit person' : 'Add a baptism candidate'}>
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
              onChange={(e) => { setUnitIdx(Number(e.target.value)); setMissIdx(0); }}
            >
              {units.map((u, i) => (
                <option key={u.id ?? u.name} value={i}>{u.name || 'Unit'}</option>
              ))}
            </select>
          </label>
        )}
        <label className="field">
          <span>Baptism date <span className="tiny muted">(optional)</span></span>
          <input
            className="input"
            type="date"
            value={baptismDate ?? ''}
            onChange={(e) => setBaptismDate(e.target.value)}
          />
        </label>
        {compUnion.length > 0 && (
          <label className="field">
            <span>Missionaries <span className="tiny muted">(optional)</span></span>
            <select className="select" value={missIdx} onChange={(e) => setMissIdx(Number(e.target.value))}>
              <option value={0}>No missionaries</option>
              {compUnion.map((c, i) => (
                <option key={i} value={i + 1}>{compLabel(c)}</option>
              ))}
            </select>
          </label>
        )}
        <label className="field">
          <span>Notes</span>
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
          <button type="button" className="btn btn--filled" disabled={saving || !name.trim()} onClick={() => void save()}>
            {saving ? 'Saving…' : existing ? 'Save' : 'Add'}
          </button>
        </div>
      </div>
    </Modal>
  );
}

/** Distinct (unit_id, unit_name) options from the members the leader can see, sorted by name. A
 *  single-unit leader still gets their one unit; a stake leader gets all their units. */
function unitOptions(members: ReturnType<typeof useDashboard>['members']): UnitOpt[] {
  const seen = new Map<string, UnitOpt>();
  for (const m of members) {
    const name = String(m['unit_name'] ?? '').trim();
    if (!name) continue;
    const id = (m['unit_id'] as string | null | undefined) ?? null;
    const key = id ?? name;
    if (!seen.has(key)) seen.set(key, { id, name });
  }
  return [...seen.values()].sort((a, b) => a.name.localeCompare(b.name));
}
