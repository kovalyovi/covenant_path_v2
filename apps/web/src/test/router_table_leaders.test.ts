// /table and /leadership render INLINE as pages now (2026-11-08): the route renders the tab
// component itself in the main content — not a side sheet (D90) and not a redirect to /settings
// (D81). This pins the route shape so a future move can't silently send Table/Leaders back into a
// sheet or into Settings.

import { describe, expect, it, vi } from 'vitest';
import { Navigate } from 'react-router-dom';

vi.mock('../lib/config', () => ({ brokerUrl: 'https://broker.test' }));
vi.mock('../lib/supabase', () => ({
  supabase: {},
  currentAccessToken: async () => 'token',
}));
vi.mock('../lib/broker', () => ({ broker: { available: true } }));
vi.mock('../hooks/useAuth', () => ({
  useAuth: () => ({ session: null, loading: false }),
  signOut: async () => {},
}));

import { router } from '../router';

type RouteNode = { path?: string; element?: { type?: { name?: string }; props?: { children?: { type?: { name?: string } } } }; children?: RouteNode[] };

function findRoute(nodes: RouteNode[] | undefined, path: string): RouteNode | undefined {
  for (const n of nodes ?? []) {
    if (n.path === path) return n;
    const found = findRoute(n.children, path);
    if (found) return found;
  }
  return undefined;
}

describe('router', () => {
  it('/table renders the table inline and /leadership renders the leaders inline', () => {
    const table = findRoute(router.routes as RouteNode[], 'table');
    expect(table, '/table route exists').toBeDefined();
    expect(table?.element?.type, '/table is not a redirect').not.toBe(Navigate);
    expect(table?.element?.type?.name, '/table renders the table inline').toBe('TableTab');

    const leaders = findRoute(router.routes as RouteNode[], 'leadership');
    expect(leaders, '/leadership route exists').toBeDefined();
    expect(leaders?.element?.type, '/leadership is not a redirect').not.toBe(Navigate);
    // LeadershipTab is code-split behind the LazyRoute wrapper (same shape as the /kpis tab) —
    // the wrapper's child is the lazy tab, not a sheet backdrop.
    expect(leaders?.element?.type?.name, '/leadership renders inline via the lazy route').toBe('LazyRoute');
  });
});
