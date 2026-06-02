// App routing (React Router v7) — mirrors the Flutter go_router map (R1). Top-level: `/login` and
// `/` (the dashboard shell) with the 5 tab children `/baptisms` · `/golden-hour` · `/needs` ·
// `/kpis` · `/table`, plus `/person/:id`, `/settings`, `/invite`, `/admin`. Auth is enforced by a
// guard that re-evaluates on every Supabase auth change (sign-in / sign-out / token refresh):
// no session → /login; an authed user at /login → /. A no-access member is blocked at login (N2),
// so they never reach a session here.

import { lazy, Suspense } from 'react';
import { createBrowserRouter, Navigate, Outlet, useLocation } from 'react-router-dom';
import { useAuth } from './hooks/useAuth';
import { DashboardProvider } from './hooks/useDashboard';
import { Spinner } from './components/ui';
import { LoginPage } from './pages/LoginPage';
import { DashboardShell } from './pages/DashboardShell';
import { BaptismsTab } from './pages/tabs/BaptismsTab';
import { GoldenHourTab } from './pages/tabs/GoldenHourTab';
import { NeedsTab } from './pages/tabs/NeedsTab';
import { TableTab } from './pages/tabs/TableTab';
import { PersonDetailPage } from './pages/PersonDetailPage';
import { SettingsPage } from './pages/SettingsPage';
import { InvitePage } from './pages/InvitePage';

// Code-split the chart-heavy KPIs tab (Recharts) and the rarely-used Admin console out of the
// initial bundle, so first paint of the dashboard stays lean.
const KpisTab = lazy(() => import('./pages/tabs/KpisTab').then((m) => ({ default: m.KpisTab })));
const AdminPage = lazy(() => import('./pages/AdminPage').then((m) => ({ default: m.AdminPage })));

function LazyRoute({ children }: { children: React.ReactNode }) {
  return <Suspense fallback={<FullScreenLoader />}>{children}</Suspense>;
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
      <Outlet />
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
  { path: '/login', element: <LoginRoute /> },
  {
    path: '/',
    element: <RequireAuth />,
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
        ],
      },
      { path: 'person/:id', element: <PersonDetailPage /> },
      { path: 'settings', element: <SettingsPage /> },
      { path: 'invite', element: <InvitePage /> },
      { path: 'admin', element: <LazyRoute><AdminPage /></LazyRoute> },
    ],
  },
  { path: '*', element: <Navigate to="/" replace /> },
]);
