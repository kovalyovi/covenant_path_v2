// Settings no longer lists Table/Leaders (2026-11-08): they moved to the app-bar "⋯" menu as
// URL-landable side sheets. Settings keeps Appearance / Preferences / Security / Support / About /
// Account — the Views section is gone.

import { afterEach, describe, expect, it, vi } from 'vitest';
import { render, screen } from '@testing-library/react';

vi.mock('../lib/supabase', () => ({
  supabase: {
    auth: { getUser: async () => ({ data: { user: { email: 'a@b.c' } } }) },
    from: () => ({ select: () => Promise.resolve({ data: [], error: null }) }),
  },
  currentAccessToken: async () => 'token',
}));
vi.mock('../hooks/useDashboard', () => ({
  useDashboard: () => ({
    showNotes: false, setShowNotes: () => {}, isAdmin: false, stakeName: 'Stake',
  }),
}));
vi.mock('../hooks/useAuth', () => ({ signOut: async () => {} }));
vi.mock('./DashboardShell', () => ({
  ContactDialog: () => null,
  FeedbackDialog: () => null,
  addPasskey: async () => {},
}));

import '../i18n';
import { ToastProvider } from '../components/Toast';
import { ThemeProvider } from '../hooks/useTheme';
import { SettingsPage } from '../pages/SettingsPage';

// jsdom has no matchMedia; the ThemeProvider reads the OS theme through it.
Object.defineProperty(window, 'matchMedia', {
  writable: true,
  value: (query: string) => ({
    matches: false,
    media: query,
    onchange: null,
    addListener: () => {},
    removeListener: () => {},
    addEventListener: () => {},
    removeEventListener: () => {},
    dispatchEvent: () => false,
  }),
});

afterEach(() => {
  vi.clearAllMocks();
});

describe('SettingsPage', () => {
  it('does not list Table or Leaders — they live in the app-bar menu now', async () => {
    render(
      <ToastProvider>
        <ThemeProvider>
          <SettingsPage />
        </ThemeProvider>
      </ToastProvider>,
    );
    // The settings list itself rendered (Appearance section is first).
    expect(await screen.findByText('Appearance')).toBeInTheDocument();
    expect(screen.queryByText('Table')).not.toBeInTheDocument();
    expect(screen.queryByText('Leaders')).not.toBeInTheDocument();
  });
});
