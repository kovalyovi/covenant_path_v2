// App routing (React Router v7) — mirrors the Flutter go_router map (R1). Top-level: `/login` and
// `/` (the dashboard shell) with the 5 tab children `/baptisms` · `/golden-hour` · `/needs` ·
// `/kpis` · `/table`, plus `/person/:id`, `/settings`, `/invite`, `/admin`. Auth is enforced by a
// guard that re-evaluates on every Supabase auth change (sign-in / sign-out / token refresh):
// no session → /login; an authed user at /login → /. A no-access member is blocked at login (N2),
// so they never reach a session here.
//
// Settings, Admin AND Person detail are SIDE/BOTTOM SHEETS that overlay the dashboard (not standalone
// pages), yet stay URL-landable: `/settings` · `/admin` · `/admin/:section` · `/person/:id` are children
// of the DashboardShell that render the last-visited tab underneath (via BackgroundTab) with the sheet
// open on top — so a refresh or a deep link lands on the dashboard + the open sheet, and closing the
// sheet navigates back to the underlying tab. The shell reads the pathname to decide which to overlay.

import { lazy, Suspense } from 'react';
import { createBrowserRouter, Navigate, Outlet, useLocation } from 'react-router-dom';
import { useAuth } from './hooks/useAuth';
import { DashboardProvider } from './hooks/useDashboard';
import { Spinner } from './components/ui';
import { lazyWithReload } from './lib/lazyReload';
import { RouteError } from './pages/RouteError';
import { LoginPage } from './pages/LoginPage';
import { DashboardShell } from './pages/DashboardShell';
import { MaintenanceGate } from './components/MaintenanceGate';
import { BaptismsTab } from './pages/tabs/BaptismsTab';
import { GoldenHourTab } from './pages/tabs/GoldenHourTab';
import { NeedsTab } from './pages/tabs/NeedsTab';
import { TableTab } from './pages/tabs/TableTab';
import { ReauthPage } from './pages/ReauthPage';
import { InvitePage } from './pages/InvitePage';

// Code-split the chart-heavy KPIs tab (Recharts) out of the initial bundle, so first paint of the
// dashboard stays lean. lazyWithReload reloads the page once when a chunk 404s because a deploy
// replaced the hashed assets under an open tab. (The Admin console is lazy-loaded by DashboardShell,
// where it now renders as a side sheet.)
const KpisTab = lazy(lazyWithReload(() => import('./pages/tabs/KpisTab').then((m) => ({ default: m.KpisTab }))));
const LeadershipTab = lazy(lazyWithReload(() => import('./pages/tabs/LeadershipTab').then((m) => ({ default: m.LeadershipTab }))));

function LazyRoute({ children }: { children: React.ReactNode }) {
  return <Suspense fallback={<FullScreenLoader />}>{children}</Suspense>;
}

// The Settings/Admin side sheets overlay the dashboard but must show WHATEVER tab the user was on
// underneath (not always Baptisms). DashboardShell records the last real tab path in sessionStorage;
// these routes render that tab as the backdrop so opening a sheet doesn't reset the view.
export const LAST_TAB_KEY = 'cp:lastTab';
const BG_TABS: Record<string, React.ReactNode> = {
  '/baptisms': <BaptismsTab />,
  '/golden-hour': <GoldenHourTab />,
  '/needs': <NeedsTab />,
  '/kpis': <LazyRoute><KpisTab /></LazyRoute>,
  '/table': <TableTab />,
  '/leadership': <LazyRoute><LeadershipTab /></LazyRoute>,
};

function BackgroundTab() {
  let last = '/baptisms';
  try { last = sessionStorage.getItem(LAST_TAB_KEY) || '/baptisms'; } catch { /* private mode */ }
  return <>{BG_TABS[last] ?? <BaptismsTab />}</>;
}

function FullScreenLoader() {
  return (
    <div className="center-col" style={{ minHeight: '100vh' }}>
      <Spinner large />
    </div>
  );
}

/** Gate that requires a Supabase session; redirects to /login otherwise. Wraps the authed area in
 * the DashboardProvider so the shell + tabs + person detail all share the loaded data. */
function RequireAuth() {
  const { session, loading } = useAuth();
  const location = useLocation();
  if (loading) return <FullScreenLoader />;
  if (!session) return <Navigate to="/login" replace state={{ from: location.pathname }} />;
  return (
    <DashboardProvider>
      <MaintenanceGate>
        <Outlet />
      </MaintenanceGate>
    </DashboardProvider>
  );
}

/** /login redirects to / when already signed in (mirrors the go_router `atLogin -> '/'`). */
function LoginRoute() {
  const { session, loading } = useAuth();
  if (loading) return <FullScreenLoader />;
  if (session) return <Navigate to="/" replace />;
  return <LoginPage />;
}

export const router = createBrowserRouter([
  { path: '/login', element: <LoginRoute />, errorElement: <RouteError /> },
  {
    path: '/',
    element: <RequireAuth />,
    errorElement: <RouteError />,
    children: [
      {
        element: <DashboardShell />,
        children: [
          { index: true, element: <Navigate to="/baptisms" replace /> },
          { path: 'baptisms', element: <BaptismsTab /> },
          { path: 'golden-hour', element: <GoldenHourTab /> },
          { path: 'needs', element: <NeedsTab /> },
          { path: 'kpis', element: <LazyRoute><KpisTab /></LazyRoute> },
          { path: 'table', element: <TableTab /> },
          { path: 'leadership', element: <LazyRoute><LeadershipTab /></LazyRoute> },
          // "By Month" is no longer its own tab — the chart now lives at the bottom of KPIs (#1).
          { path: 'by-month', element: <Navigate to="/kpis" replace /> },
          // Settings + Admin overlay the dashboard as SIDE SHEETS but stay URL-landable: each renders
          // the default Baptisms tab underneath while the shell overlays the matching sheet (keyed off
          // the pathname). A refresh / deep link lands here → dashboard + open sheet; closing the sheet
          // navigates back to the underlying tab. Admin's content is lazy-loaded inside the sheet.
          { path: 'settings', element: <BackgroundTab /> },
          { path: 'admin', element: <BackgroundTab /> },
          // Full-history ops views (#7): /admin/runs · /admin/changelog · /admin/logins · /admin/endpoints (paginated).
          { path: 'admin/:section', element: <BackgroundTab /> },
          // Person detail is ALSO a URL-landable side/bottom sheet over the dashboard (same pattern):
          // the route renders the last tab as backdrop; DashboardShell overlays the detail sheet.
          { path: 'person/:id', element: <BackgroundTab /> },
        ],
      },
      // Deep link from the day-40 "re-authorize your sync" email — opens the one-MFA dialog (Piece 3).
      { path: 'reauth', element: <ReauthPage /> },
      { path: 'invite', element: <InvitePage /> },
    ],
  },
  { path: '*', element: <Navigate to="/" replace /> },
]);
