import { useEffect } from 'react';
import { useNavigate } from 'react-router-dom';
import { useDashboard } from '../hooks/useDashboard';

/**
 * Deep-link target for the day-40 "re-authorize your stake's sync" email (Piece 3). Opens the
 * one-MFA credential-capture dialog over the dashboard so the leader re-authorizes in under a minute
 * and a fresh 45-day Member Tools token is minted. An unauthenticated leader is sent through /login
 * first by RequireAuth, then bounced back here. Renders nothing — it just opens the dialog and lands
 * on the dashboard (where ReauthDialog lives).
 */
export function ReauthPage() {
  const d = useDashboard();
  const navigate = useNavigate();
  useEffect(() => {
    d.openReauth();
    navigate('/baptisms', { replace: true });
  }, [d, navigate]);
  return null;
}
