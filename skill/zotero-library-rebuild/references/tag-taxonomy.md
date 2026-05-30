# Tag Taxonomy Reference

Use this as the active bundled tag taxonomy for the `zotero-library-rebuild` skill.

## Rules

- Use lowercase ASCII namespaces with `/`.
- Use snake_case for multiword values.
- Do not use `priority/*`, `origin/*`, `system/*`, or `role/*`.
- Use `project/*` instead of `system/*`.
- Paper function labels such as review, theory, synthesis, characterization, mechanism, performance, supplementary, and ideas belong in collection subfolders or human notes, not in the tag namespace.
- First pass is additive: do not delete or rename legacy tags.
- Legacy workflow tags must be converted deterministically into the new workflow/status namespace during planning. Keep the old tags in the first pass and add the normalized tags as proposed additions.
- Auto-tagging must use whole-token or phrase matches, not arbitrary substring matches.
- Personal topics such as finance, history, literature, academic, and productivity need strong explicit signals; do not infer them from generic scientific words such as novel, paper, market, stock, bond, or agent.
- `topic/coding` is for programming/development work. Do not auto-assign it from scientific software names alone, such as FEFF, Athena, Artemis, Larch, or general analysis packages.
- `topic/productivity` is for personal workflow / PKM / note-taking systems. Do not auto-assign it from the word `workflow` in scientific titles.
- `topic/rag_knowledge` requires explicit RAG, retrieval-augmented generation, vector database, or knowledge-base context. Do not auto-assign it from the word `agent` alone.
- `topic/history` is for history as a personal-interest domain. Do not auto-assign it from scientific review phrases such as historical milestones.
- Short method abbreviations such as CV, CA, and CP must require method context, such as full method names or curve/measurement phrases.
- Scientific analysis software papers, such as Athena/Artemis/Larch/FEFF, should be treated as characterization-method literature unless the title is explicitly about programming or software development practice.
- Use AI-extracted keyword/tag candidates as proposals, not automatic truth. Update this taxonomy only after review.
- If a tag assignment is low-confidence, leave it out of the automatic tag update plan and keep the item in archive/manual review.

## Namespaces

### status

```text
status/to_read
status/reading
status/read
status/annotated
status/to_cite
status/cited
status/needs_decision
status/needs_metadata
status/duplicate_check
status/pdf_missing
```

### project

```text
project/mno2
project/zn
project/battery
project/cellulose
project/other
```

### topic

```text
topic/academic
topic/coding
topic/visualization
topic/electrochemistry
topic/characterization
topic/modeling
topic/machine_learning
topic/rag_knowledge
topic/productivity
topic/finance
topic/history
topic/literature
```

### tech/electrochemistry

```text
tech/electrochemistry/cv
tech/electrochemistry/gcd
tech/electrochemistry/eis
tech/electrochemistry/dqdv
tech/electrochemistry/lsv
tech/electrochemistry/ocv
tech/electrochemistry/ca
tech/electrochemistry/cp
tech/electrochemistry/cycling
tech/electrochemistry/rate_capability
```

### tech/characterization

```text
tech/characterization/xas
tech/characterization/exafs
tech/characterization/tem
tech/characterization/txm
tech/characterization/xrd
tech/characterization/xps
tech/characterization/sem
tech/characterization/raman
tech/characterization/ftir
```

### tech/modeling and tech/ai

```text
tech/modeling/dft
tech/modeling/md
tech/modeling/phase_field
tech/ai/machine_learning
tech/ai/rag
tech/ai/llm_agent
```

### workflow

Workflow tags record process state and legacy workflow-tag migration. They should come from existing tags or explicit workflow events, not from title keyword inference.

```text
workflow/metadata
workflow/ai_note
workflow/collection_rebuild_reviewed
workflow/tag_rebuild_reviewed
workflow/classified
workflow/needs_manual_review
```

## Legacy Tags

Convert these old tags additively in the tag plan:

```text
update/metadata -> workflow/metadata
update/AInote -> workflow/ai_note
/reading -> status/reading
star emoji tags -> keep until manual review; do not convert automatically
```

Do not remove `update/metadata`, `update/AInote`, or `/reading` in the first pass. Removal or renaming can be a later cleanup phase after the normalized tags have been verified.

## AI Review Input

Before changing tags, generate and review:

```text
00_export_current_state/tags_before.json
00_export_current_state/item_tag_edges.jsonl
10_extract_library_signals/collection_profiles.json
10_extract_library_signals/collection_title_sets.json
20_ai_keyword_tag_review/keyword_tag_extraction_prompt.md
```

AI should propose:

- candidate normalized tags
- deterministic legacy tag conversions from existing tags to normalized workflow/status tags
- strong and weak keyword triggers
- tags that should remain manual-only
- ambiguous words that must not be used for automation

Do not add AI-proposed tags until the keyword rules have been reviewed against title examples.

## Examples

MnO2 XAS mechanism paper:

```text
project/mno2
tech/characterization/xas
```

RAG/coding workflow paper:

```text
topic/rag_knowledge
topic/coding
tech/ai/rag
```

Electrochemistry paper using CV, EIS, and dQ/dV:

```text
topic/electrochemistry
tech/electrochemistry/cv
tech/electrochemistry/eis
tech/electrochemistry/dqdv
```
