# FrankenOracle — Codex Repo Ready

This folder is organized to be dropped into a **private GitHub repo** and connected to **Codex web**.

## Folder layout

- `src/` — core Python code
- `docs/handoff/` — full project state and handoff docs
- `docs/analysis/` — latest internal analysis reports
- `prompts/` — ready-to-paste Codex prompts
- `data/` — currently available raw market data
- `results/` — key JSON/MD outputs from prior research passes

## What Codex should read first

1. `docs/handoff/frankenoracle_full_handoff_new_chat.md`
2. `docs/handoff/frankenoracle_detailed_report_for_claude.md`
3. `prompts/step12_hazard_manifold_widening.md`

## Immediate task

Run **Step 12 — Hazard Manifold Widening Pass**.

Short version:
- keep the honest later-regime event definition
- keep the Oracle grounding baseline from Task 8 fixed
- freeze Candidate B downstream
- test:
  - Pass 0 = current hazard stack
  - Pass 1 = + drawdown damage into hazard
  - Pass 2 = + drawdown damage + vol regime into hazard
- judge in this order:
  1. hazard separation
  2. half-on occupancy
  3. decisive occupancy
  4. T0 / pre24h exposure
  5. motif preservation

## How to use this with Codex web

1. Create a **private GitHub repo**
2. Upload the contents of this folder to that repo
3. Open **Codex web** and connect the repo
4. Paste the prompt from `prompts/step12_hazard_manifold_widening.md`
5. Let Codex run the experiment and return results

## Notes

- This bundle includes the currently available core code, docs, data, and results.
- Some earlier uploads in the conversation had expired, so only files present at packaging time are included here.
- If Codex asks for a file that is missing, re-upload that specific file to the new repo.

## Packaged files

Copied: 32
Missing at packaging time: 0
