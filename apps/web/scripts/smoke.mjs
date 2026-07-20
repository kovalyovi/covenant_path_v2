// Post-deploy e2e smoke test (no deps, Node 20+): verifies the LIVE site can actually load every
// lazy route chunk — the "Failed to fetch dynamically imported module: KpisTab-*.js" regression.
//
// What it checks, against APP_URL (default production):
//   1. `/` serves 200 with Cache-Control: no-cache (stale-shell prevention, public/_headers).
//   2. If a local dist/index.html exists (CI runs this right after the build), poll until the
//      deployed shell references the SAME entry bundle we just built — i.e. the deploy actually
//      propagated — before judging anything else.
//   3. Every asset referenced by index.html AND every lazy chunk referenced by the entry bundle
//      (KpisTab, AdminPage, AdminListPage, recharts, supabase, CSS) fetches 200 with the
//      immutable cache header.
//
// Usage: node scripts/smoke.mjs   (from apps/web; APP_URL env overrides the target)

import { readFile } from 'node:fs/promises';

const APP_URL = (process.env.APP_URL || 'https://app.membercovenantpath.org').replace(/\/$/, '');
const PROPAGATION_TIMEOUT_MS = 3 * 60 * 1000; // Cloudflare Pages usually propagates in seconds
const POLL_INTERVAL_MS = 5000;
// Asset fetches get their own grace window: `/` propagating does NOT mean every edge already has
// the new /assets/* files (2026-07-19: the shell was new but the entry-bundle GET was answered by
// a stale edge with the OLD index.html as SPA fallback — HTTP 200, body HTML).
const ASSET_DEADLINE_MS = 2 * 60 * 1000;
const assetDeadline = Date.now() + PROPAGATION_TIMEOUT_MS + ASSET_DEADLINE_MS;

const failures = [];
const ok = (msg) => console.log(`  ✓ ${msg}`);
const fail = (msg) => { failures.push(msg); console.error(`  ✗ ${msg}`); };

async function get(path) {
  const res = await fetch(`${APP_URL}${path}`, { redirect: 'follow', cache: 'no-store' });
  const body = await res.text();
  return { status: res.status, cacheControl: res.headers.get('cache-control') ?? '', body };
}

const assetRefs = (text) => [...new Set([...text.matchAll(/\/?assets\/[\w.-]+\.(?:js|css)/g)].map((m) => `/${m[0].replace(/^\//, '')}`))];

// A missing /assets/* file does NOT 404 on Cloudflare Pages — the SPA fallback serves index.html
// with a 200. For an asset request that "success" is a MISS (the real bug class this smoke exists
// to catch: a chunk the deploy didn't ship). Detect it by body shape, and poll while the edge may
// simply not have propagated yet.
const looksHtml = (body) => /^\s*<(!doctype|html)/i.test(body);

async function getAsset(path) {
  for (;;) {
    const res = await get(path);
    const miss = res.status !== 200 || looksHtml(res.body);
    if (!miss) return res;
    if (Date.now() > assetDeadline) return { ...res, spaFallback: res.status === 200 };
    console.log(`  … ${path} not served yet (${res.status}${looksHtml(res.body) ? ', SPA-fallback HTML' : ''}) — retrying`);
    await new Promise((r) => setTimeout(r, POLL_INTERVAL_MS));
  }
}

// (2) When run right after a build (CI), wait until production serves the build we just made.
// CI-only: a local dist/ is built without the CI env (VITE_SUPABASE_URL etc. are baked into the
// bundle), so its content hashes never match the deployed artifact.
async function waitForPropagation() {
  if (!process.env.GITHUB_ACTIONS) {
    console.log('  (not in CI — skipping propagation check, testing whatever is live)');
    return;
  }
  let expectedEntry;
  try {
    expectedEntry = assetRefs(await readFile(new URL('../dist/index.html', import.meta.url), 'utf8')).find((a) => a.endsWith('.js'));
  } catch {
    console.log('  (no dist/ — skipping propagation check, testing whatever is live)');
    return;
  }
  const deadline = Date.now() + PROPAGATION_TIMEOUT_MS;
  for (;;) {
    const { status, body } = await get('/');
    if (status === 200 && body.includes(expectedEntry)) {
      ok(`deploy propagated — live shell references ${expectedEntry}`);
      return;
    }
    if (Date.now() > deadline) {
      fail(`deploy did NOT propagate within ${PROPAGATION_TIMEOUT_MS / 1000}s — live shell still lacks ${expectedEntry}`);
      return;
    }
    console.log(`  … waiting for live shell to reference ${expectedEntry}`);
    await new Promise((r) => setTimeout(r, POLL_INTERVAL_MS));
  }
}

console.log(`Smoke-testing ${APP_URL}`);
await waitForPropagation();

// (1) The shell must never be cached past a deploy.
const index = await get('/');
index.status === 200 ? ok('GET / → 200') : fail(`GET / → ${index.status}`);
index.cacheControl.includes('no-cache')
  ? ok(`/ Cache-Control: ${index.cacheControl}`)
  : fail(`/ Cache-Control is "${index.cacheControl}" — expected no-cache (stale shells cause chunk 404s)`);

// (3) Walk shell → entry bundle → lazy chunks; every referenced asset must serve real content.
const shellAssets = assetRefs(index.body);
if (shellAssets.length === 0) fail('index.html references no /assets/* files — unexpected shell');
const toCheck = new Set(shellAssets);
for (const asset of shellAssets.filter((a) => a.endsWith('.js'))) {
  const res = await getAsset(asset);
  // Only harvest refs out of a REAL js body — parsing an HTML fallback yields the previous
  // deploy's asset names and poisons the walk (the 2026-07-19 red herring).
  if (res.status === 200 && !looksHtml(res.body)) assetRefs(res.body).forEach((a) => toCheck.add(a));
}
// (3b) In CI the deployed artifact is the local dist/ — every built asset must serve, by name.
// Stronger than the reference walk: catches a chunk the upload dropped even if nothing refs it yet.
if (process.env.GITHUB_ACTIONS) {
  try {
    const { readdir } = await import('node:fs/promises');
    for (const f of await readdir(new URL('../dist/assets', import.meta.url))) toCheck.add(`/assets/${f}`);
  } catch { /* no dist — reference walk still covers the live shell */ }
}
for (const asset of toCheck) {
  const res = await getAsset(asset);
  const good = res.status === 200 && !res.spaFallback;
  good
    ? ok(`GET ${asset} → 200`)
    : fail(`GET ${asset} → ${res.spaFallback ? '200 but SPA-fallback HTML (asset missing)' : res.status} — lazy navigation to this chunk would crash`);
  if (good && !res.cacheControl.includes('immutable')) fail(`${asset} Cache-Control is "${res.cacheControl}" — expected immutable`);
}

// The original bug was specifically the KPIs tab — assert its chunk is present by name.
[...toCheck].some((a) => /\/assets\/KpisTab-[\w-]+\.js$/.test(a))
  ? ok('KpisTab lazy chunk found and served')
  : fail('no KpisTab-*.js chunk referenced by the entry bundle — KPI route would have nothing to load');

if (failures.length > 0) {
  console.error(`\nSMOKE FAILED (${failures.length}): the deployed app would break for users.`);
  process.exit(1);
}
console.log('\nSmoke passed — all lazy route chunks load on the live site.');
