## Clean-up all metadata

### 推荐给代理的直接提示词
```text
使用 skill zotero-cli-agents。
先读取 Zotero 条目 metadata，使用 summarize-all --detail full 导出，并排除 tag `update/metadata`。
只清洗这些字段的格式问题：title、abstractNote、publicationTitle、journalAbbreviation、language、publisher。
清洗目标：去掉 HTML 标签，修复异常空格、断裂换行、特殊符号粘连；保持原意，不改事实内容。
不要修改 DOI、url、date、pages、ISSN、extra.extra、creators、tags、notes。
只输出实际发生变更的条目，生成 cleaned-metadata.jsonl。
先执行 `uv run zot --json update --from-jsonl cleaned-metadata.jsonl --dry-run`，不要正式写入，等我确认。
```

## Daily RSS DOI Import

### 推荐给代理的直接提示词
```text
不要手动拆开执行 RSS DOI 导入流程。
直接在 E:\Desktop\CodingDaily\zotero-cli-agents 下调用 scripts\run-rss-daily-doi-import.ps1 做日常导入。
默认读取 rss-cli-agent\storage\daily\当天.selected.json。
如果需要，使用 -Date 指定日期，使用 -ProgressIntervalSeconds 调整进度刷新频率。
导入完成后检查根目录的 rss_failed_dois_YYYY-MM-DD.txt；如果没有失败且脚本成功结束，tmp 应该被自动删除。
```

## Remove Newer DOI Duplicates

### 推荐给代理的直接提示词
```text
不要用 title 模糊匹配做去重。
直接在 E:\Desktop\CodingDaily\zotero-cli-agents 下调用 scripts\remove-newer-doi-duplicates.ps1。
规则固定为：只按 DOI 精确判断；同 DOI 时保留 date_added 更早的旧条目，删除 date_added 更晚的新条目。
先执行默认 dry-run 看 keep/delete 计划；我确认后，再加 -Apply 正式删除。
```
