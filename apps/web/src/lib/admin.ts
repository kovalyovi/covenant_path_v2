// Calls the broker's admin/ops endpoints. Every request carries the signed-in user's Supabase
// token as a Bearer; the broker verifies it belongs to an app_admin. Ported from
// apps/viewer/lib/admin_client.dart.

import { brokerUrl } from './config';
import { currentAccessToken } from './supabase';

export class AdminError extends Error {
  constructor(message: string) {
    super(message);
    this.name = 'AdminError';
  }
}

export class AdminClient {
  get available(): boolean {
    return brokerUrl.length > 0;
  }

  private async headers(): Promise<Record<string, string>> {
    return { 'Content-Type': 'application/json', Authorization: `Bearer ${await currentAccessToken()}` };
  }

  private ensure(): void {
    if (!this.available) throw new AdminError('Ops console needs BROKER_URL configured.');
  }

  private async decode(r: Response): Promise<Record<string, unknown>> {
    let data: Record<string, unknown>;
    try {
      data = (await r.json()) as Record<string, unknown>;
    } catch {
      throw new AdminError(`Broker error (${r.status}).`);
    }
    if (r.status === 403) throw new AdminError('Not authorized (admins only).');
    if (r.status >= 400) throw new AdminError(String(data['detail'] ?? `Request failed (${r.status}).`));
    return data;
  }

  private async get(path: string): Promise<Record<string, unknown>> {
    this.ensure();
    const r = await fetch(`${brokerUrl}${path}`, { method: 'GET', headers: await this.headers() });
    return this.decode(r);
  }

  private async postReq(path: string, body?: unknown): Promise<Record<string, unknown>> {
    this.ensure();
    const r = await fetch(`${brokerUrl}${path}`, {
      method: 'POST',
      headers: await this.headers(),
      body: JSON.stringify(body ?? {}),
    });
    return this.decode(r);
  }

  summary = () => this.get('/admin/summary');
  actions = () => this.get('/admin/actions');
  diagnostics = () => this.get('/admin/diagnostics');
  enrolledStakes = () => this.get('/admin/enrolled-stakes');
  revokeStake = (stakeId: string) => this.postReq(`/admin/stakes/${stakeId}/revoke`);
  run = (workflow: string, inputs?: Record<string, unknown>) =>
    this.postReq('/admin/actions/run', inputs ? { workflow, inputs } : { workflow });
  rerun = (runId: number) => this.postReq(`/admin/actions/${runId}/rerun`);
  invite = (email: string) => this.postReq('/admin/invite', { email });
  feedback = (title: string, body: string) => this.postReq('/feedback', { title, body });
}

export const admin = new AdminClient();
