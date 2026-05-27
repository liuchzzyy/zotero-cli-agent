# Collection Design Reference

Use this as the active bundled collection design for the `zotero-library-rebuild` skill.

## Top Level

```text
00_INBOX      entrance
10_STAGE      useful items after screening
20_PROJECTS   project-like literature
30_TOPICS     personal skills and interests
40_WORKSPACE  special handling later
80_TRASH      rejected or not useful
90_ARCHIVE    manual archive / old structure
```

## Collection Tree

```text
00_INBOX
  00_UNSORTED
  10_AUTHOR_WATCH
    A.P. Hitchcock
    Martin Winter
    Zaiping Guo
    Xiaobo Ji

10_STAGE
  00_SCREENED
  10_AUTHOR_WATCH

20_PROJECTS
  00_PROJECT_INBOX
  10_MnO2
    00_Reviews
    10_Key_Papers
    20_Theory
    30_Synthesis
    40_Characterization
    50_Mechanism
    60_Performance
    70_Supplementary
    80_Ideas
  20_Zn
    00_Reviews
    10_Key_Papers
    20_Theory
    30_Synthesis
    40_Characterization
    50_Mechanism
    60_Performance
    70_Supplementary
    80_Ideas
  30_Battery
  40_Cellulose
  90_Other

30_TOPICS
  00_TOPIC_INBOX
  05_Academic
  10_Coding
  15_Visualization
  20_Electrochemistry
  25_Characterization
  30_Modeling
  35_Machine_Learning
  40_RAG_Knowledge
  45_Productivity
  50_Finance
  55_History
  60_Literature

40_WORKSPACE
80_TRASH
90_ARCHIVE
```

## Item Flow

```text
new item
  -> 00_INBOX/00_UNSORTED
  -> if tracked author: also 00_INBOX/10_AUTHOR_WATCH/<Author>

screening
  -> useful regular item: 10_STAGE/00_SCREENED
  -> useful tracked-author item: 10_STAGE/10_AUTHOR_WATCH
  -> not useful: 80_TRASH

first-pass classification
  -> project-like item: 20_PROJECTS/00_PROJECT_INBOX
  -> skill/interest item: 30_TOPICS/00_TOPIC_INBOX
  -> author-watch item: 30_TOPICS/05_Academic

later refinement
  -> 20_PROJECTS/00_PROJECT_INBOX -> MnO2 / Zn / Battery / Cellulose / Other
  -> 30_TOPICS/00_TOPIC_INBOX -> flat topic collections
  -> 40_WORKSPACE: separate later pass
  -> 90_ARCHIVE: manual handling
```

## Rebuild Flow

Use the collection tree only after the current library has been exported and profiled.

```text
00_export_current_state
  -> export all items, collections, tags, item-collection edges, and item-tag edges

10_extract_library_signals
  -> identify legacy trash delete candidates
  -> profile each existing collection from title sets and existing tags
  -> summarize likely project/topic/method ranges

20_ai_keyword_tag_review
  -> ask AI to propose keyword sets, tag sets, and risky ambiguous rules from title groups

30_design_adjustment
  -> update this reference and the tag taxonomy if the live library shows a better structure

40_plan_for_confirmation
  -> create archive plan, movement plan, and tag plan for human approval

50_execution_results
  -> store apply and verification results only after confirmed live writes
```

Uncertain item handling:

```text
90_ARCHIVE
  00_PRE_REBUILD_<YYYY-MM-DD>
    00_UNSURE_MANUAL_REVIEW
```

Low-confidence items must go to `00_UNSURE_MANUAL_REVIEW`, not to project/topic inboxes. The user can manually recover or classify them later.

Legacy trash handling:

- Legacy `04_TRASH` items map to `80_TRASH` as a holding collection.
- They also become delete candidates in the signal-extraction stage.
- Do not permanently delete them without separate explicit approval.

## Old-To-New Mapping

```text
00_INBOX_AA -> 00_INBOX/00_UNSORTED; author items also go to 00_INBOX/10_AUTHOR_WATCH/<Author>
00_INBOX_AA/A.P. Hitchcock -> 00_INBOX/10_AUTHOR_WATCH/A.P. Hitchcock
00_INBOX_AA/Martin Winter -> 00_INBOX/10_AUTHOR_WATCH/Martin Winter
00_INBOX_AA/Zaiping Guo -> 00_INBOX/10_AUTHOR_WATCH/Zaiping Guo
00_INBOX_AA/Xiaobo Ji -> 00_INBOX/10_AUTHOR_WATCH/Xiaobo Ji
00_INBOX_BB -> 00_INBOX/00_UNSORTED
01_SHORTTERMS -> likely 10_STAGE/00_SCREENED, then first-pass classify
02_PROJECTS -> 20_PROJECTS path after review
03_AREAS -> 30_TOPICS path after review
04_TRASH -> 80_TRASH unless manually archived instead
```
