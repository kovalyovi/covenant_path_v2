// Power users route (/invite) — kept for deep links; the primary entry is now the compact
// PowerUserSheet opened from the dashboard menu (#5). Both render the same PowerUserBody.

import { useNavigate } from 'react-router-dom';
import { IconButton } from '../components/ui';
import { PowerUserBody } from '../components/PowerUserSheet';

export function InvitePage() {
  const navigate = useNavigate();
  return (
    <div className="app-shell">
      <header className="appbar">
        <IconButton icon="chevron_left" label="Back" onClick={() => navigate(-1)} />
        <h1 className="appbar__title">Power users</h1>
      </header>
      <main className="page">
        <div className="maxw">
          <div style={{ padding: 16 }}>
            <PowerUserBody />
          </div>
        </div>
      </main>
    </div>
  );
}
