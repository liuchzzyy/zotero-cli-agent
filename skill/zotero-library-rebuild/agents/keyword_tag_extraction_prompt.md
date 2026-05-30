# AI Prompt: Keyword And Tag Candidate Extraction

You are helping rebuild a Zotero library. Use the exported title sets and collection profiles to propose keyword rules and normalized tags.

Input files:

- `../00_export_current_state/items_before.jsonl`
- `../10_extract_library_signals/collection_profiles.json`
- `../10_extract_library_signals/collection_title_sets.json`
- `../10_extract_library_signals/trash_delete_candidates.jsonl`
- `../../../../skill/zotero-library-rebuild/references/collection-design.md`
- `../../../../skill/zotero-library-rebuild/references/tag-taxonomy.md`

Return JSON only:

```json
{
  "collection_profile_summary": [
    {
      "source_collection": "",
      "scope_summary": "",
      "keep_or_delete_signal": "",
      "strong_keywords": [],
      "weak_keywords": [],
      "candidate_tags": [],
      "example_item_keys": [],
      "risks": []
    }
  ],
  "recommended_project_keywords": {},
  "recommended_topic_keywords": {},
  "recommended_tech_keywords": {},
  "recommended_legacy_tag_conversions": {},
  "recommended_tag_additions": [],
  "recommended_collection_adjustments": [],
  "do_not_auto_apply": []
}
```

Rules:

- Prefer precise phrases over short ambiguous tokens.
- Allowed tag namespaces are `status/*`, `project/*`, `topic/*`, `tech/*`, and `workflow/*`.
- Treat `workflow/*` as process state from existing tags or explicit workflow events, not as a title-keyword topic namespace.
- Preserve deterministic legacy conversions unless there is a clear conflict: `update/metadata` -> `workflow/metadata`, `update/AInote` -> `workflow/ai_note`, `/reading` -> `status/reading`.
- Keep old tags in the first pass; propose normalized additions only.
- Do not propose `priority/*`, `origin/*`, `system/*`, or `role/*` tags.
- Do not infer personal topics from generic scientific words.
- Mark uncertain signals as `do_not_auto_apply`.
- Treat legacy trash items as delete candidates only after explicit human approval.
