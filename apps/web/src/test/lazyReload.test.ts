// Regression tests for the stale-chunk recovery (the KPIs-tab "Failed to fetch dynamically
// imported module" error). A deploy replaces the hashed chunks under any tab still running the old
// index.html, so the first lazy navigation 404s. lazyWithReload must reload the page exactly ONCE
// to pick up the new build, and must NOT reload-loop when the import keeps failing (e.g. offline) —
// the second failure rethrows so the route errorElement can take over.

import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import { lazyWithReload, reloadOnceForStaleChunk, clearStaleChunkFlag } from '../lib/lazyReload';

const reload = vi.fn();

beforeEach(() => {
  sessionStorage.clear();
  reload.mockClear();
  vi.stubGlobal('location', { ...window.location, reload });
});

afterEach(() => {
  vi.unstubAllGlobals();
});

describe('lazyWithReload', () => {
  it('passes a successful import through and re-arms the guard', async () => {
    sessionStorage.setItem('cp-stale-chunk-reload', '1'); // left over from a previous recovery
    const factory = lazyWithReload(async () => ({ default: 'mod' }));
    await expect(factory()).resolves.toEqual({ default: 'mod' });
    expect(reload).not.toHaveBeenCalled();
    expect(sessionStorage.getItem('cp-stale-chunk-reload')).toBeNull();
  });

  it('reloads the page once when the chunk import fails', async () => {
    const factory = lazyWithReload(async () => {
      throw new TypeError('Failed to fetch dynamically imported module');
    });
    void factory(); // resolves never — the reload takes over
    await vi.waitFor(() => expect(reload).toHaveBeenCalledTimes(1));
  });

  it('rethrows instead of reload-looping when the import fails again after a reload', async () => {
    reloadOnceForStaleChunk(); // simulate: this session already reloaded once
    reload.mockClear();
    const err = new TypeError('Failed to fetch dynamically imported module');
    const factory = lazyWithReload(async () => {
      throw err;
    });
    await expect(factory()).rejects.toBe(err);
    expect(reload).not.toHaveBeenCalled();
  });
});

describe('reloadOnceForStaleChunk', () => {
  it('only fires once per session until cleared', () => {
    expect(reloadOnceForStaleChunk()).toBe(true);
    expect(reloadOnceForStaleChunk()).toBe(false);
    expect(reload).toHaveBeenCalledTimes(1);
    clearStaleChunkFlag();
    expect(reloadOnceForStaleChunk()).toBe(true);
  });
});
