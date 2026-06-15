// Per-day field-gap aggregation for the ops dash (track-missing-fields). Pure + PII-free, mirrored by
// no native surface (ops console is web-only). Each sync run stamps a structured field-gap report into
// its diagnostics payload (run_stats.field_gaps: per-field members-missing + WHY) and also emits a live
// Axiom `sync.field_gaps` event; this rolls the diagnostics rows up per day so "which fields are
// missing, and is it trending better or worse?" is answerable at a glance.

type Json = Record<string, unknown>;

/** Members-missing-per-field for one sync run's payload: prefer the structured field_gaps report;
 *  fall back to field_coverage (missing = blocked + pending) for legacy one-work runs that predate it. */
export function missingByField(payload: Json): Record<string, { missing: number; reason?: string }> {
  const out: Record<string, { missing: number; reason?: string }> = {};
  const stats = (payload['run_stats'] as Json) ?? {};
  const gaps = (stats['field_gaps'] as Json) ?? {};
  const fields = (gaps['fields'] as Record<string, Json>) ?? {};
  for (const [f, v] of Object.entries(fields)) {
    out[f] = { missing: Number((v as Json)['missing'] ?? 0), reason: String((v as Json)['reason'] ?? '') };
  }
  if (Object.keys(out).length === 0) {
    const cov = (payload['field_coverage'] as Record<string, Json>) ?? {};
    for (const [f, v] of Object.entries(cov)) {
      const miss = Number((v as Json)['blocked'] ?? 0) + Number((v as Json)['pending'] ?? 0);
      if (miss > 0) out[f] = { missing: miss };
    }
  }
  return out;
}

export function humanizeField(f: string): string {
  return f.replace(/_/g, ' ').replace(/\b\w/g, (c) => c.toUpperCase());
}

export interface FieldGapSeries {
  days: string[]; // YYYY-MM-DD, ascending (oldest → newest)
  fields: string[]; // sorted by most-recent-day missing, desc
  totals: Record<string, number[]>; // field -> members missing per day (aligned with `days`)
  reasons: Record<string, string>; // field -> most-recent reason string
}

/** Aggregate per-day field gaps across recent sync diagnostics rows (PII-free): group by calendar
 *  day, keep only the LATEST run per stake per day (runs arrive newest-first), sum members-missing per
 *  field across stakes, and keep the last ~`maxDays` days. */
export function fieldGapSeries(runs: Json[], maxDays = 10): FieldGapSeries {
  const syncRuns = runs.filter((r) => r['kind'] === 'sync');
  const dayTotals = new Map<string, Map<string, number>>();
  const reasons = new Map<string, string>();
  const seen = new Set<string>(); // `${day}|${stake}` — runs arrive newest-first, so first wins
  for (const r of syncRuns) {
    const day = String(r['run_at'] ?? '').slice(0, 10);
    if (!day) continue;
    const dedupe = `${day}|${String(r['stake_id'] ?? '')}`;
    if (seen.has(dedupe)) continue;
    seen.add(dedupe);
    const mbf = missingByField((r['payload'] as Json) ?? {});
    const tot = dayTotals.get(day) ?? new Map<string, number>();
    for (const [f, v] of Object.entries(mbf)) {
      tot.set(f, (tot.get(f) ?? 0) + v.missing);
      if (v.reason && !reasons.has(f)) reasons.set(f, v.reason);
    }
    dayTotals.set(day, tot);
  }
  const days = [...dayTotals.keys()].sort().slice(-maxDays);
  const all = new Set<string>();
  for (const t of dayTotals.values()) for (const f of t.keys()) all.add(f);
  const latest = days[days.length - 1];
  const fields = [...all].sort(
    (a, b) => (dayTotals.get(latest)?.get(b) ?? 0) - (dayTotals.get(latest)?.get(a) ?? 0),
  );
  const totals: Record<string, number[]> = {};
  for (const f of fields) totals[f] = days.map((d) => dayTotals.get(d)?.get(f) ?? 0);
  return { days, fields, totals, reasons: Object.fromEntries(reasons) };
}
