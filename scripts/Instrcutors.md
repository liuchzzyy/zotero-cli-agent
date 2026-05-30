## 通用执行规则

本文件中的所有 Zotero workflow 都默认直接在 PowerShell 中运行对应 `*.ps1` wrapper，然后查看真实进度；这条规则也适用于本次没有运行到的指令、参数组合、恢复命令和 apply 阶段。

推荐操作顺序：
1. 直接在 `E:\Desktop\CodingDaily\zotero-cli-agents` 下运行对应 wrapper，保留当前 PowerShell 输出。
2. 长任务运行时，另开 PowerShell 或使用 wrapper 打印的 progress watch 命令查看进程、`log\...` 目录、`progress.ndjson`、`summary.json`、`import_summary.json`、`run.out.log`、batch 日志或 Web API postcheck 文件。
3. 汇报进度必须引用实际证据，例如已处理数量、batch 编号、failed 数、输出文件修改时间、checkpoint/summary 内容；不要只说“正在运行”。
4. 如果 workflow 尚未实际执行，也要在说明和脚本里保留同样的直接运行和进度检查要求。
5. 对应 wrapper 默认打印 progress watch 命令；只有在输出过多时才使用 `-HideProgressWatchCommands` 隐藏提示。

## Zotero Library Rebuild

### 推荐给代理的直接提示词
```text
使用 skill zotero-library-rebuild。
在 E:\Desktop\CodingDaily\zotero-cli-agents 下重构 Zotero library 的 collection tree 和 tag system。

目标：
先导出当前 Zotero 的真实状态，包括所有条目、集合结构、tag、item-collection 关系和 item-tag 关系；再根据 skill\zotero-library-rebuild\references 中的 collection/tag 设计生成审核计划。不要直接写 zotero.sqlite，不删除条目，不在第一轮移除 legacy tag，不把条目路由到 40_WORKSPACE。

本指令独立包含运行文件规则：所有导出、审核计划、checkpoint、执行结果、临时诊断文件都放在 log\zotero-library-rebuild\<run-name> 下，不要放在仓库根目录散文件、tmp\ 或临时 .workspace\... 运行目录中。-OutputDir smoke 对应 log\zotero-library-rebuild\smoke；-OutputDir current-state-review 对应 log\zotero-library-rebuild\current-state-review。成功并复核无误后清理本次目录；失败、中断、等待确认或需要审计时保留。

先做只读基线检查：
uv run zot --json collection list
uv run zot --json stats
uv run zot --json workspace list

先跑小样本 smoke，只生成审核材料，不写 Zotero：
powershell -NoProfile -ExecutionPolicy Bypass -File skill\zotero-library-rebuild\scripts\run-zotero-library-rebuild.ps1 -OutputDir smoke -Limit 50 -TitleSampleSize 50 -KeepOutput

如果 smoke 输出结构正常，再生成完整审核计划：
powershell -NoProfile -ExecutionPolicy Bypass -File skill\zotero-library-rebuild\scripts\run-zotero-library-rebuild.ps1 -OutputDir current-state-review -TitleSampleSize 200 -KeepOutput

审核入口固定看：
- log\zotero-library-rebuild\current-state-review\plan.md
- log\zotero-library-rebuild\current-state-review\summary.md

同时检查这些关键计划：
- 00_export_current_state：当前库导出。
- 10_extract_library_signals：集合画像、标题集、trash/delete candidates。
- 20_ai_keyword_tag_review：给 AI 的关键词/tag/架构审查 prompt。
- 30_design_adjustment：目标 collection tree 和设计调整记录。
- 40_plan_for_confirmation：archive plan、item movement plan、tag update plan、low-confidence items。

确认逻辑：
- plan.md 是人工确认入口；summary.md 是快速计数概览。
- 不确定条目必须留在 90_ARCHIVE/00_PRE_REBUILD_<date>/00_UNSURE_MANUAL_REVIEW，不要强行塞进项目/topic 子集合。
- legacy 04_TRASH 只映射到 80_TRASH 作为 holding collection；是否永久删除需要另行确认。
- Zotero built-in trash 条目只导出为 delete candidates，不进入普通移动/tag 更新计划。
- tag 第一轮只 additive：例如 update/metadata -> workflow/metadata，update/AInote -> workflow/ai_note，/reading -> status/reading；不要删除旧 tag。
- 如果当前库显示框架需要调整，先更新 skill\zotero-library-rebuild\references 和 planner 规则，再重新生成 plan。

正式写入前必须让我确认 plan.md。确认前不要执行 apply。

我确认后，分阶段执行，不要一开始直接 -Phase all：
powershell -NoProfile -ExecutionPolicy Bypass -File skill\zotero-library-rebuild\scripts\apply-zotero-library-rebuild.ps1 -ReviewDir current-state-review -Phase collections -Apply
powershell -NoProfile -ExecutionPolicy Bypass -File skill\zotero-library-rebuild\scripts\apply-zotero-library-rebuild.ps1 -ReviewDir current-state-review -Phase items -BatchSize 25 -Apply
powershell -NoProfile -ExecutionPolicy Bypass -File skill\zotero-library-rebuild\scripts\apply-zotero-library-rebuild.ps1 -ReviewDir current-state-review -Phase verify -BatchSize 25 -Apply

执行时必须实时显示进度，items/verify 阶段至少要能看到 batch x/y、processed=xx/total、failed、missing、trashed_skipped 或 trashed_items。

执行结果检查：
- log\zotero-library-rebuild\current-state-review\50_execution_results\item_update_summary.json
- log\zotero-library-rebuild\current-state-review\50_execution_results\failed_results.jsonl
- log\zotero-library-rebuild\current-state-review\50_execution_results\verification_summary.md
- log\zotero-library-rebuild\current-state-review\50_execution_results\verification_missing_items.jsonl
- log\zotero-library-rebuild\current-state-review\50_execution_results\verification_trashed_items.jsonl

如果 Web API 返回 data.deleted=1，计为 trashed_skipped，不给它添加普通集合或 tag。若本地 SQLite 有条目但 Web API fetch 不到，记录 missing key/title，不能当作成功写入。

完成后以 Web API verification 为准；Zotero 桌面端同步后本地 zotero.sqlite 才会完全反映结果。成功并复核无误后再清理本次 log\zotero-library-rebuild\current-state-review；失败、中断、等待确认或需要审计时保留该目录。
```

## Zotero Library Relevance Cleanup

### 推荐给代理的直接提示词
```text
在 E:\Desktop\CodingDaily\zotero-cli-agents 下执行 Zotero library relevance cleanup，用于把与当前研究主题无关的期刊条目移动到 80_TRASH 集合。

规则文件固定为：
scripts\zotero-cleanup-rules.json

不要使用旧的 aa.json、aa_* 预览文件或 TODO 中间文件；这些只是早期临时命名，不再是正式接口。
规则文件中的 `zotero_scope.exclude_collections` 默认跳过持有集合：
- `80_TRASH` (`JJ6JSGT5`)：已经判为无关或待丢弃的 holding collection，不重复分类。
- `90_ARCHIVE` (`6HREN2FT`)：归档 holding collection，不参与日常 relevance cleanup。
如需排除其他持有集合，先更新 `scripts\zotero-cleanup-rules.json`，不要手改 CSV 或临时过滤输出。

本指令独立包含运行文件规则：classification preview、summary、cleanup plan、CSV 清单、progress、apply 结果和 postcheck 都放在本次 log\zotero-cleanup\YYYYMMDD-HHMMSS 目录；不要放在仓库根目录散文件、tmp\ 或临时 .workspace\... 运行目录中。失败、中断、等待确认或需要审计时保留该目录；确认完成且无需审计后再清理。

先执行 dry-run，只生成预览和计划，不写 Zotero：
powershell -NoProfile -ExecutionPolicy Bypass -File scripts\run-zotero-cleanup.ps1

dry-run 输出目录默认是：
log\zotero-cleanup\YYYYMMDD-HHMMSS

检查本次目录中的：
- classification-preview.md
- classification-summary.json
- cleanup-plan.json
- reject-candidates.csv
- unsure.csv
- keep.csv
- run.out.log
- progress.ndjson

边界：
- 只分类和处理 journalArticle。
- 非期刊条目全部保留，不移动；包括 book、preprint、document、computerProgram、encyclopediaArticle、webpage、report、thesis 等。
- 已在 Zotero 自带回收站中的条目跳过。
- 已在 `80_TRASH` 或 `90_ARCHIVE` 的条目默认跳过，不再重复分类。
- keep 和 unsure 不动。
- reject 才作为移动候选；`cleanup-plan.json` 中的 `reject_item_keys` 只包含还需要实际移动的条目。
- 不调用 zot delete，不删除 Zotero 条目。
- 不直接写 zotero.sqlite；读操作来自本地 SQLite，写操作必须走 Zotero Web API。

正式执行前必须让我确认 dry-run 结果。确认后再运行：
powershell -NoProfile -ExecutionPolicy Bypass -File scripts\run-zotero-cleanup.ps1 -Apply

“移动到 80_TRASH”的语义是：把 reject 候选条目的 collections 设置为仅 80_TRASH，使它们不再分散在原来的文件夹中。不是追加到 80_TRASH，也不是删除条目。

执行时必须实时显示进度。关注：
- preflight 中的 active journalArticle / keep / unsure / move_candidates
- classification-summary.json 中的 classification_scope.excluded_by_collection_count / excluded_collection_keys
- cleanup-plan.json 中的 reject_count / already_only_target_count / move_needed_count
- 每批 batch 的 fetched、moved、already、failed、completed/total、elapsed
- postcheck 中的 only_target、not_only_target、missing

默认批量大小为 50，这是 Zotero Web API 单批上限。不要调到 50 以上。

实际运行经验：
- 2026-05-27 的一次正式运行中，dry-run 分类结果为 active journalArticle=4824、keep=2173、unsure=799、move_candidates=1852；正式移动 1852 个条目成功。
- 2026-05-28 之后，规则默认排除 `80_TRASH` 和 `90_ARCHIVE`。一次只读 smoke 结果为 active journalArticle=2975、keep=2286、unsure=689、move_candidates=0、excluded_by_collection_count=1855。
- 如果 `move_needed_count=0`，不要再执行 -Apply；说明没有需要移动的 reject 条目。
- Web API 写入阶段耗时约 640 秒（约 10 分 40 秒）；多数 50 条批次耗时约 16-20 秒。不要因为 10-20 秒没有新行就判断卡死。
- postcheck 额外耗时约 47 秒；本次结果为 checked=1852、only_target_count=1852、not_only_target_count=0、missing_count=0。
- dry-run 和 -Apply 如果都不指定 -OutputDir，会生成两个不同的时间戳目录；正式结果以 -Apply 运行目录为准。
- completed-keys.txt 的行数应等于 apply-summary.json 中的 completed。progress.ndjson 的最后应包含 apply_complete 和 postcheck 事件。

如果执行中断或网络/API 失败，不要重建计划后盲目全量重跑。使用同一个输出目录继续：
powershell -NoProfile -ExecutionPolicy Bypass -File scripts\run-zotero-cleanup.ps1 -Apply -Resume -OutputDir log\zotero-cleanup\YYYYMMDD-HHMMSS

恢复逻辑：
- completed-keys.txt 中已有的 key 会跳过。
- Web API 中已经只属于 80_TRASH 的条目也会跳过。
- failed-keys.txt 和 api-results.ndjson 用于定位失败项。

完成后检查：
- apply-summary.json
- postcheck-web-api.json
- failed-keys.txt 是否为空或不存在
- postcheck-web-api.json 中 not_only_target_count 和 missing_count 是否为 0

Zotero Web API 写入后，需要 Zotero 桌面端同步，本地 zotero.sqlite 才会完全反映新的集合归属。验证正式执行结果优先看 postcheck-web-api.json，不要立即用本地 SQLite 判断失败。
同理，刚执行完时 `zot collection items JJ6JSGT5` 可能仍读取本地旧库，不能代替 Web API postcheck。

本工作流的运行目录使用 log\zotero-cleanup\YYYYMMDD-HHMMSS。失败、中断、等待确认或需要审计时保留该目录；确认完成且无需审计后再清理。
```

## Clean-up all metadata

### 推荐给代理的直接提示词
```text
使用 skill zotero-cli-agents。
在 E:\Desktop\CodingDaily\zotero-cli-agents 下执行 metadata cleanup。先建立本次运行目录：log\metadata-cleanup-YYYYMMDD-HHMM。
本指令独立包含运行文件规则：metadata-export、cleaned jsonl、dry-run/apply 输出、batch 文件、续跑文件和诊断记录都只放在本次 log\metadata-cleanup-YYYYMMDD-HHMM 目录；不要放在仓库根目录散文件、tmp\ 或临时 .workspace\... 运行目录中。失败、中断、等待确认或需要排查时保留该目录；复核无误后删除本次目录，如果 log\ 已空也删除 log\。

如果这是 CodingDaily 的“全库条目清理”总控流程，优先使用根目录 wrapper：
powershell -NoProfile -ExecutionPolicy Bypass -File E:\Desktop\CodingDaily\run-full-library-cleanup.ps1 -SkipDuplicates -SkipRelevance
该 wrapper 会默认排除 `80_TRASH` (`JJ6JSGT5`) 和 `90_ARCHIVE` (`6HREN2FT`)，并在 apply 时提供 `-ResumeMetadataApply` 续跑和实时 `[batch x/y] item a/b | overall c/d` 进度。

如果在本仓库内单独执行 metadata cleanup，先读取 Zotero 条目 metadata。默认导出命令必须同时跳过已清理 tag 和不需要清理的 holding collections：
uv run zot --json --detail full summarize-all --exclude-tag workflow/metadata --exclude-tag update/metadata --exclude-collection-key JJ6JSGT5 --exclude-collection-key 6HREN2FT --limit 5000 > log\metadata-cleanup-YYYYMMDD-HHMM\metadata-export.json

默认排除集合：
- `80_TRASH` (`JJ6JSGT5`)：无关/丢弃 holding collection，不做 metadata cleanup。
- `90_ARCHIVE` (`6HREN2FT`)：归档 holding collection，不做日常 metadata cleanup。
- `40_WORKSPACE` (`AFTJQCQA`) 默认不排除；只有明确不需要清理 workspace 条目时，才额外追加 `--exclude-collection-key AFTJQCQA`，或在总控 wrapper 中使用 `-ExcludeWorkspaceMetadata`。

导出后检查 metadata-export.json 的 meta：
- `excluded_tags` 应包含 `workflow/metadata` 和 `update/metadata`。
- `excluded_collection_keys` 应默认包含 `JJ6JSGT5` 和 `6HREN2FT`。
- `count` 是本次需要交给代理判断的条目数；不要对已排除集合生成 cleaned-metadata.jsonl。

只清洗这些字段的格式问题：title、abstractNote、publicationTitle、journalAbbreviation、language、publisher。
清洗目标：去掉 HTML 标签，修复异常空格、断裂换行、特殊符号粘连；保持原意，不改事实内容。
边界处理：化学式、化学计量数和电荷不要插入空格，例如 CO2、H2O、MnO2、Zn2+、LiFePO4、Ni3S2；不要把小数改成 `1. 0`；不要把 `single- versus`、`regio- and` 这类并列短语合并成一个词。
不要修改 DOI、url、date、pages、ISSN、extra.extra、creators、tags、notes。
只输出实际发生变更的条目，生成 log\metadata-cleanup-YYYYMMDD-HHMM\cleaned-metadata.jsonl。

先执行 `uv run zot --json update --from-jsonl log\metadata-cleanup-YYYYMMDD-HHMM\cleaned-metadata.jsonl --dry-run > log\metadata-cleanup-YYYYMMDD-HHMM\metadata-cleanup-dry-run.json`，不要正式写入，等我确认。等待确认期间保留本次 log 目录。

我确认后，按批次正式写入。推荐批大小为 50；如果网络不稳定可降到 25，不要超过 100。每批文件命名为：
- log\metadata-cleanup-YYYYMMDD-HHMM\cleaned-metadata-batch-001.jsonl
- log\metadata-cleanup-YYYYMMDD-HHMM\metadata-cleanup-apply-batch-001.json
- log\metadata-cleanup-YYYYMMDD-HHMM\metadata-cleanup-apply-batch-001.err.log

正式写入命令：
uv run zot --json update --from-jsonl log\metadata-cleanup-YYYYMMDD-HHMM\cleaned-metadata-batch-001.jsonl --add-tag workflow/metadata > log\metadata-cleanup-YYYYMMDD-HHMM\metadata-cleanup-apply-batch-001.json 2> log\metadata-cleanup-YYYYMMDD-HHMM\metadata-cleanup-apply-batch-001.err.log

不要静默等待长批次。`zot update --from-jsonl` 会在 stderr 输出结构化 progress；代理必须实时读取 stderr 或使用总控 wrapper，把进度转成类似：
`[batch 3/13] item 41/50 | overall 141/630 | succeeded=... failed=...`
每批结束后立即报告成功数、失败数、剩余批次数和日志路径。

增量/续跑规则：
- 已成功的 batch 判定标准是 apply JSON 中 `ok=true` 且 `failed=[]`，并且 succeeded 数等于该 batch 行数。
- 中断、超时或 API 断连后，不要重跑全量 cleaned-metadata.jsonl。
- 先读取已有 `metadata-cleanup-apply-batch-*.json`；成功 batch 跳过。
- partial batch 只收集 `data.failed` 中的条目，写入 `cleaned-metadata-retry-failed-001.jsonl` 后单独重试。
- 空文件、缺失输出或 JSON 解析失败的 batch 才重跑该 batch。
- 在 CodingDaily 总控流程中，直接用同一个 `-RunName` 加 `-ResumeMetadataApply` 续跑：
  powershell -NoProfile -ExecutionPolicy Bypass -File E:\Desktop\CodingDaily\run-full-library-cleanup.ps1 -RunName full-library-cleanup-YYYYMMDD-HHMMSS -SkipDuplicates -SkipRelevance -SkipMetadataExport -CleanedMetadataJsonl E:\Desktop\CodingDaily\zotero-cli-agents\log\full-library-cleanup-YYYYMMDD-HHMMSS\03_metadata\cleaned-metadata.jsonl -ApplyMetadata -ResumeMetadataApply

全部批次完成后，生成或检查最终汇总：
- 单独流程：人工汇总每个 batch 的 succeeded/failed，确认 cleaned-metadata.jsonl 中所有 key 都成功。
- 总控 wrapper：检查 03_metadata\metadata-cleanup-final-summary.json，要求 final_succeeded 等于 total_updates，final_unresolved_failed=0。

复核无误后删除本次 log\metadata-cleanup-YYYYMMDD-HHMM 目录；如果 log\ 已空，也删除 log\。
```

## Clean-up book metadata

### 推荐给代理的直接提示词
```text
在 E:\Desktop\CodingDaily\zotero-cli-agents 下执行图书条目 metadata cleanup。图书不要使用期刊论文 DOI / Crossref 清洗路径，也不要直接写 zotero.sqlite。

图书专用 workflow 固定使用：
powershell -NoProfile -ExecutionPolicy Bypass -File scripts\run-book-metadata-cleanup.ps1

dry-run 会生成本次目录：
log\book-metadata-cleanup\YYYYMMDD-HHMMSS

重点检查：
- book-metadata-preview.csv
- book-metadata-plan.json
- book-metadata-updates.jsonl
- book-metadata-dry-run.json

图书专用脚本只处理 book 条目，优先按 ISBN 到外部书目源解析元数据，字段更新限定为：
- title
- date
- abstractNote
- language
- publisher
- shortTitle
- ISBN
- numPages
- series
- edition
- place

不要在这个 workflow 中修改 DOI、url、creators、collections，也不要用期刊 publicationTitle/journalAbbreviation 逻辑处理图书。
默认外部来源顺序是 `open_library,library_of_congress`。如果要用 Google Books：
- 已有可用 token cache 时，直接传 `-GoogleOAuthTokenCache` 即可。
- 只有首次授权或 token 过期且无法刷新时，才需要再传 `-GoogleOAuthClientSecret`。
powershell -NoProfile -ExecutionPolicy Bypass -File scripts\run-book-metadata-cleanup.ps1 -Providers google_books,open_library,library_of_congress -GoogleOAuthTokenCache E:\Desktop\CodingDaily\zotero-cli-agents\.zot\state\google-books-oauth-token.json

图书字段规则：
- date 清理 Zotero/Crossref 异常重复日期，例如 `2016-00-00 2016` -> `2016`，`2018-02-00 2018-02` -> `2018-02`。
- publisher 对 Douban HTML / 出品方 / 出版年 / 副标题杂项做图书专用清理，只保留出版社名。
- language 根据图书标题、摘要、出版社、shortTitle 判断；中文书名应为 `zh`，英文书应为 `en`。
- abstractNote 只做 HTML、空白、常见 mojibake 和破折号格式修复，不改写事实内容。
- apply 时默认只给处理过的 book 添加一个 tag：`workflow/metadata`。
- 不再额外生成 `source/book_metadata/*` 之类的 provider 来源 tag。

确认 dry-run 后正式写入：
powershell -NoProfile -ExecutionPolicy Bypass -File scripts\run-book-metadata-cleanup.ps1 -OutputDir log\book-metadata-cleanup\YYYYMMDD-HHMMSS -Apply

如果中断或需要复核，使用同一个目录续跑：
powershell -NoProfile -ExecutionPolicy Bypass -File scripts\run-book-metadata-cleanup.ps1 -OutputDir log\book-metadata-cleanup\YYYYMMDD-HHMMSS -Apply -Resume

正式写入后必须看 Web API postcheck：
- book-metadata-web-api-verification.json

要求：
- missing_count = 0
- field_mismatch_count = 0
- tag_mismatch_count = 0

Zotero Web API 写入后，需要 Zotero 桌面端同步，本地 zotero.sqlite 才会完全反映新的字段值。复核正式执行结果优先看 book-metadata-web-api-verification.json，不要立即用本地 SQLite 判断失败。
```

## Daily RSS DOI Import

### 推荐给代理的直接提示词
```text
在 E:\Desktop\CodingDaily\zotero-cli-agents 下执行 Daily RSS DOI Import。

本指令独立包含运行文件规则：route_plan、checkpoint、summary、failed_results、progress 和恢复审计文件都放在 log\rss-daily-doi-import_YYYY-MM-DD；不要放在仓库根目录散文件、tmp\ 或临时 .workspace\... 运行目录中。成功且 failed=0 时默认清理本次 log 目录；失败、中断或需要恢复时保留该目录。

日常运行不要手动拆开清洗/导入步骤，直接调用 wrapper。wrapper 默认把本次 route_plan、checkpoint、summary、failed_results 等运行文件放到 log\rss-daily-doi-import_YYYY-MM-DD，并在 failed=0 成功完成后自动删除本次 log 目录：
powershell -NoProfile -ExecutionPolicy Bypass -File scripts\run-rss-daily-doi-import.ps1 -Date YYYY-MM-DD -ProgressIntervalSeconds 5

推荐直接在 PowerShell 中运行 wrapper，保留终端输出；如需旁路查看进度，另开 PowerShell 查询 import 进程和 import_summary.json：
Get-CimInstance Win32_Process | Where-Object { $_.CommandLine -match 'run-rss-daily-doi-import|import_rss_inbox_plan' } | Select-Object ProcessId,Name,CommandLine
Get-Content -Raw log\rss-daily-doi-import_YYYY-MM-DD\rss_inbox_import\import_summary.json

默认读取：
E:\Desktop\CodingDaily\rss-cli-agent\storage\exports\daily\YYYY-MM-DD.selected.json

如果 RSS selected JSON 在非默认位置，必须显式传入完整路径：
powershell -NoProfile -ExecutionPolicy Bypass -File scripts\run-rss-daily-doi-import.ps1 -Date YYYY-MM-DD -SelectedJson "E:\Desktop\CodingDaily\rss-cli-agent\storage\exports\daily\YYYY-MM-DD.selected.json" -ProgressIntervalSeconds 5

如果需要保留成功运行记录用于审查，加 `-KeepLog`；否则不要保留成功运行的 log 目录。

运行时必须显示实时进度。关注 processed/total、created_new、reused_existing、already_routed、failed。长时间停在 preflight/import starting 时，检查 log\rss-daily-doi-import_YYYY-MM-DD\rss_inbox_import\import_summary.json 和是否仍有 import_rss_inbox_plan.py 进程，不要凭表面输出判断卡死。
如果 clean summary 显示 new_dois=0，wrapper 应直接写出 created_new=0、reused_existing=0、already_routed=0、failed=0 的 summary，并跳过 import_rss_inbox_plan.py；不要为 0 个 DOI 启动空导入进程。

如果 wrapper 已经完成且 failed=0：
- 本次 log\rss-daily-doi-import_YYYY-MM-DD 应该已被自动删除；如果使用过 -KeepLog，复核无误后手动删除。
- 删除旧版本残留的根目录 rss_failed_dois_YYYY-MM-DD.txt（如果存在）。
- 提醒用户 Zotero Web API 写入后需要 Zotero 同步，本地 SQLite 才会完全反映。

如果中途失败或被中断且 log\rss-daily-doi-import_YYYY-MM-DD 还在：
- 不要立刻重跑 wrapper；wrapper 会重建本次输出目录，可能丢掉 checkpoint。
- 先确认没有残留 import_rss_inbox_plan.py 进程。
- 用同一个 route_plan 和 output_dir 恢复：
  .\.venv\Scripts\python.exe scripts\import_rss_inbox_plan.py --route-plan log\rss-daily-doi-import_YYYY-MM-DD\rss_inbox_plan\route_plan.json --output-dir log\rss-daily-doi-import_YYYY-MM-DD\rss_inbox_import --library user --apply
- 恢复完成后检查 failed_results.json；若为空且 checkpoint 覆盖全部 route_plan entries，再删除旧版本残留的根目录 rss_failed_dois_YYYY-MM-DD.txt，并清理本次 log\rss-daily-doi-import_YYYY-MM-DD。
- 如果失败来自 metadata/Crossref 解析异常，先修复代码并补测试，再基于原 checkpoint 恢复；不要清空本次 log 目录。
```

## Remove Newer DOI Duplicates

### 推荐给代理的直接提示词
```text
不要用 title 模糊匹配做去重。
直接在 E:\Desktop\CodingDaily\zotero-cli-agents 下调用 scripts\remove-newer-doi-duplicates.ps1。

本指令独立包含运行文件规则：dry-run 输出、apply 输出、计划记录和诊断日志都放在本次 log\remove-newer-doi-duplicates-YYYYMMDD-HHMM 目录；不要放在仓库根目录散文件、tmp\ 或临时 .workspace\... 运行目录中。复核删除结果无误后清理本次目录；失败或等待确认时保留。

规则固定为：只按 DOI 精确判断；同 DOI 时保留 date_added 更早的旧条目，删除 date_added 更晚的新条目。
执行时必须给出实时进度：查询 DOI 重复项、构建 keep/delete 计划、每个重复组的 keep/delete 判断；正式删除时还要报告批次编号、已删除数、失败数、总体百分比。

如果这是 CodingDaily 的“全库条目清理”总控流程，本步骤是第一步，仍然先 dry-run，不要和 relevance / metadata apply 一起无确认地自动写入：
powershell -NoProfile -ExecutionPolicy Bypass -File E:\Desktop\CodingDaily\run-full-library-cleanup.ps1
确认 DOI keep/delete 计划后，才只执行 DOI duplicate apply：
powershell -NoProfile -ExecutionPolicy Bypass -File E:\Desktop\CodingDaily\run-full-library-cleanup.ps1 -RunName full-library-cleanup-YYYYMMDD-HHMMSS -SkipRelevance -SkipMetadataExport -ApplyDuplicates
如果 dry-run 显示 0 groups found，不需要进入 apply。

如果需要保存终端输出，先建立 log\remove-newer-doi-duplicates-YYYYMMDD-HHMM，并用 Tee-Object 同时显示和记录；不要把计划文件或日志放到根目录散文件：
powershell -NoProfile -ExecutionPolicy Bypass -File scripts\remove-newer-doi-duplicates.ps1 2>&1 | Tee-Object -FilePath log\remove-newer-doi-duplicates-YYYYMMDD-HHMM\dry-run.log

先执行默认 dry-run 看 keep/delete 计划；我确认后，再加 -Apply 正式删除，并把 apply 输出写到同一个 log\remove-newer-doi-duplicates-YYYYMMDD-HHMM\apply.log。
复核删除结果无误后，删除本次 log\remove-newer-doi-duplicates-YYYYMMDD-HHMM 目录；如果失败或等待我确认，保留该目录。
```

## Batch AI Note Analysis

### 推荐给代理的直接提示词
```text
使用 E:\Desktop\CodingDaily\zotero-cli-agents\scripts\run-ai-note-batch.ps1 批量生成 Zotero AI note，不要手动拼长命令逐条跑。

目标：
对尚未带有 `workflow/ai_note` 或旧 `update/AInote` 的非书籍条目，读取所有本地 PDF 附件，使用 MinerU 抽取 Markdown 和图片，经 CLIProxyAPI 的 gpt-5.5 生成“AI条目分析 - <title>”note，写回 Zotero Web API，并给父条目打 tag `workflow/ai_note`。

本指令独立包含运行文件规则：checkpoint、preview、results、failures、notes、MinerU 临时资产和 batch logs 都放在 log\ai-note-analysis-batch-YYYYMMDD-HHMMSS；不要放在仓库根目录散文件、tmp\ 或临时 .workspace\... 运行目录中。完整成功并复核无误后清理本次目录；失败、中断、等待审查或需要保留 MinerU 原始材料时保留。

默认命令。wrapper 默认把 checkpoint、preview、results、failures、notes、MinerU 临时资产和 batch logs 放到 log\ai-note-analysis-batch-YYYYMMDD-HHMMSS，并在完整成功后自动清理本次 log 目录：
powershell -NoProfile -ExecutionPolicy Bypass -File scripts\run-ai-note-batch.ps1 -BatchSize 3

先验证候选条目时用 dry-run；dry-run 成功结束后也会清理本次 log 目录，等待审查时可加 -KeepLog：
powershell -NoProfile -ExecutionPolicy Bypass -File scripts\run-ai-note-batch.ps1 -DryRun -BatchSize 3 -ScanLimit 100 -KeepLog

只处理指定条目时用：
powershell -NoProfile -ExecutionPolicy Bypass -File scripts\run-ai-note-batch.ps1 -Keys VH4PXB5G -BatchSize 1

边界和跳过规则：
- 已有 `workflow/ai_note` 或旧 `update/AInote` 的父条目默认完全跳过，不重复生成 note。
- 同一个 output/checkpoint 中已经 tagged 的条目也跳过；这是为了避免 Zotero Web API 写入后，本地 SQLite 尚未同步导致重复处理。
- book 和 bookSection 跳过；当前不做书籍 AI 分析。
- 无 PDF、PDF 路径缺失、PDF 超过 max PDF 大小、MinerU 抽取失败、AI 分类 uncertain、AI 调用失败、Zotero 写入失败，都不打 `workflow/ai_note`，便于下次继续。
- Zotero 读操作来自本地 SQLite；写 note/tag 通过 Zotero Web API。写入成功后需要 Zotero 同步，本地数据库才会看到新 note 和 tag。

模型和图片边界：
- 默认使用 CLIProxyAPI: http://127.0.0.1:8317/v1，模型 gpt-5.5，模式 mineru-markdown-images。
- CLIProxyAPI 的 gpt-5.5 已验证可以读取 image_url/base64 图片。
- DeepSeek deepseek-v4-flash 不支持 image_url 图片；如果切到 DeepSeek，只能用 mineru-text，不能使用 mineru-markdown-images。
- 不要把 MinerU Markdown 里的本地图片路径直接当作可读图片；脚本会把 MinerU 输出图片转成 base64 data URL 后发送给支持视觉的模型。
- 默认每个条目最多发送 24 张 MinerU 图片，避免请求过大。必要时可调整 -MaxImages，但不要无上限发送全部图片。

实时进度要求：
- 运行时必须保留终端输出，不要静默后台运行。
- 进度中应能看到扫描、跳过原因、MinerU upload/process/download、classify、analyze、note、tag、done、summary。
- 每批都会写 log\ai-note-analysis-batch-YYYYMMDD-HHMMSS\logs\batch-XXX.log；如果长时间停在 MinerU process 或 AI analyze，先看当前 batch log，不要盲目重启全量。

中间文件和清理：
- 默认输出目录为 log\ai-note-analysis-batch-YYYYMMDD-HHMMSS，不再使用 .workspace\ai-note-analysis-batch-* 作为运行目录。
- 成功批次后脚本会自动删除 mineru-assets 中间目录，避免图片和 MinerU ZIP 解包文件长期占用空间。
- 完整成功后脚本会删除本次 log\ai-note-analysis-batch-YYYYMMDD-HHMMSS；如果 log\ 已空，也删除 log\。
- 如果某批失败，log\ai-note-analysis-batch-YYYYMMDD-HHMMSS 会保留用于诊断，里面包括 notes、results.json、failures.json、summary.json、preview.json、checkpoint.json、logs\batch-*.log。
- 如果需要审查 MinerU 原始 Markdown/图片，加 -NoCleanIntermediate 保留中间文件；这也会保留本次 log 目录。
- 不要删除 checkpoint.json；批量处理中断后继续使用同一个 -OutputDir 才能避免重复处理已写入但本地尚未同步的条目。

失败恢复：
- 如果失败在 MinerU 上传/下载，优先用原 log\ai-note-analysis-batch-YYYYMMDD-HHMMSS 目录重跑；已缓存的 MinerU 资产会被复用，除非加 -RefreshMineruCache。
- 如果失败在 AI 调用，检查 CLIProxyAPI 是否运行、/v1/models 是否可用、模型是否支持图片。
- 如果失败在 Zotero 写入，检查 ZOT_API_KEY / ZOT_LIBRARY_ID 和 Web API 权限，不要写本地 zotero.sqlite。
- 如果某批有 failures，默认停止并保留本次 log 目录；不要立即用 -Force 全量重跑。
```

### 常用参数
```powershell
# 小批量正式运行，推荐默认；成功后自动清理本次 log 目录
powershell -NoProfile -ExecutionPolicy Bypass -File scripts\run-ai-note-batch.ps1 -BatchSize 3

# 保留 MinerU 中间 Markdown 和图片，便于检查
powershell -NoProfile -ExecutionPolicy Bypass -File scripts\run-ai-note-batch.ps1 -BatchSize 1 -NoCleanIntermediate

# 复用同一个 log 输出目录继续跑，避免本地 Zotero 未同步时重复
powershell -NoProfile -ExecutionPolicy Bypass -File scripts\run-ai-note-batch.ps1 -BatchSize 3 -OutputDir log\ai-note-analysis-batch-YYYYMMDD-HHMMSS

# 成功后也保留运行目录用于审查
powershell -NoProfile -ExecutionPolicy Bypass -File scripts\run-ai-note-batch.ps1 -BatchSize 3 -KeepLog

# 切到 DeepSeek 时只能用文本模式，不要使用 mineru-markdown-images
powershell -NoProfile -ExecutionPolicy Bypass -File scripts\run-ai-note-batch.ps1 -BatchSize 3 -Model deepseek-v4-flash -BaseUrl https://api.deepseek.com -PdfInputMode mineru-text
```

## Update AI Note Citation Keywords

### 推荐给代理的直接提示词
```text
使用 E:\Desktop\CodingDaily\zotero-cli-agents\scripts\run-ai-note-keyword-update.ps1 更新已经带有 workflow/ai_note 的父条目 citationKey，不要手动逐条改 Zotero，不要直接写 zotero.sqlite。

目标：
读取本地 Zotero SQLite 中带 workflow/ai_note 的父条目及其 AI note，对比现有 citationKey，生成统一的引用关键词，并通过 Zotero Web API 写回父条目 citationKey；写入成功后给父条目添加 tag workflow/keyword。

本指令独立包含运行文件规则：items、generated、updates、applied、failed_generation、failed_apply、summary、remaining 和 logs 都放在 log\ai-note-keyword-update 或指定的 log\ai-note-keyword-update-YYYYMMDD-HHMM 目录；不要放在仓库根目录散文件、tmp\ 或临时 .workspace\... 运行目录中。失败、中断、等待复核或等待充值时保留本次 log 目录；确认全量完成并复核后才清理。

关键词格式：
领域/体系 | 机制/关键问题 | 性能优势/价值 | 可选先进表征方法 | 可选制备方法 | 可选理论 | 疑问：最大破绽

格式规则：
- 最终 citationKey 是纯文本，不要 Markdown 反引号，不要方括号。
- 前三槽和最后的“疑问：”槽必填；可选先进表征方法、制备方法、理论/模型只有 AI note 中确实有时才追加，没有就不写，不要补空槽。
- 可选槽按“先进表征方法 | 制备方法 | 理论/模型”的语义顺序追加，每类最多一个短槽，可以用逗号合并同类术语。
- 引用关键词必须指出这篇文章最大的破绽、最弱证据、最值得追问的假设或外推风险，不要泛写“无明显破绽”。
- 统一通用术语；例如“液态Na-K合金负极”“Na-K液态合金负极”“液态Na-K合金”“Na-K液态合金”都简写为 Na-K。
- 具体 prompt 不再写死在 Python 中，保存在 scripts\update_ai_note_keywords_prompt.json；修改格式要求或术语统一时优先改这个 JSON。

推荐 wrapper。默认不写 Zotero，只刷新 status；完整运行需要显式 -FullRun：
powershell -NoProfile -ExecutionPolicy Bypass -File scripts\run-ai-note-keyword-update.ps1 -Status
powershell -NoProfile -ExecutionPolicy Bypass -File scripts\run-ai-note-keyword-update.ps1 -FullRun

分步运行时用：
powershell -NoProfile -ExecutionPolicy Bypass -File scripts\run-ai-note-keyword-update.ps1 -Generate
powershell -NoProfile -ExecutionPolicy Bypass -File scripts\run-ai-note-keyword-update.ps1 -RetryFailed
powershell -NoProfile -ExecutionPolicy Bypass -File scripts\run-ai-note-keyword-update.ps1 -DryRunApply
powershell -NoProfile -ExecutionPolicy Bypass -File scripts\run-ai-note-keyword-update.ps1 -Apply
powershell -NoProfile -ExecutionPolicy Bypass -File scripts\run-ai-note-keyword-update.ps1 -Status

当前推荐模型是 deepseek-v4-flash；不要再用 deepseek-v4-pro 做这个关键词流程，pro 在本流程里明显更慢。wrapper 默认 Model=deepseek-v4-flash。如果临时用 Python 子命令，显式指定 flash：
uv run python scripts\update_ai_note_keywords.py generate --skip-done-tag --model deepseek-v4-flash

Python 子命令仍可用于调试。默认工作目录是 log\ai-note-keyword-update，不再使用 .workspace\ai-note-keyword-update：
uv run python scripts\update_ai_note_keywords.py generate --skip-done-tag --model deepseek-v4-flash
uv run python scripts\update_ai_note_keywords.py generate --retry-failed --batch-size 1 --model deepseek-v4-flash
uv run python scripts\update_ai_note_keywords.py apply --dry-run
uv run python scripts\update_ai_note_keywords.py apply --zotero-timeout 90
uv run python scripts\update_ai_note_keywords.py status

如果要临时测试另一版 prompt：
uv run python scripts\update_ai_note_keywords.py --prompt-path scripts\update_ai_note_keywords_prompt.json generate --skip-done-tag --model deepseek-v4-flash
或用 wrapper：
powershell -NoProfile -ExecutionPolicy Bypass -File scripts\run-ai-note-keyword-update.ps1 -Generate -PromptPath scripts\update_ai_note_keywords_prompt.json

中间文件和续跑：
- 默认中间文件保存在 log\ai-note-keyword-update，包括 items.jsonl、generated.jsonl、updates.jsonl、applied.jsonl、failed_generation.jsonl、failed_apply.jsonl、summary.json、remaining.jsonl，以及 logs\*.log。
- 运行时终端和 logs\*.log 会实时输出 progress/progress_label，例如 generate 353/444、apply 81/444；如果长时间不变，再检查当前 log 和模型/API 状态。
- 如果要另开一次独立运行，用 --workspace log\ai-note-keyword-update-YYYYMMDD-HHMM；不要放到 .workspace。
- 续跑时复用同一个 log 目录；脚本会跳过 generated.jsonl、failed_generation.jsonl、applied.jsonl、failed_apply.jsonl 中已经记录且未解决的 key。
- 如果只想补跑生成失败的少数条目，用 wrapper 的 -RetryFailed，或 Python 的 --retry-failed --batch-size 1；不要用 --force 全量重跑。
- 每次 generate/apply/status 都会自动刷新 summary.json 和 remaining.jsonl；先看 summary.json 的 remaining、not_applied、generation_failed_unresolved、apply_failed_unresolved，再决定下一步。generation_failed_history_total 只是历史失败记录数，不代表当前仍失败。
- 如果 remaining.jsonl 只剩少数反复非 JSON 条目，可以读取对应 AI note 后人工整理 citationKey，追加到 generated.jsonl，再运行 apply；不要继续无意义消耗模型调用。
- 如果 DeepSeek 返回 402 Insufficient Balance，脚本会停止且不把待处理条目标记为失败；保留 log\ai-note-keyword-update，充值或切换模型后继续同一个目录。
- 如果本地 Zotero SQLite 尚未同步，优先用 --skip-done-tag 跳过已经打 workflow/keyword 的父条目；不要依赖直接改 zotero.sqlite。

安全边界：
- 读操作来自本地 SQLite；写 citationKey/tag 只通过 Zotero Web API。
- 不直接写 zotero.sqlite，不删除 Zotero 本地库文件。
- 失败、中断、等待复核或等待充值时不要清理 log\ai-note-keyword-update；只有确认全量完成并复核后才清理。
- Web API 写入后需要 Zotero 同步，本地 SQLite 才能看到新 citationKey/tag；抽样验证优先读 Web API。
```

## Full Library RAG Incremental Index

### 推荐给代理的直接提示词
```text
使用 E:\Desktop\CodingDaily\zotero-cli-agents\scripts\run-rag-full-library.ps1 为 Zotero 全库含 PDF 的父条目建立/更新 RAG 索引，不要手动逐条添加 workspace item。

默认目标：
- workspace 名称：full-library-pdf-rag。
- 条目范围：本地 Zotero SQLite 中所有“至少有一个本地存在 PDF 附件”的父条目。
- 索引方式：先维护 .workspace\full-library-pdf-rag\workspace.toml，再调用 uv run zot workspace index full-library-pdf-rag --extractor mineru。
- 增量规则：workspace 只新增缺失 key；RAG index 只索引尚未进入 rag.idx.sqlite 的 item key；PDF 文本抽取复用 .zot\state\pdf_cache.sqlite。

本指令独立包含运行文件规则，并区分持久状态和本次运行文件：.workspace\full-library-pdf-rag 和 .zot\state\pdf_cache.sqlite 是持久 workspace/index/cache，不是清理对象；inventory、临时脚本、运行日志和临时诊断文件放在 log\rag-full-library-YYYYMMDD-HHMMSS。不要把本次运行文件放在仓库根目录散文件、tmp\ 或额外临时 .workspace\... 目录中。完整成功并复核无误后清理本次 log 目录；失败、中断或需要审查时保留。

默认 dry-run。运行文件默认放到 log\rag-full-library-YYYYMMDD-HHMMSS，dry-run 成功后会自动清理；如果要审查 inventory，加 -KeepLog：
powershell -NoProfile -ExecutionPolicy Bypass -File scripts\run-rag-full-library.ps1 -DryRun -ScanLimit 100 -KeepLog

正式增量运行。成功后自动删除本次 log\rag-full-library-YYYYMMDD-HHMMSS 运行目录；持久 workspace/index 仍保留在 .workspace\full-library-pdf-rag：
powershell -NoProfile -ExecutionPolicy Bypass -File scripts\run-rag-full-library.ps1

边界：
- 默认不排除 book/bookSection，因为 RAG 的目标是“全库含 PDF”，不是 AI note 论文分析。
- 无本地 PDF 文件的条目不进入 workspace；有 Zotero PDF 记录但本地文件缺失的条目会统计为 pdf_but_missing_local_file。
- 现有 workspace index 的增量粒度是 item key。已索引条目的 PDF 或 metadata 后续变化不会自动重建；如果确认大量 PDF/metadata 已变更，用 -ForceRebuild 全量重建。
- 不直接写 rag.idx.sqlite；RAG index 只通过 zot workspace index 生成，避免破坏索引结构。
- 不删除 .workspace\full-library-pdf-rag，也不删除 .zot\state\pdf_cache.sqlite；它们是持久 workspace/index/cache，不是运行中间文件。

实时进度：
- inventory 阶段会显示 scanned/local_pdf_items/pdf_but_missing。
- index 阶段会显示 Extracting、MinerU upload/process/download、Chunking、Indexing、Embedding 等现有 CLI 进度。
- 所有运行日志写入 log\rag-full-library-YYYYMMDD-HHMMSS\logs\inventory.log 和 log\rag-full-library-YYYYMMDD-HHMMSS\logs\index.log。

中间文件清理：
- 默认会删除临时 inventory_full_pdf_workspace.py。
- 完整成功后脚本会删除本次 log\rag-full-library-YYYYMMDD-HHMMSS；如果 log\ 已空，也删除 log\。
- 如果需要保留 inventory.json 或运行日志用于审查，加 -KeepLog。
- 如果需要保留临时 inventory 脚本用于排查，加 -KeepInventory；这会保留本次 log 目录。
- 如果只想更新 workspace 不跑索引，用 -NoIndex；成功后仍按默认清理本次 log 目录，除非加 -KeepLog。

常用命令：
powershell -NoProfile -ExecutionPolicy Bypass -File scripts\run-rag-full-library.ps1 -DryRun -ScanLimit 500 -KeepLog
powershell -NoProfile -ExecutionPolicy Bypass -File scripts\run-rag-full-library.ps1
powershell -NoProfile -ExecutionPolicy Bypass -File scripts\run-rag-full-library.ps1 -NoIndex
powershell -NoProfile -ExecutionPolicy Bypass -File scripts\run-rag-full-library.ps1 -ForceRebuild
```
