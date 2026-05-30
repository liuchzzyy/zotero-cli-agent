---
name: zotero-library-rebuild
description: "Rebuild a Zotero library's collection tree and tag system with an export-first, AI-assisted, dry-run-gated workflow. Use when users ask to export current Zotero items/collections/tags and their relationships, extract title-based keyword/tag candidates, adjust collection/tag architecture, migrate old collections into ARCHIVE, classify items into INBOX/STAGE/PROJECTS/TOPICS buffers, or run a safe Zotero collection/tag cleanup."
---

# Zotero Library Rebuild

Use this skill to safely rebuild Zotero collections and tags through staged dry-runs. Treat live Zotero as production data.

## Source Design

This skill is self-contained. Load these bundled references when collection or tag details are needed:

- `references/collection-design.md`
- `references/tag-taxonomy.md`

Do not depend on repo `TODO/` files for this workflow.

## Safety Rules

- Never write directly to `zotero.sqlite`.
- Never delete Zotero items during rebuild.
- Do not remove legacy tags in the first pass.
- Do not route items into `40_WORKSPACE`; workspace handling is separate.
- Treat `80_TRASH` as a holding collection, not permanent deletion.
- Every write phase needs a dry-run artifact and explicit user confirmation.
- After Web API writes, re-read Zotero state and account for sync lag before judging success.

## Command Baseline

Run read-only refresh first:

```powershell
uv run zot --json collection list
uv run zot --json stats
uv run zot --json workspace list
```

Inspect command contracts before relying on a write command:

```powershell
uv run zot --json schema
uv run zot collection --help
uv run zot tag --help
```

Use Zotero Web API-backed writes only through `zot`, `pyzotero`, or a reviewed repo script. If current CLI commands cannot express a needed collection re-parenting or batch tag update, create a dry-run script first and review it before live execution.

## Runtime Files

- Put all generated intermediate files under the repository root `log/` directory.
- Use a run-specific subdirectory under `log/zotero-library-rebuild/`.
- On a successful confirmed run, delete the corresponding intermediate run directory.
- On failure, preserve the run directory for debugging.
- For a dry-run that needs user review, keep the output explicitly with `-KeepOutput`; treat it as temporary review evidence and remove it after approval or after the confirmed run succeeds.
- Do not write generated artifacts to `TODO/`.

## Bundled Scripts

Use the planner first. It reads local SQLite in read-only mode and writes review artifacts only:

```powershell
powershell -ExecutionPolicy Bypass -File skill\zotero-library-rebuild\scripts\run-zotero-library-rebuild.ps1 -OutputDir smoke -Limit 50 -TitleSampleSize 50 -KeepOutput
```

Remove `-Limit` for the full dry-run after the smoke output looks coherent. The wrapper calls:

```text
skill/zotero-library-rebuild/scripts/plan_rebuild.py
```

The wrapper resolves relative output names under `log/zotero-library-rebuild/` and rejects absolute output paths outside repo `log/`. The Python planner enforces the same `log/` boundary when run directly. Without `-KeepOutput`, the wrapper deletes the run directory after success and preserves it only on failure.

Each retained review run must include these root-level files:

```text
plan.md     human review entrypoint with approval checklist and links to detailed artifacts
summary.md  compact count summary for quick inspection
```

For the standard retained run, review starts at:

```text
log/zotero-library-rebuild/current-state-review/plan.md
log/zotero-library-rebuild/current-state-review/summary.md
```

Use the apply script only after the user approves the retained dry-run plan:

```powershell
powershell -ExecutionPolicy Bypass -File skill\zotero-library-rebuild\scripts\apply-zotero-library-rebuild.ps1 -ReviewDir current-state-review -Phase collections -Apply
powershell -ExecutionPolicy Bypass -File skill\zotero-library-rebuild\scripts\apply-zotero-library-rebuild.ps1 -ReviewDir current-state-review -Phase items -BatchSize 25 -Apply
powershell -ExecutionPolicy Bypass -File skill\zotero-library-rebuild\scripts\apply-zotero-library-rebuild.ps1 -ReviewDir current-state-review -Phase verify -BatchSize 25 -Apply
```

Run phases separately unless the user explicitly wants `-Phase all`. Re-running `items` and `verify` is idempotent: already-applied rows should report `already_done`.

## Workflow

### 1. Export Current State

Export the target Zotero library before designing moves. The export must include all parent items, all collections, all tags, and item-to-collection / item-to-tag relationships.

```text
00_export_current_state/
  collection_tree_before.json
  library_stats_before.json
  tags_before.json
  items_before.jsonl
  item_collection_edges.jsonl
  item_tag_edges.jsonl
```

Each item row should include:

```json
{
  "item_key": "",
  "title": "",
  "item_type": "",
  "is_deleted": false,
  "collections": [],
  "tags": [],
  "doi": "",
  "creators": [],
  "year": "",
  "has_pdf": false,
  "has_notes": false
}
```

Classify regular parent items. Do not treat child attachments as independent literature items.

### 2. Extract Library Signals

Extract useful signals from the current library before changing the design:

```text
10_extract_library_signals/
  collection_profiles.json
  collection_title_sets.json
  trash_delete_candidates.jsonl
  signal_summary.md
```

Use this stage to answer:

- Which items are already in legacy trash and should become delete candidates after separate explicit approval.
- Which existing collections are close to target project/topic buckets.
- What each current collection is roughly about based on title sets, current tags, creators, years, and top terms.
- Which title groups should be sent to AI for keyword and tag candidate extraction.

Do not treat legacy trash membership or Zotero built-in trash membership as permanent deletion approval. They are signals for a separate delete-candidate review.

### 3. AI Review And Design Adjustment

Generate prompts for AI review:

```text
20_ai_keyword_tag_review/
  keyword_tag_extraction_prompt.md
  architecture_adjustment_prompt.md
  plan_review_prompt.md
```

The reusable source template for `keyword_tag_extraction_prompt.md` lives at:

```text
agents/keyword_tag_extraction_prompt.md
```

Use these prompts with the exported title sets. Ask AI to propose:

- strong keywords and weak keywords by collection/profile
- candidate `status/*`, `project/*`, `topic/*`, `tech/*`, and `workflow/*` tags
- deterministic legacy tag conversions into `workflow/*` or `status/*`
- collection architecture adjustments
- tags or rules that must not be auto-applied

Then compare the AI output against:

- `references/collection-design.md`
- `references/tag-taxonomy.md`

If the current library shows the framework needs adjustment, update the references and planner keyword rules before execution. Keep all design edits explicit and reviewable:

```text
30_design_adjustment/
  target_collection_tree.json
  target_collection_create_plan.json
  design_adjustment_notes.md
```

### 4. Plan For Human Confirmation

Only after export, signal extraction, and design adjustment, create the archive, movement, and tag plan:

```text
40_plan_for_confirmation/
  archive_collection_plan.json
  archive_item_membership_plan.jsonl
  item_movement_plan.jsonl
  tag_update_plan.jsonl
  low_confidence_items.md
  movement_summary.md
  tag_summary.md
  plan_review.md
```

Also write root-level `plan.md` and `summary.md` in the run directory. Use `plan.md` as the primary human approval document; use `summary.md` as the quick count overview.

Planning rules:

- Preserve the old structure under `90_ARCHIVE/00_PRE_REBUILD_<date>`.
- Detect legacy collection paths by path segment, not only by top-level prefix. After the first rebuild, old paths may appear as `90_ARCHIVE/00_PRE_REBUILD_<date>/04_TRASH` or `.../01_SHORTTERMS`; they must still map as legacy paths.
- Preserve existing target collection membership when re-planning an already rebuilt library.
- Move confident project/topic items into the approved target buffers.
- Keep uncertain items under `90_ARCHIVE/00_PRE_REBUILD_<date>/00_UNSURE_MANUAL_REVIEW`.
- Keep uncertain tag decisions out of automatic tag updates.
- Convert existing workflow-like tags additively: `update/metadata` -> `workflow/metadata`, `update/AInote` -> `workflow/ai_note`, and `/reading` -> `status/reading`.
- Keep all legacy tags in the first pass; do not remove `update/metadata`, `update/AInote`, or `/reading` until a later confirmed cleanup phase.
- Treat `workflow/*` as process state from existing tags or explicit rebuild events, not as a title-keyword topic namespace.
- Treat legacy trash items as `80_TRASH` movement plus separate delete candidates; do not delete them without separate approval.
- Treat Zotero built-in trash items (`deletedItems` / Web API `data.deleted`) as delete candidates only. Export them for review, but do not include them in normal archive, movement, collection update, or tag update plans.

Each movement row should include:

```json
{
  "phase": "",
  "item_key": "",
  "title": "",
  "from_collections": [],
  "to_collections": [],
  "reason": [],
  "confidence": "high|medium|low",
  "needs_user_confirm": true
}
```

Each tag row should include:

```json
{
  "item_key": "",
  "title": "",
  "current_tags": [],
  "proposed_add_tags": [],
  "proposed_remove_tags": [],
  "reason": [],
  "confidence": "high|medium|low",
  "needs_user_confirm": true
}
```

### 5. Execute After Confirmation

After the user approves the plan:

1. Apply one phase at a time.
2. Create or reuse target collections.
3. Preserve archive membership before new classification.
4. Apply confirmed item collection assignments.
5. Apply confirmed additive tag updates.
6. Keep uncertain items and tags in archive/manual review.
7. Re-read collections/tags after each phase.
8. Stop if counts diverge from the approved summary.

Use this folder for confirmed execution evidence:

```text
50_execution_results/
  collection_tree_after.json
  tag_stats_after.json
  collection_phase_summary.json
  collection_create_results.jsonl
  collection_reparent_results.jsonl
  item_update_results.jsonl
  item_update_progress.json
  item_update_summary.json
  failed_results.jsonl
  failed_batches.jsonl
  trashed_skipped_items.jsonl
  verification_progress.json
  verification_trashed_items.jsonl
  verification_missing_items.jsonl
  verification_summary.json
  verification_summary.md
```

Batch phases should print progress in this shape so interrupted runs are easy to resume or audit:

```text
[items] batch 1/199 processed=25/4965 fetched=25/25 updated=0 already_done=25 failed=0 missing=0 elapsed=1.09s
[items] batch 9/199 processed=225/4965 fetched=25/25 updated=0 already_done=24 failed=0 missing=0 trashed_skipped=1 elapsed=1.33s
[verify] batch 1/199 processed=25/4965 fetched=25/25 missing_items=0 trashed_items=0 missing_collections=0 missing_tags=0
```

Always keep failed, missing-item, and trashed-item details under the same execution output directory. A successful item apply can still have `missing > 0` if the local SQLite export contains items that the Zotero Web API cannot fetch; record those keys and titles for sync/manual review instead of treating them as successful writes. If the Web API fetch succeeds with `data.deleted=1`, count the row as `trashed_skipped` and do not add normal collections or tags.

## Classification Heuristics

Use conservative routing:

- If clearly project-like, send to `20_PROJECTS/00_PROJECT_INBOX`.
- If useful but not project-like, send to `30_TOPICS/00_TOPIC_INBOX`.
- If tracked-author and useful, send to `30_TOPICS/05_Academic` after `10_STAGE/10_AUTHOR_WATCH`.
- If not useful, send to `80_TRASH`.
- If uncertain, keep in `90_ARCHIVE/00_PRE_REBUILD_<date>/00_UNSURE_MANUAL_REVIEW`.
- If tag confidence is uncertain, do not add the proposed tag automatically.
- Use whole-token or phrase matching for auto-tags; do not match short technical terms inside unrelated words.
- Treat personal-interest topics as strong-signal/manual categories unless the item explicitly contains the topic meaning.

Never force a low-confidence item into a deep project/topic subcollection in the first pass.

## Reporting

When reporting to the user, include:

- files created
- commands run
- counts before and after
- number of high/medium/low confidence items
- write phases completed or still pending
- any commands that were not run and why
