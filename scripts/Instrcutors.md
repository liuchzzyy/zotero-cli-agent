## Global Run-File Rule

所有日常任务的运行中间文件、checkpoint、preview、inventory、批次日志和临时诊断文件，都放在仓库根目录的 `log\` 目录下，不要放在根目录散文件、`tmp\` 或临时 `.workspace\...` 运行目录中。

任务成功完成并复核无误后，清理本次 `log\...` 运行目录；如果 `log\` 已经为空，也删除空的 `log\` 目录。任务失败、中断、等待我确认、或需要排查时，不要清理对应 `log\...` 目录，因为其中的 checkpoint / failed / preview 文件用于恢复和审计。

注意：RAG workspace 本身仍然是持久状态，保存在 `.workspace\<workspace-name>\`；这不是运行中间文件，不能作为清理对象。只把每次运行产生的 inventory、临时脚本、批次日志、MinerU 临时资产等放进 `log\`。

## Clean-up all metadata

### 推荐给代理的直接提示词
```text
使用 skill zotero-cli-agents。
在 E:\Desktop\CodingDaily\zotero-cli-agents 下执行 metadata cleanup。先建立本次运行目录：log\metadata-cleanup-YYYYMMDD-HHMM。

先读取 Zotero 条目 metadata，使用 `uv run zot --json --detail full summarize-all --exclude-tag update/metadata --limit 5000 > log\metadata-cleanup-YYYYMMDD-HHMM\metadata-export.json` 导出未处理条目。
只清洗这些字段的格式问题：title、abstractNote、publicationTitle、journalAbbreviation、language、publisher。
清洗目标：去掉 HTML 标签，修复异常空格、断裂换行、特殊符号粘连；保持原意，不改事实内容。
边界处理：化学式、化学计量数和电荷不要插入空格，例如 CO2、H2O、MnO2、Zn2+、LiFePO4、Ni3S2；不要把小数改成 `1. 0`；不要把 `single- versus`、`regio- and` 这类并列短语合并成一个词。
不要修改 DOI、url、date、pages、ISSN、extra.extra、creators、tags、notes。
只输出实际发生变更的条目，生成 log\metadata-cleanup-YYYYMMDD-HHMM\cleaned-metadata.jsonl。

先执行 `uv run zot --json update --from-jsonl log\metadata-cleanup-YYYYMMDD-HHMM\cleaned-metadata.jsonl --dry-run > log\metadata-cleanup-YYYYMMDD-HHMM\metadata-cleanup-dry-run.json`，不要正式写入，等我确认。等待确认期间保留本次 log 目录。
我确认后，按 25-100 条切分 cleaned-metadata.jsonl 为 log\metadata-cleanup-YYYYMMDD-HHMM\cleaned-metadata-batch-N.jsonl 分批正式写入，避免长批次超时或 API 断连；如果条目很少，可以只生成一个批次，但仍按批次记录。
每批先在终端实时打印进度，例如 `[batch 2/8] applying 75 items -> log\metadata-cleanup-YYYYMMDD-HHMM\metadata-cleanup-apply-batch-2.json`，再执行 `uv run zot --json update --from-jsonl log\metadata-cleanup-YYYYMMDD-HHMM\cleaned-metadata-batch-N.jsonl --add-tag update/metadata > log\metadata-cleanup-YYYYMMDD-HHMM\metadata-cleanup-apply-batch-N.json`；如果确实只跑一个完整文件，可用 `uv run zot --json update --from-jsonl log\metadata-cleanup-YYYYMMDD-HHMM\cleaned-metadata.jsonl --add-tag update/metadata > log\metadata-cleanup-YYYYMMDD-HHMM\metadata-cleanup-apply.json`。
不要静默等待长批次；每批结束后立即报告成功数、失败数、剩余批次数和日志路径。
如果某批超时或断连，不要盲目重跑全量；先用 Web API 复核哪些条目已经同时完成字段更新和 `update/metadata` tag，再只续跑未完成条目，续跑文件也放在同一个 log\metadata-cleanup-YYYYMMDD-HHMM 目录。
全部批次完成后，复核 cleaned-metadata.jsonl 中所有 key 都已完成字段更新并带有 `update/metadata` tag。
复核无误后删除本次 log\metadata-cleanup-YYYYMMDD-HHMM 目录；如果 log\ 已空，也删除 log\。
```

## Daily RSS DOI Import

### 推荐给代理的直接提示词
```text
在 E:\Desktop\CodingDaily\zotero-cli-agents 下执行 Daily RSS DOI Import。

日常运行不要手动拆开清洗/导入步骤，直接调用 wrapper。wrapper 默认把本次 route_plan、checkpoint、summary、failed_results 等运行文件放到 log\rss-daily-doi-import_YYYY-MM-DD，并在 failed=0 成功完成后自动删除本次 log 目录：
powershell -NoProfile -ExecutionPolicy Bypass -File scripts\run-rss-daily-doi-import.ps1 -Date YYYY-MM-DD -ProgressIntervalSeconds 5

默认读取：
E:\Desktop\CodingDaily\rss-cli-agent\storage\exports\daily\YYYY-MM-DD.selected.json

如果 RSS selected JSON 在非默认位置，必须显式传入完整路径：
powershell -NoProfile -ExecutionPolicy Bypass -File scripts\run-rss-daily-doi-import.ps1 -Date YYYY-MM-DD -SelectedJson "E:\Desktop\CodingDaily\rss-cli-agent\storage\exports\daily\YYYY-MM-DD.selected.json" -ProgressIntervalSeconds 5

如果需要保留成功运行记录用于审查，加 `-KeepLog`；否则不要保留成功运行的 log 目录。

运行时必须显示实时进度。关注 processed/total、created_new、reused_existing、already_routed、failed。长时间停在 preflight/import starting 时，检查 log\rss-daily-doi-import_YYYY-MM-DD\rss_inbox_import\import_summary.json 和是否仍有 import_rss_inbox_plan.py 进程，不要凭表面输出判断卡死。

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

规则固定为：只按 DOI 精确判断；同 DOI 时保留 date_added 更早的旧条目，删除 date_added 更晚的新条目。
执行时必须给出实时进度：查询 DOI 重复项、构建 keep/delete 计划、每个重复组的 keep/delete 判断；正式删除时还要报告批次编号、已删除数、失败数、总体百分比。

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
对尚未带有 update/AInote 的非书籍条目，读取所有本地 PDF 附件，使用 MinerU 抽取 Markdown 和图片，经 CLIProxyAPI 的 gpt-5.5 生成“AI条目分析 - <title>”note，写回 Zotero Web API，并给父条目打 tag update/AInote。

默认命令。wrapper 默认把 checkpoint、preview、results、failures、notes、MinerU 临时资产和 batch logs 放到 log\ai-note-analysis-batch-YYYYMMDD-HHMMSS，并在完整成功后自动清理本次 log 目录：
powershell -NoProfile -ExecutionPolicy Bypass -File scripts\run-ai-note-batch.ps1 -BatchSize 3

先验证候选条目时用 dry-run；dry-run 成功结束后也会清理本次 log 目录，等待审查时可加 -KeepLog：
powershell -NoProfile -ExecutionPolicy Bypass -File scripts\run-ai-note-batch.ps1 -DryRun -BatchSize 3 -ScanLimit 100 -KeepLog

只处理指定条目时用：
powershell -NoProfile -ExecutionPolicy Bypass -File scripts\run-ai-note-batch.ps1 -Keys VH4PXB5G -BatchSize 1

边界和跳过规则：
- 已有 update/AInote 的父条目默认完全跳过，不重复生成 note。
- 同一个 output/checkpoint 中已经 tagged 的条目也跳过；这是为了避免 Zotero Web API 写入后，本地 SQLite 尚未同步导致重复处理。
- book 和 bookSection 跳过；当前不做书籍 AI 分析。
- 无 PDF、PDF 路径缺失、PDF 超过 max PDF 大小、MinerU 抽取失败、AI 分类 uncertain、AI 调用失败、Zotero 写入失败，都不打 update/AInote，便于下次继续。
- Zotero 读操作来自本地 SQLite；写 note/tag 通过 Zotero Web API。写入成功后需要 Zotero 同步，本地数据库才会看到新 note 和 tag。

模型和图片边界：
- 默认使用 CLIProxyAPI: http://127.0.0.1:8317/v1，模型 gpt-5.5，模式 mineru-markdown-images。
- CLIProxyAPI 的 gpt-5.5 已验证可以读取 image_url/base64 图片。
- DeepSeek deepseek-v4-pro 不支持 image_url 图片；如果切到 DeepSeek，只能用 mineru-text，不能使用 mineru-markdown-images。
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
powershell -NoProfile -ExecutionPolicy Bypass -File scripts\run-ai-note-batch.ps1 -BatchSize 3 -Model deepseek-v4-pro -BaseUrl https://api.deepseek.com -PdfInputMode mineru-text
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
