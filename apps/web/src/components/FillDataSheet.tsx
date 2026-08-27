// Fill-data side sheet (2026-07-06): opened from a ⚠ "not available" table cell (or the
// patriarchal banner). Shows exactly WHICH profile fields are missing for how many members
// (GET /auth/profile-refresh/status), explains why the daily sync can't pull them (they need a
// live signed-in Church session), and offers the fix: POST /auth/profile-refresh — which fills
// everything off the STORED session when it's still live, or answers needs_reauth so we open the
// ReauthDialog (whose enroll path runs the same fill off the fresh session). While a fill runs,
// the sheet polls status and shows progress; on completion it reloads the members so the ⚠s clear.
import { useCallback, useEffect, useRef, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { Modal } from './Modal';
import { Icon } from './Icon';
import { Button } from './ui';
import { broker } from '../lib/broker';
import type { EnrollmentStatus } from '../lib/broker';

export interface FillStatus {
  running: boolean;
  progress: { state?: string; total?: number; done?: number; filled?: number } | null;
  /** The last run ended having filled NOTHING — a dead Church session, not a success. */
  needsReauth: boolean;
  membersWithGaps: number;
  missing: Record<string, number>;
  canRefresh: boolean;
  lastRefresh: { run_at?: string; payload?: { filled?: number; total?: number } } | null;
}

function statusFromJson(j: Record<string, unknown>): FillStatus {
  return {
    running: j['running'] === true,
    progress: (j['progress'] as FillStatus['progress']) ?? null,
    needsReauth: j['needs_reauth'] === true,
    membersWithGaps: Number(j['members_with_gaps'] ?? 0) || 0,
    missing: (j['missing'] as Record<string, number>) ?? {},
    canRefresh: j['can_refresh'] !== false,
    lastRefresh: (j['last_refresh'] as FillStatus['lastRefresh']) ?? null,
  };
}

const POLL_MS = 2500;

export function FillDataSheet({
  open, onClose, onReauth, enrollStatus, onFilled,
}: {
  open: boolean;
  onClose: () => void;
  /** Opens the in-app ReauthDialog (the fill re-starts automatically off the fresh session). */
  onReauth: () => void;
  enrollStatus: EnrollmentStatus | null;
  /** Called once when a running fill completes, so the caller reloads members (the ⚠s clear). */
  onFilled: () => void;
}) {
  const { t } = useTranslation();
  const [status, setStatus] = useState<FillStatus | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [starting, setStarting] = useState(false);
  const [needsReauth, setNeedsReauth] = useState(false);
  const [finished, setFinished] = useState<{ filled: number; total: number } | null>(null);
  const wasRunning = useRef(false);
  const onFilledRef = useRef(onFilled);
  onFilledRef.current = onFilled;

  const isLeader = enrollStatus?.viewerIsStakeLeader === true && broker.available;

  const load = useCallback(async (quiet = false) => {
    if (!quiet) setLoading(true);
    try {
      const s = statusFromJson(await broker.profileRefreshStatus());
      setStatus(s);
      setError(null);
      if (s.needsReauth) setNeedsReauth(true);
      // Fire the reload exactly once, on the running→finished edge.
      if (wasRunning.current && !s.running) {
        wasRunning.current = false;
        const p = s.progress;
        if (p?.state === 'done') {
          setFinished({ filled: p.filled ?? 0, total: p.total ?? 0 });
          onFilledRef.current();
        } else if (p?.state === 'needs_reauth') {
          // The run finished but filled nothing — the stored session is dead. Ask for the one thing
          // that fixes it instead of showing a completed-looking "0 of N updated".
          setNeedsReauth(true);
        }
      } else if (s.running) {
        wasRunning.current = true;
        setFinished(null);
      }
    } catch (e) {
      setError(e instanceof Error ? e.message : t('fillData.statusError'));
    } finally {
      if (!quiet) setLoading(false);
    }
  }, [t]);

  // Load on open (leaders only — the status route is stake-leader-gated); poll while running or
  // while the re-auth dialog may be filling in the background.
  useEffect(() => {
    if (!open || !isLeader) return;
    setFinished(null);
    setNeedsReauth(false);
    void load();
    const id = setInterval(() => {
      // Quiet polls: refresh counts/progress without flashing the sheet's spinner.
      void load(true);
    }, POLL_MS);
    return () => clearInterval(id);
  }, [open, isLeader, load]);

  const start = useCallback(async () => {
    setStarting(true);
    setError(null);
    try {
      const r = await broker.profileRefreshStart();
      const st = String(r['status'] ?? '');
      if (st === 'needs_reauth') {
        setNeedsReauth(true);
      } else if (st === 'started' || st === 'running') {
        wasRunning.current = true;
        setStatus((s) => (s ? { ...s, running: true } : s));
        void load(true);
      } else if (st === 'nothing_to_fill') {
        void load(true);
      }
    } catch (e) {
      setError(e instanceof Error ? e.message : t('fillData.failed'));
    } finally {
      setStarting(false);
    }
  }, [load, t]);

  const missingRows = Object.entries(status?.missing ?? {}).sort((a, b) => b[1] - a[1]);
  const prog = status?.progress;
  const running = status?.running === true;
  const pct = running && prog?.total ? Math.round(((prog.done ?? 0) / prog.total) * 100) : null;
  const noAccess = enrollStatus?.credential?.canRefreshPatriarchal === false || status?.canRefresh === false;

  let lastRun: string | null = null;
  if (status?.lastRefresh?.run_at) {
    const p = status.lastRefresh.payload ?? {};
    const when = new Date(status.lastRefresh.run_at).toLocaleString();
    // "0 of 8 updated" reads like a completed run that simply found nothing. It never means that —
    // it means the Church session was dead. Say so.
    lastRun = (p.total ?? 0) > 0 && (p.filled ?? 0) === 0
      ? t('fillData.lastRunNone', { when })
      : t('fillData.lastRun', { when, filled: p.filled ?? 0, total: p.total ?? 0 });
  }

  return (
    <Modal open={open} onClose={onClose} title={t('fillData.title')} side loading={loading && !status}>
      <div className="form-stack" style={{ gap: 14 }}>
        <p className="tiny" style={{ margin: 0, opacity: 0.85 }}>{t('fillData.intro')}</p>

        {!isLeader && <p style={{ margin: 0 }}>{t('fillData.notLeader')}</p>}

        {isLeader && noAccess && (
          <div className="banner banner--info" role="status">{t('fillData.noAccess')}</div>
        )}

        {isLeader && error && (
          <div className="banner banner--error" role="alert">{error}</div>
        )}

        {isLeader && status && missingRows.length > 0 && (
          <div>
            <div className="row" style={{ gap: 6, fontWeight: 600, marginBottom: 6 }}>
              <Icon name="warning" size={16} color="#f9a825" />
              {t('fillData.missingTitle')}
            </div>
            <table className="tiny" style={{ borderCollapse: 'collapse', width: '100%' }}>
              <tbody>
                {missingRows.map(([field, count]) => (
                  <tr key={field}>
                    <td style={{ padding: '3px 0' }}>{t(`fillData.fields.${field}`, field)}</td>
                    <td style={{ textAlign: 'right', fontVariantNumeric: 'tabular-nums' }}>{count}</td>
                  </tr>
                ))}
              </tbody>
            </table>
            <p className="tiny" style={{ margin: '6px 0 0', opacity: 0.75 }}>
              {t('fillData.membersWithGaps', { count: status.membersWithGaps })}
            </p>
          </div>
        )}

        {isLeader && status && !running && missingRows.length === 0 && !finished && (
          <div className="banner banner--info" role="status">{t('fillData.allFilled')}</div>
        )}

        {isLeader && running && (
          <div>
            <div className="tiny" style={{ marginBottom: 6 }}>
              {t('fillData.progress', {
                done: prog?.done ?? 0, total: prog?.total ?? 0, filled: prog?.filled ?? 0,
              })}
            </div>
            <div style={{ height: 6, borderRadius: 3, background: 'var(--surface-variant, #e0e0e0)' }}>
              <div
                style={{
                  height: 6, borderRadius: 3, background: 'var(--primary)',
                  width: `${pct ?? 5}%`, transition: 'width .4s ease',
                }}
              />
            </div>
          </div>
        )}

        {isLeader && finished && (
          <div className="banner banner--info" role="status">
            {t('fillData.done', { filled: finished.filled, total: finished.total })}
          </div>
        )}

        {isLeader && prog?.state === 'failed' && !running && (
          <div className="banner banner--error" role="alert">{t('fillData.failed')}</div>
        )}

        {isLeader && needsReauth && (
          <div className="banner banner--info" role="status">{t('fillData.needsReauth')}</div>
        )}

        {isLeader && !noAccess && (
          needsReauth ? (
            <Button onClick={onReauth}>{t('fillData.reauthNow')}</Button>
          ) : (
            <Button onClick={() => void start()} disabled={starting || running || missingRows.length === 0}>
              {starting ? t('fillData.starting') : t('fillData.fillNow')}
            </Button>
          )
        )}

        {isLeader && lastRun && (
          <p className="tiny" style={{ margin: 0, opacity: 0.65 }}>{lastRun}</p>
        )}
      </div>
    </Modal>
  );
}
