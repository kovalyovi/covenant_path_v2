// App-wide light/dark/system preference, persisted to localStorage and applied to <html data-theme>.
// Mirrors apps/viewer/lib/theme/app_theme.dart (ThemeController) incl. the system → light → dark cycle.

import { createContext, useCallback, useContext, useEffect, useMemo, useState, type ReactNode } from 'react';

export type ThemeMode = 'system' | 'light' | 'dark';
export type ThemeLook = 'classic' | 'refined';
const KEY = 'theme_mode';
const LOOK_KEY = 'theme_look';

interface ThemeApi {
  mode: ThemeMode;
  label: string;
  setMode: (m: ThemeMode) => void;
  cycle: () => void;
  /** #6a commit-2: an alternate "Refined" visual style, previewed live + chosen by the user. */
  look: ThemeLook;
  setLook: (l: ThemeLook) => void;
}

const ThemeContext = createContext<ThemeApi | null>(null);

function resolve(mode: ThemeMode): 'light' | 'dark' {
  if (mode === 'system') {
    return window.matchMedia('(prefers-color-scheme: dark)').matches ? 'dark' : 'light';
  }
  return mode;
}

function apply(mode: ThemeMode) {
  document.documentElement.setAttribute('data-theme', resolve(mode));
}

function load(): ThemeMode {
  const v = localStorage.getItem(KEY);
  return v === 'light' || v === 'dark' || v === 'system' ? v : 'system';
}

function loadLook(): ThemeLook {
  return localStorage.getItem(LOOK_KEY) === 'refined' ? 'refined' : 'classic';
}

export function ThemeProvider({ children }: { children: ReactNode }) {
  const [mode, setModeState] = useState<ThemeMode>(() => load());
  const [look, setLookState] = useState<ThemeLook>(() => loadLook());

  useEffect(() => {
    apply(mode);
  }, [mode]);

  // #6a commit-2: the alternate visual style is a `data-look` attribute the CSS keys off.
  useEffect(() => {
    document.documentElement.setAttribute('data-look', look);
  }, [look]);

  // Track OS changes while in system mode.
  useEffect(() => {
    if (mode !== 'system') return;
    const mq = window.matchMedia('(prefers-color-scheme: dark)');
    const onChange = () => apply('system');
    mq.addEventListener('change', onChange);
    return () => mq.removeEventListener('change', onChange);
  }, [mode]);

  const setMode = useCallback((m: ThemeMode) => {
    localStorage.setItem(KEY, m);
    setModeState(m);
  }, []);

  const cycle = useCallback(() => {
    setMode(mode === 'system' ? 'light' : mode === 'light' ? 'dark' : 'system');
  }, [mode, setMode]);

  const setLook = useCallback((l: ThemeLook) => {
    localStorage.setItem(LOOK_KEY, l);
    setLookState(l);
  }, []);

  const label = mode === 'system' ? 'System' : mode === 'light' ? 'Light' : 'Dark';

  const api = useMemo<ThemeApi>(() => ({ mode, label, setMode, cycle, look, setLook }), [mode, label, setMode, cycle, look, setLook]);
  return <ThemeContext.Provider value={api}>{children}</ThemeContext.Provider>;
}

export function useTheme(): ThemeApi {
  const ctx = useContext(ThemeContext);
  if (!ctx) throw new Error('useTheme must be used within ThemeProvider');
  return ctx;
}
