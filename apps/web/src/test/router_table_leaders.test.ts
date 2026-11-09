// /table and /leadership are URL-landable overlay sheets now (2026-11-08): the route renders the
// last tab as backdrop (BackgroundTab) and DashboardShell overlays the matching sheet — the old
// redirect to /settings is gone. This pins the route shape so a future move can't silently send
// Table/Leaders back into Settings.

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

type RouteNode = { path?: string; element?: { type?: unknown }; children?: RouteNode[] };

function findRoute(nodes: RouteNode[] | undefined, path: string): RouteNode | undefined {
  for (const n of nodes ?? []) {
    if (n.path === path) return n;
    const found = findRoute(n.children, path);
    if (found) return found;
  }
  return undefined;
}

describe('router', () => {
  it('/table and /leadership render the overlay backdrop, not a redirect to /settings', () => {
    for (const path of ['table', 'leadership']) {
      const route = findRoute(router.routes as RouteNode[], path);
      expect(route, `/${path} route exists`).toBeDefined();
      const type = route?.element?.type as { name?: string } | undefined;
      expect(type, `/${path} is not a redirect`).not.toBe(Navigate);
      expect(type?.name, `/${path} renders the overlay backdrop`).toBe('BackgroundTab');
    }
  });
});
