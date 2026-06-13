// The dashboard data layer — the React port of `_DashboardPageState` (apps/viewer/lib/dashboard_page.dart).
// Resolves which single stake to show BEFORE the first member query (a leader sees only their stake;
// multi-stake power users get a switcher), loads members scoped to that stake (RLS is still the gate
// underneath), polls sync_state every ~5s while a sync runs so the banner self-clears (N3), and
// loads enrollment status for the empty state. Exposed via context so the shell + every tab share it.

import {
  createContext, useCallback, useContext, useEffect, useMemo, useRef, useState, type ReactNode,
} from 'react';
import { supabase } from '../lib/supabase';
import { MEMBER_COLUMNS, type Member } from '../lib/member';
import { buildNotesIndex, type NoteRow, type MemberNoteRow, type NoteSummary } from '../logic/notes';
import { broker, type EnrollmentStatus } from '../lib/broker';
import { getShowNotes, setShowNotes as persistShowNotes } from '../lib/prefs';

const STAKE_KEY = 'current_stake_id';
const SYNC_GUARD_MIN = 30; // ignore a 'running' state older than this (crashed run that never marked 'done')

export interface StakeRow {
  id: string;
  name?: string | null;
  last_synced_at?: string | null;
  sync_state?: string | null;
  sync_started_at?: string | null;
  missionaries?: unknown;
}

type Missionaries = Record<string, Array<Record<string, unknown>>>;

interface DashboardState {
  loading: boolean;
  error: string | null;
  members: Member[];
  /** person_uuid -> the single editable leader note, for the list-row note lines. */
  notes: Record<string, NoteSummary>;
  /** Re-pull the notes index (after editing a note on the detail page or via long-press). */
  reloadNotes: () => Promise<void>;
  /** Whether the main screen shows member notes (default true; persisted per the global pref). */
  showNotes: boolean;
  setShowNotes: (on: boolean) => void;
  stakes: StakeRow[];
  currentStakeId: string | null;
  stakeName: string | null;
  lastSynced: string | null;
  syncing: boolean;
  syncStartedAt: string | null;
  missionaries: Missionaries;
  isAdmin: boolean;
  enrollStatus: EnrollmentStatus | null;
  switchStake: (id: string) => void;
  refresh: () => Promise<void>;
  /** Optimistically flip into the syncing state (used right after "Sync now"). */
  markSyncing: () => void;
  reloadStakes: () => Promise<void>;
  reloadEnrollStatus: () => Promise<void>;
  setEnrollStatus: (s: EnrollmentStatus | null) => void;
  /** In-app Church re-authorization dialog (stale/revoked credential, or first-time setup) — keeps
   *  the user signed in instead of bouncing them to the login screen. */
  reauthOpen: boolean;
  openReauth: () => void;
  closeReauth: () => void;
}

const Ctx = createContext<DashboardState | null>(null);

function parseMissionaries(s: StakeRow): Missionaries {
  const out: Missionaries = {};
  const m = s.missionaries;
  if (m && typeof m === 'object' && !Array.isArray(m)) {
    for (const [k, v] of Object.entries(m as Record<string, unknown>)) {
      if (Array.isArray(v)) {
        out[k] = v.filter((e) => e && typeof e === 'object') as Array<Record<string, unknown>>;
      }
    }
  }
  return out;
}

function isRunning(s: StakeRow): { running: boolean; startedAt: string | null } {
  if (s.sync_state !== 'running') return { running: false, startedAt: null };
  const started = s.sync_started_at ? new Date(s.sync_started_at) : null;
  if (started && !Number.isNaN(started.getTime())) {
    const mins = (Date.now() - started.getTime()) / 60000;
    if (mins < SYNC_GUARD_MIN) return { running: true, startedAt: s.sync_started_at ?? null };
  }
  return { running: false, startedAt: null };
}

const STAKE_COLS = 'id, name, last_synced_at, sync_state, sync_started_at, missionaries';

export function DashboardProvider({ children }: { children: ReactNode }) {
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [members, setMembers] = useState<Member[]>([]);
  const [notes, setNotes] = useState<Record<string, NoteSummary>>({});
  const [stakes, setStakes] = useState<StakeRow[]>([]);
  const [currentStakeId, setCurrentStakeId] = useState<string | null>(null);
  const [stakeName, setStakeName] = useState<string | null>(null);
  const [lastSynced, setLastSynced] = useState<string | null>(null);
  const [syncing, setSyncing] = useState(false);
  const [syncStartedAt, setSyncStartedAt] = useState<string | null>(null);
  const [missionaries, setMissionaries] = useState<Missionaries>({});
  const [isAdmin, setIsAdmin] = useState(false);
  const [enrollStatus, setEnrollStatus] = useState<EnrollmentStatus | null>(null);
  const [showNotes, setShowNotesState] = useState<boolean>(() => getShowNotes());

  const setShowNotes = useCallback((on: boolean) => {
    setShowNotesState(on);
    persistShowNotes(on);
  }, []);

  const pollRef = useRef<number | null>(null);
  const stakesRef = useRef<StakeRow[]>([]);
  const currentIdRef = useRef<string | null>(null);
  const syncingRef = useRef(false);

  stakesRef.current = stakes;
  currentIdRef.current = currentStakeId;
  syncingRef.current = syncing;

  const loadMembers = useCallback(async (stakeId: string | null): Promise<Member[]> => {
    // Scope to the selected stake — never the RLS union of every stake the viewer has a role in.
    const base = supabase.from('members').select(MEMBER_COLUMNS);
    const scoped = stakeId != null ? base.eq('stake_id', stakeId) : base;
    const { data, error: e } = await scoped.order('unit_name').order('name');
    if (e) throw e;
    return (data ?? []) as unknown as Member[];
  }, []);

  const loadNotes = useCallback(async (stakeId: string | null): Promise<Record<string, NoteSummary>> => {
    // The SINGLE note per member (member_notes) WINS; legacy member_comments threads are folded in
    // for members not yet migrated, so nothing is lost. Both bulk-queried per stake (RLS-scoped like
    // members). Best-effort: a notes hiccup must never fail the member load.
    try {
      const noteBase = supabase.from('member_notes').select('member_person_uuid, note, updated_at');
      const cmtBase = supabase.from('member_comments').select('member_person_uuid, body, author_name, author_email, created_at');
      const [notesRes, cmtRes] = await Promise.all([
        stakeId != null ? noteBase.eq('stake_id', stakeId) : noteBase,
        stakeId != null ? cmtBase.eq('stake_id', stakeId) : cmtBase,
      ]);
      return buildNotesIndex(
        (notesRes.data ?? []) as MemberNoteRow[],
        (cmtRes.data ?? []) as NoteRow[],
      );
    } catch {
      return {};
    }
  }, []);

  const reloadNotes = useCallback(async () => {
    setNotes(await loadNotes(currentIdRef.current));
  }, [loadNotes]);

  const applyCurrentStake = useCallback((list: StakeRow[], id: string | null) => {
    if (list.length === 0) return;
    const s = list.find((e) => e.id === id) ?? list[0];
    const { running, startedAt } = isRunning(s);
    setStakeName(s.name ?? null);
    setLastSynced(s.last_synced_at ?? null);
    setMissionaries(parseMissionaries(s));
    setSyncing(running);
    setSyncStartedAt(startedAt);
  }, []);

  const reloadEnrollStatus = useCallback(async () => {
    if (!broker.available) return;
    try {
      const s = await broker.enrollmentStatus();
      setEnrollStatus(s);
    } catch {
      /* leave null */
    }
  }, []);

  const reloadStakes = useCallback(async () => {
    try {
      const { data } = await supabase.from('stakes').select(STAKE_COLS);
      const list = ((data ?? []) as StakeRow[]).slice();
      if (list.length === 0) return;
      // freshest stake first, so an unset default lands on the most recent scrape
      list.sort((a, b) => String(b.last_synced_at ?? '').localeCompare(String(a.last_synced_at ?? '')));
      let current = currentIdRef.current;
      if (current == null) current = localStorage.getItem(STAKE_KEY);
      if (current == null || !list.some((s) => s.id === current)) current = list[0].id;
      setStakes(list);
      setCurrentStakeId(current);
      applyCurrentStake(list, current);
    } catch {
      /* ignore */
    }
  }, [applyCurrentStake]);

  const pollSyncState = useCallback(async () => {
    const id = currentIdRef.current;
    if (id == null) return;
    try {
      const { data } = await supabase.from('stakes').select(STAKE_COLS).eq('id', id);
      const list = (data ?? []) as StakeRow[];
      if (list.length === 0) return;
      const merged = stakesRef.current.map((s) => (s.id === id ? list[0] : s));
      setStakes(merged);
      const wasSyncing = syncingRef.current;
      applyCurrentStake(merged, id);
      const { running } = isRunning(list[0]);
      if (wasSyncing && !running) {
        // sync finished → pull the fresh members
        try {
          setMembers(await loadMembers(id));
        } catch {
          /* keep stale members on error */
        }
      }
    } catch {
      /* ignore */
    }
  }, [applyCurrentStake, loadMembers]);

  // Manage the N3 poll lifecycle: run a 5s interval only while syncing.
  useEffect(() => {
    if (syncing && pollRef.current == null) {
      pollRef.current = window.setInterval(() => void pollSyncState(), 5000);
    } else if (!syncing && pollRef.current != null) {
      window.clearInterval(pollRef.current);
      pollRef.current = null;
    }
    return () => {
      if (pollRef.current != null) {
        window.clearInterval(pollRef.current);
        pollRef.current = null;
      }
    };
  }, [syncing, pollSyncState]);

  // Bootstrap: resolve stakes, then load members; prefetch enrollment status in the background once
  // the page is ready (#11) so opening Sync settings is instant — and it's also needed for the empty state.
  useEffect(() => {
    let active = true;
    (async () => {
      setLoading(true);
      setError(null);
      await reloadStakes();
      try {
        const [rows, nts] = await Promise.all([
          loadMembers(currentIdRef.current), loadNotes(currentIdRef.current),
        ]);
        if (!active) return;
        setMembers(rows);
        setNotes(nts);
        // Not awaited — never delays first paint; caches enrollStatus for the Sync-settings sheet (#11).
        void reloadEnrollStatus();
      } catch (e) {
        if (active) setError(e instanceof Error ? e.message : String(e));
      } finally {
        if (active) setLoading(false);
      }
    })();
    // is_admin check (best-effort)
    supabase.rpc('is_admin').then(({ data }) => {
      if (active && data === true) setIsAdmin(true);
    }, () => {});
    return () => {
      active = false;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const refresh = useCallback(async () => {
    setError(null);
    try {
      const [rows, nts] = await Promise.all([
        loadMembers(currentIdRef.current), loadNotes(currentIdRef.current),
      ]);
      setMembers(rows);
      setNotes(nts);
      if (rows.length === 0) void reloadEnrollStatus();
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    }
  }, [loadMembers, loadNotes, reloadEnrollStatus]);

  const switchStake = useCallback(
    (id: string) => {
      if (id === currentIdRef.current) return;
      setCurrentStakeId(id);
      applyCurrentStake(stakesRef.current, id);
      try {
        localStorage.setItem(STAKE_KEY, id);
      } catch {
        /* ignore */
      }
      setLoading(true);
      Promise.all([loadMembers(id), loadNotes(id)])
        .then(([rows, nts]) => {
          setMembers(rows);
          setNotes(nts);
          if (rows.length === 0) void reloadEnrollStatus();
        })
        .catch((e) => setError(e instanceof Error ? e.message : String(e)))
        .finally(() => setLoading(false));
    },
    [applyCurrentStake, loadMembers, loadNotes, reloadEnrollStatus],
  );

  const markSyncing = useCallback(() => {
    setSyncing(true);
    setSyncStartedAt(new Date().toISOString());
    // reconcile with the real stakes.sync_state shortly after the job marks itself running
    window.setTimeout(() => void reloadStakes(), 8000);
  }, [reloadStakes]);

  const [reauthOpen, setReauthOpen] = useState(false);
  const openReauth = useCallback(() => setReauthOpen(true), []);
  const closeReauth = useCallback(() => setReauthOpen(false), []);

  const value = useMemo<DashboardState>(
    () => ({
      loading, error, members, notes, reloadNotes, showNotes, setShowNotes,
      stakes, currentStakeId, stakeName, lastSynced,
      syncing, syncStartedAt, missionaries, isAdmin, enrollStatus, switchStake, refresh, markSyncing,
      reloadStakes, reloadEnrollStatus, setEnrollStatus,
      reauthOpen, openReauth, closeReauth,
    }),
    [
      loading, error, members, notes, reloadNotes, showNotes, setShowNotes,
      stakes, currentStakeId, stakeName, lastSynced,
      syncing, syncStartedAt, missionaries, isAdmin, enrollStatus, switchStake, refresh, markSyncing,
      reloadStakes, reloadEnrollStatus, reauthOpen, openReauth, closeReauth,
    ],
  );

  return <Ctx.Provider value={value}>{children}</Ctx.Provider>;
}

export function useDashboard(): DashboardState {
  const ctx = useContext(Ctx);
  if (!ctx) throw new Error('useDashboard must be used within DashboardProvider');
  return ctx;
}
