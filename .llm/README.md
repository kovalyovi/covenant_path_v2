# `.llm/` — agent working notes & cross-surface rules

Durable instructions for AI agents (and humans) working in this repo. This **complements**
`CLAUDE.md` (the root source-of-truth) and `docs/` — it does not replace them. Read
`CLAUDE.md` first, then this.

## Files

- **[`CROSS_SURFACE_UI.md`](CROSS_SURFACE_UI.md)** — THE cardinal rule: **every UI-facing
  change must land in all three client codebases (React web, native iOS, native Android) and
  stay in parity.** Read it before touching any UI. (The old Flutter app was deleted 2026-06-13.)
- **[`ROADMAP.md`](ROADMAP.md)** — the consolidated user-feedback roadmap currently in
  flight, with per-item status and the surfaces each item touches.

## Conventions

- If you add a cross-cutting rule future agents must follow, add it here and link it from
  `CLAUDE.md` so it's discoverable.
- Keep `ROADMAP.md` status current as items land.
