// Families tab — part-member families (Turley proposal, Aug 2026): a household where one or more
// are members and one or more are not — an unbaptized member of record 9+ or an unbaptized spouse.
// Mobile-first: family CARDS grouped by unit (not a dense table). Lists A + B are derived by the
// daily sync from the Member Tools household directory (aligned to Ricky Bloomfield's verified
// Mission-KPIs model — classifications MEMBER, per-unit uuid sets, couple-form listed names for
// spouse-not-on-record candidates); leaders can also add a spouse by hand from the LCR report.
// Status is leader-entered: Identified → Love → Share → On Date → Baptized, plus Do Not Contact.
// The monthly rollup at the bottom is unit TOTALS ONLY (no names) for the stake presidency.

import { useMemo, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { useDashboard } from '../../hooks/useDashboard';
import { useTier } from '../../hooks/useTier';
import { PageScaffold, SectionTitle, SubtleNote } from '../../components/dashboard';
import { Button, Segmented, SectionCard } from '../../components/ui';
import { TabGate } from '../../components/TabGate';
import { useToast } from '../../components/Toast';
import {
  ageBand, findOnDateInvestigator, groupFamiliesByUnit, needsAttention, rollupByUnit,
  PMF_PIPELINE, PMF_SOURCE_LABELS, PMF_STATUS_LABELS,
  type PartMemberFamily, type PartMemberStatus,
} from '../../logic/partMemberFamilies';

type StatusFilter = 'all' | PartMemberStatus;

export function FamiliesTab() {
  return (
    <TabGate>
      <FamiliesBody />
    </TabGate>
  );
}

function FamiliesBody() {
  const d = useDashboard();
  const tier = useTier();
  const { t } = useTranslation();
  const toast = useToast();
  const [unitFilter, setUnitFilter] = useState('all');
  const [statusFilter, setStatusFilter] = useState<StatusFilter>('all');
  const [sourceFilter, setSourceFilter] = useState('all');
  const [attentionOnly, setAttentionOnly] = useState(false);
  const [showDnc, setShowDnc] = useState(false);
  const [busyId, setBusyId] = useState<string | null>(null);
  const [onDateWarning, setOnDateWarning] = useState<Record<string, string>>({});
  const [dncReason, setDncReason] = useState<Record<string, string>>({});
  const [addOpen, setAddOpen] = useState(false);

  const families = d.partFamilies;
  const units = useMemo(
    () => [...new Set(families.map((f) => f.unit_name ?? 'Unknown unit'))].sort(),
    [families],
  );

  const visible = families.filter((f) => {
    if (!showDnc && f.status === 'do_not_contact') return false;
    if (unitFilter !== 'all' && (f.unit_name ?? 'Unknown unit') !== unitFilter) return false;
    if (statusFilter !== 'all' && f.status !== statusFilter) return false;
    if (sourceFilter !== 'all' && f.source !== sourceFilter) return false;
    if (attentionOnly && !needsAttention(f)) return false;
    return true;
  });
  const grouped = groupFamiliesByUnit(visible);
  const rollup = useMemo(() => rollupByUnit(families), [families]);
  const counts = useMemo(() => {
    const c: Record<string, number> = { identified: 0, love: 0, share: 0, on_date: 0, baptized: 0 };
    for (const f of families) if (c[f.status] !== undefined) c[f.status] += 1;
    return c;
  }, [families]);

  async function setStatus(f: PartMemberFamily, status: PartMemberStatus) {
    if (status === 'on_date') {
      // On Date is only honest when the non-member is being taught: an investigator in the SAME
      // unit with a planned baptism date. Block (with the reason) until Being Taught has them.
      const { reason } = findOnDateInvestigator(f, d.members);
      if (reason === 'no-investigator') {
        setOnDateWarning((w) => ({ ...w, [f.id]: t('families.onDateNoInvestigator') }));
        return;
      }
      if (reason === 'no-goal-date') {
        setOnDateWarning((w) => ({ ...w, [f.id]: t('families.onDateNoGoalDate') }));
        return;
      }
      setOnDateWarning((w) => {
        const next = { ...w };
        delete next[f.id];
        return next;
      });
    }
    const reason = status === 'do_not_contact' ? (dncReason[f.id] ?? '').trim() || undefined : undefined;
    setBusyId(f.id);
    try {
      await d.updatePartFamilyStatus(f.id, status, reason);
    } catch (e) {
      toast.show({ message: e instanceof Error ? e.message : t('families.saveFailed') });
    } finally {
      setBusyId(null);
    }
  }

  const memberFor = (f: PartMemberFamily) =>
    f.member_person_uuid
      ? d.members.find((m) => String(m['person_uuid'] ?? '') === f.member_person_uuid)
      : undefined;

  return (
    <PageScaffold
      tier={tier}
      header={
        <div className="row" style={{ justifyContent: 'space-between', alignItems: 'center' }}>
          <h1 style={{ margin: 0 }}>{t('families.title')}</h1>
          <Button onClick={() => setAddOpen((v) => !v)}>{t('families.addFamily')}</Button>
        </div>
      }
    >
      <p className="small muted" style={{ marginTop: 0 }}>{t('families.intro')}</p>

      {families.length === 0 && (
        <SectionCard title={t('families.emptyTitle')} icon="groups" iconColor="#6A1B9A">
          <p className="small" style={{ margin: 0 }}>{t('families.emptyBody')}</p>
        </SectionCard>
      )}

      {families.length > 0 && (
        <>
          <div className="row" style={{ gap: 8, flexWrap: 'wrap', marginBottom: 12 }}>
            {(['identified', 'love', 'share', 'on_date', 'baptized'] as const).map((s) => (
              <button
                key={s}
                type="button"
                className="chip"
                aria-pressed={statusFilter === s}
                onClick={() => setStatusFilter(statusFilter === s ? 'all' : s)}
                style={statusFilter === s ? { background: '#6A1B9A', color: '#fff' } : undefined}
              >
                {PMF_STATUS_LABELS[s]} · {counts[s] ?? 0}
              </button>
            ))}
          </div>

          <div className="row" style={{ gap: 8, flexWrap: 'wrap', marginBottom: 16 }}>
            <label className="field" style={{ minWidth: 140 }}>
              <span>{t('families.filterUnit')}</span>
              <select className="input" value={unitFilter} onChange={(e) => setUnitFilter(e.target.value)}>
                <option value="all">{t('families.allUnits')}</option>
                {units.map((u) => <option key={u} value={u}>{u}</option>)}
              </select>
            </label>
            <label className="field" style={{ minWidth: 140 }}>
              <span>{t('families.filterSource')}</span>
              <select className="input" value={sourceFilter} onChange={(e) => setSourceFilter(e.target.value)}>
                <option value="all">{t('families.allSources')}</option>
                <option value="lcr_list_a">{PMF_SOURCE_LABELS.lcr_list_a}</option>
                <option value="lcr_list_b">{PMF_SOURCE_LABELS.lcr_list_b}</option>
                <option value="lcr_report">{PMF_SOURCE_LABELS.lcr_report}</option>
                <option value="manual">{PMF_SOURCE_LABELS.manual}</option>
              </select>
            </label>
            <label className="list-tile" style={{ cursor: 'pointer' }}>
              <input type="checkbox" checked={attentionOnly} onChange={(e) => setAttentionOnly(e.target.checked)} />
              <span>{t('families.needsAttention')}</span>
            </label>
            <label className="list-tile" style={{ cursor: 'pointer' }}>
              <input type="checkbox" checked={showDnc} onChange={(e) => setShowDnc(e.target.checked)} />
              <span>{t('families.showDoNotContact')}</span>
            </label>
          </div>

          {addOpen && <AddFamilyForm onDone={() => setAddOpen(false)} />}

          {grouped.map(({ unitName, families: list }) => (
            <div key={unitName} style={{ marginBottom: 20 }}>
              <SectionTitle title={unitName} count={list.length} />
              {list.map((f) => {
                const member = memberFor(f);
                const calling = member ? String(member['calling'] ?? '') : '';
                return (
                  <SectionCard
                    key={f.id}
                    title={f.household_name || f.nonmember_name}
                    icon="groups"
                    iconColor="#6A1B9A"
                    trailing={<span className="chip">{PMF_STATUS_LABELS[f.status]}</span>}
                  >
                    <div className="small" style={{ marginBottom: 6 }}>
                      <strong>{t('families.member')}:</strong> {f.member_name ?? '—'}
                      {calling && calling !== 'No' && <> · {calling}</>}
                      {member && String(member['ministering_brothers_sisters'] ?? '') === 'Yes' && (
                        <> · {t('families.hasMinistering')}</>
                      )}
                    </div>
                    <div className="small" style={{ marginBottom: 10 }}>
                      <strong>{t('families.notYetMember')}:</strong> {f.nonmember_name} ·{' '}
                      {f.nonmember_role === 'spouse' ? t('families.spouse') : t('families.child')}{' '}
                      · {ageBand(f.nonmember_birth_date)} · {PMF_SOURCE_LABELS[f.source]}
                    </div>
                    {f.basis === 'unbaptized_spouse_in_home' && (
                      <p className="small" style={{ margin: '0 0 10px' }}>{t('families.basisConfirmed')}</p>
                    )}
                    {f.basis === 'spouse_not_on_record' && (
                      <p className="small" style={{ margin: '0 0 10px' }}>{t('families.basisCandidate')}</p>
                    )}
                    {f.assigned_companionship && (
                      <div className="small" style={{ marginBottom: 10 }}>
                        <strong>{t('families.companionship')}:</strong> {f.assigned_companionship}
                      </div>
                    )}
                    {f.notes && <p className="small" style={{ margin: '0 0 10px' }}>{f.notes}</p>}
                    <Segmented<PartMemberStatus>
                      ariaLabel={t('families.statusFor', { name: f.nonmember_name })}
                      value={f.status === 'do_not_contact' ? 'identified' : f.status}
                      disabled={busyId === f.id}
                      options={PMF_PIPELINE.map((s) => ({ value: s, label: PMF_STATUS_LABELS[s] }))}
                      onChange={(s) => void setStatus(f, s)}
                    />
                    {onDateWarning[f.id] && (
                      <p className="small" role="alert" style={{ color: 'var(--error)', margin: '8px 0 0' }}>
                        {onDateWarning[f.id]}
                      </p>
                    )}
                    <div className="row" style={{ gap: 8, marginTop: 10, flexWrap: 'wrap' }}>
                      {f.status === 'do_not_contact' ? (
                        <>
                          <input
                            className="input"
                            style={{ flex: 1, minWidth: 160 }}
                            placeholder={t('families.dncReasonPlaceholder')}
                            value={dncReason[f.id] ?? f.do_not_contact_reason ?? ''}
                            onChange={(e) => setDncReason((r) => ({ ...r, [f.id]: e.target.value }))}
                          />
                          <Button
                            disabled={busyId === f.id}
                            onClick={() => void setStatus(f, 'identified')}
                          >
                            {t('families.clearDnc')}
                          </Button>
                        </>
                      ) : (
                        <Button
                          disabled={busyId === f.id}
                          onClick={() => void setStatus(f, 'do_not_contact')}
                        >
                          {t('families.markDnc')}
                        </Button>
                      )}
                      <Button disabled={busyId === f.id} onClick={() => void d.deletePartFamily(f.id)}>
                        {t('families.remove')}
                      </Button>
                    </div>
                    {f.status === 'do_not_contact' && f.do_not_contact_reason && (
                      <p className="small muted" style={{ margin: '8px 0 0' }}>
                        {t('families.dncReason')}: {f.do_not_contact_reason}
                      </p>
                    )}
                  </SectionCard>
                );
              })}
            </div>
          ))}
          {visible.length === 0 && <SubtleNote text={t('families.noMatches')} />}

          <SectionTitle title={t('families.rollupTitle')} count={rollup.length} />
          <p className="small muted" style={{ marginTop: 0 }}>{t('families.rollupNote')}</p>
          <div style={{ overflowX: 'auto' }}>
            <table className="tiny" style={{ borderCollapse: 'collapse', width: '100%', minWidth: 560 }}>
              <thead>
                <tr>
                  <th style={{ textAlign: 'left', padding: '4px 8px 4px 0' }}>{t('families.rollupUnit')}</th>
                  <th style={{ padding: 4 }}>{t('families.rollupIdentified')}</th>
                  <th style={{ padding: 4 }}>{t('families.rollupLove')}</th>
                  <th style={{ padding: 4 }}>{t('families.rollupShare')}</th>
                  <th style={{ padding: 4 }}>{t('families.rollupOnDate')}</th>
                  <th style={{ padding: 4 }}>{t('families.rollupBaptized')}</th>
                  <th style={{ padding: 4 }}>{t('families.rollupDnc')}</th>
                </tr>
              </thead>
              <tbody>
                {rollup.map((r) => (
                  <tr key={r.unitName}>
                    <td style={{ padding: '4px 8px 4px 0' }}>{r.unitName}</td>
                    <td style={{ textAlign: 'center', padding: 4 }}>{r.identified}</td>
                    <td style={{ textAlign: 'center', padding: 4 }}>{r.loveFamilies} / {r.loveIndividuals}</td>
                    <td style={{ textAlign: 'center', padding: 4 }}>{r.shareFamilies} / {r.shareIndividuals}</td>
                    <td style={{ textAlign: 'center', padding: 4 }}>{r.onDate}</td>
                    <td style={{ textAlign: 'center', padding: 4 }}>{r.baptizedLastMonth}</td>
                    <td style={{ textAlign: 'center', padding: 4 }}>{r.doNotContact}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          <p className="small muted">{t('families.rollupGap')}</p>
        </>
      )}
    </PageScaffold>
  );
}

function AddFamilyForm({ onDone }: { onDone: () => void }) {
  const d = useDashboard();
  const { t } = useTranslation();
  const toast = useToast();
  const [memberName, setMemberName] = useState('');
  const [nonmemberName, setNonmemberName] = useState('');
  const [role, setRole] = useState<'spouse' | 'child'>('spouse');
  const [unitName, setUnitName] = useState('');
  const [birthDate, setBirthDate] = useState('');
  const [notes, setNotes] = useState('');
  const [busy, setBusy] = useState(false);

  const units = useMemo(
    () => [...new Set(d.members.map((m) => String(m['unit_name'] ?? '')).filter(Boolean))].sort(),
    [d.members],
  );

  async function save() {
    if (!memberName.trim() || !nonmemberName.trim() || !unitName) {
      toast.show({ message: t('families.addRequired') });
      return;
    }
    setBusy(true);
    try {
      const member = d.members.find(
        (m) => String(m['name'] ?? '').trim().toLowerCase() === memberName.trim().toLowerCase()
          && String(m['unit_name'] ?? '') === unitName,
      );
      await d.addPartFamily({
        unitId: member ? (member['unit_id'] as string | null) ?? null : null,
        unitName,
        memberPersonUuid: member ? String(member['person_uuid'] ?? '') : null,
        memberName: memberName.trim(),
        nonmemberName: nonmemberName.trim(),
        nonmemberRole: role,
        nonmemberBirthDate: birthDate || null,
        notes,
      });
      onDone();
    } catch (e) {
      toast.show({ message: e instanceof Error ? e.message : t('families.saveFailed') });
    } finally {
      setBusy(false);
    }
  }

  return (
    <SectionCard title={t('families.addTitle')} icon="person_add" iconColor="#6A1B9A">
      <p className="small muted" style={{ marginTop: 0 }}>{t('families.addHelp')}</p>
      <label className="field">
        <span>{t('families.member')}</span>
        <input className="input" value={memberName} onChange={(e) => setMemberName(e.target.value)} placeholder={t('families.memberPlaceholder')} />
      </label>
      <label className="field">
        <span>{t('families.notYetMember')}</span>
        <input className="input" value={nonmemberName} onChange={(e) => setNonmemberName(e.target.value)} placeholder={t('families.nonmemberPlaceholder')} />
      </label>
      <label className="field">
        <span>{t('families.role')}</span>
        <select className="input" value={role} onChange={(e) => setRole(e.target.value as 'spouse' | 'child')}>
          <option value="spouse">{t('families.spouse')}</option>
          <option value="child">{t('families.child')}</option>
        </select>
      </label>
      <label className="field">
        <span>{t('families.filterUnit')}</span>
        <select className="input" value={unitName} onChange={(e) => setUnitName(e.target.value)}>
          <option value="">{t('families.chooseUnit')}</option>
          {units.map((u) => <option key={u} value={u}>{u}</option>)}
        </select>
      </label>
      <label className="field">
        <span>{t('families.birthDateOptional')}</span>
        <input className="input" type="date" value={birthDate} onChange={(e) => setBirthDate(e.target.value)} />
      </label>
      <label className="field">
        <span>{t('families.notes')}</span>
        <textarea className="textarea" rows={2} value={notes} onChange={(e) => setNotes(e.target.value)} />
      </label>
      <div className="row" style={{ gap: 8 }}>
        <Button variant="filled" disabled={busy} onClick={() => void save()}>{t('families.save')}</Button>
        <Button disabled={busy} onClick={onDone}>{t('families.cancel')}</Button>
      </div>
    </SectionCard>
  );
}
