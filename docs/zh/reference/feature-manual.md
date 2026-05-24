# zotero-cli-agents 功能说明书（中文）与逻辑链路

本文档面向后续优化、重构和补全功能的人，而不是面向终端用户的快速入门。目标是回答四个问题：

1. 这个仓库到底对外暴露了哪些功能。
2. 每个功能从入口到核心逻辑、再到数据落点的调用链是什么。
3. 每个功能当前依赖哪些核心模块。
4. 如果准备优化，该优先看哪些薄弱点。

本文基于当前仓库实际代码面整理，覆盖：

- CLI 顶层命令与子命令
- MCP tools 暴露面
- 核心子系统
- 统一输出契约、错误码、缓存、RAG 索引和配置解析链路

---

## 1. 产品边界与总设计

### 1.1 一句话定义

`zot` 是一个面向代理和自动化的 Zotero CLI，同时提供 MCP server。它把：

- 本地只读能力，建立在 `zotero.sqlite` 之上
- 远程写入能力，建立在 Zotero Web API 之上
- workspace/RAG 能力，建立在本地 TOML + SQLite 索引之上

统一到一个命令面和一个 MCP 工具面里。

### 1.2 最重要的架构约束

这是整个项目最核心的设计前提：

- 读操作：只能走本地 SQLite，入口是 `src/zotero_cli_agents/core/reader.py`
- 写操作：只能走 Zotero Web API，入口是 `src/zotero_cli_agents/core/writer.py`
- 绝不直接写 `zotero.sqlite`

这意味着所有优化都必须先判断自己属于：

- 本地读路径优化
- API 写路径优化
- 本地工作区 / RAG 路径优化
- 输出契约 / agent 兼容性优化

### 1.3 三层对外能力

#### A. CLI 层

- 入口：`src/zotero_cli_agents/cli.py`
- 特点：
  - 支持人类终端交互
  - 支持 JSON envelope
  - 支持 `zot schema`
  - 支持 `--dry-run`
  - 支持 `--idempotency-key`
  - 支持 NDJSON streaming

#### B. MCP 层

- CLI 入口：`src/zotero_cli_agents/commands/mcp.py`
- Server 实现：`src/zotero_cli_agents/mcp_server.py`
- 特点：
  - stdio transport
  - 工具定义与 CLI 基本镜像
  - 当前已经支持 `structuredContent`

#### C. Workspace / RAG 层

- 工作区元数据：`src/zotero_cli_agents/core/workspace.py`
- 检索与分块：`src/zotero_cli_agents/core/rag.py`
- 索引存储：`src/zotero_cli_agents/core/rag_index.py`

---

## 2. 全局逻辑链路

## 2.1 CLI 调用总链路

```text
shell / agent
  -> zot
  -> cli.py: main()
  -> 全局参数注入 (--json/--limit/--detail/--profile/--library)
  -> commands/<feature>.py
  -> core/<reader|writer|workspace|rag|pdf...>.py
  -> formatter.py / exit_codes.py
  -> stdout / stderr / exit code
```

### 关键节点

- 全局 flags 提升：`cli.py::_hoist_global_flags`
- JSON envelope：`formatter.py::envelope_ok / envelope_error / envelope_partial`
- 请求级追踪：`formatter.py::request_scope`
- 错误码映射：`exit_codes.py::exit_code_for`

## 2.2 MCP 调用总链路

```text
MCP client
  -> zot mcp serve
  -> mcp.py: serve_cmd()
  -> mcp_server.py: FastMCP tool registration
  -> tool function / _handle_* handler
  -> core/<reader|writer|workspace|rag|pdf...>.py
  -> FastMCP lowlevel server
  -> CallToolResult(content + structuredContent)
```

### 当前重要变化

当前 MCP tool 返回类型已经从裸 `dict` 调整为 `dict[str, Any]`，这样 `FastMCP` 会生成 `outputSchema`，下游 `call_tool(...)` 可直接拿到 `structuredContent`。

## 2.3 配置解析总链路

```text
命令输入
  -> --profile / env / config.toml
  -> config.py::load_config()
  -> get_data_dir()
  -> resolve_library_id()
```

配置优先级遵循：

1. CLI flag
2. 环境变量
3. active profile
4. 默认值

## 2.4 读写分流总链路

### 读路径

```text
commands/*.py
  -> load_config()
  -> get_data_dir()
  -> ZoteroReader(db_path, library_id, prefs_js_path?)
  -> SQL 查询 / 附件路径解析
  -> formatter / MCP structured output
```

### 写路径

```text
commands/*.py 或 mcp_server.py
  -> load_config()
  -> ZoteroWriter(library_id, api_key, library_type)
  -> pyzotero Web API
  -> sync_required / dry-run / idempotency / human reminder
```

---

## 3. 核心模块地图

| 模块 | 文件 | 角色 | 典型上游 | 典型下游 |
|---|---|---|---|---|
| CLI 根入口 | `src/zotero_cli_agents/cli.py` | 注册命令、注入全局参数、帮助分层 | shell / agent | `commands/*.py` |
| 配置 | `src/zotero_cli_agents/config.py` | 配置加载、profile、数据目录解析 | 所有命令 | reader / writer |
| 只读引擎 | `src/zotero_cli_agents/core/reader.py` | SQLite 查询、附件解析、近期开题、重复项等 | search/read/list/pdf/... | formatter / workspace |
| 写入引擎 | `src/zotero_cli_agents/core/writer.py` | API 写入、附件上传、集合操作、trash restore | add/update/delete/attach/... | Zotero Web API |
| DOI 解析 | `src/zotero_cli_agents/core/metadata_resolver.py` | Crossref DOI -> Zotero 字段映射 | add/add_from_pdf | writer |
| PDF 提取 | `src/zotero_cli_agents/core/pdf_extractor.py` | `pymupdf` / `mineru` 双提取链 | pdf / workspace index | pdf_cache / rag |
| PDF 缓存 | `src/zotero_cli_agents/core/pdf_cache.py` | 缓存全文提取结果 | pdf / config cache | sqlite cache |
| 工作区模型 | `src/zotero_cli_agents/core/workspace.py` | TOML 工作区管理 | workspace 命令 | rag_index |
| RAG 计算 | `src/zotero_cli_agents/core/rag.py` | chunk、BM25、semantic、RRF | workspace index/query | rag_index |
| RAG 索引 | `src/zotero_cli_agents/core/rag_index.py` | chunk 存储、BM25 term、embedding 存储 | workspace index/query | sqlite index |
| 预印本状态 | `src/zotero_cli_agents/core/semantic_scholar.py` | preprint -> published 检查 | update-status | writer |
| 输出契约 | `src/zotero_cli_agents/formatter.py` | JSON envelope / table / NDJSON | commands | stdout |
| 错误契约 | `src/zotero_cli_agents/exit_codes.py` | typed exit code + structured error | commands | shell / orchestrator |
| MCP 服务 | `src/zotero_cli_agents/mcp_server.py` | FastMCP tool registry 与 handler | MCP client | core modules |

---

## 4. 功能总览

当前仓库的用户可见功能可以按 8 组来理解：

1. 全局契约与 agent 能力
2. 配置与环境管理
3. 检索与浏览
4. PDF 与内容抽取
5. 笔记、标签、引用与导出
6. 写入与变更管理
7. 工作区与 RAG
8. MCP 服务

---

## 5. 全局契约与 agent 能力

## 5.1 全局 flags

| 功能 | 入口 | 作用 | 逻辑链路 | 优化关注点 |
|---|---|---|---|---|
| `--json` | `cli.py` | 强制 JSON 输出 | `main()` -> `ctx.obj["json"]` -> `formatter.py` | 继续保持所有命令一致性 |
| `--no-json` | `cli.py` | 强制人类可读输出 | `main()` -> `ctx.obj["json"]=False` | 与 `config show` 等特殊命令对齐 |
| `--limit` | `cli.py` | 全局默认 limit | `main()` -> `ctx.obj["limit"]` -> 各命令覆盖 | 局部命令的覆盖逻辑统一性 |
| `--detail` | `cli.py` | `minimal/standard/full` | `main()` -> formatter 精简输出 | MCP/CLI 的 detail 语义统一 |
| `--profile` | `cli.py` | 指定 profile | `main()` -> `load_config(profile=...)` | profile 缺失时的错误提示一致性 |
| `--library` | `cli.py` | `user` 或 `group:<id>` | `main()` -> `ctx.obj` -> `resolve_library_id` / writer | group 模式测试覆盖面 |
| `--no-interaction` | `cli.py` | 禁止交互 | `ctx.obj` -> destructive / config init | 所有破坏性命令都应遵守 |
| `--verbose` | `cli.py` | 预留调试输出 | `ctx.obj["verbose"]` | 当前很多命令未深用，可扩展 |

## 5.2 JSON Envelope / Error / Exit Code

| 功能 | 文件 | 作用 | 逻辑链路 | 优化关注点 |
|---|---|---|---|---|
| success envelope | `formatter.py::envelope_ok` | 统一成功输出 | command -> envelope -> stdout | 某些命令仍有裸 JSON 输出历史包袱 |
| error envelope | `formatter.py::envelope_error` | 统一错误输出 | command -> `emit_error()` -> envelope | 全仓错误 code 完整性 |
| partial envelope | `formatter.py::envelope_partial` | 批量成功/失败混合 | batch command -> partial | 批量命令覆盖面可再扩 |
| typed exit | `exit_codes.py` | exit 0/1/2/3/4/5/6 | `emit_error` -> `SystemExit` | 保持 MCP/CLI 错误语义一致 |
| request scope | `formatter.py::request_scope` | request_id + latency | `cli.py` -> contextvar -> envelope meta | 可扩到更多内部 tracing |

## 5.3 Schema / Completion / MCP Serve

| 功能 | CLI | 核心文件 | 逻辑链路 | 优化关注点 |
|---|---|---|---|---|
| 机器可读 schema | `zot schema` | `commands/schema.py` | Click tree -> `_command_to_dict()` -> JSON schema tree | schema 与 skill/docs 漂移检测自动化 |
| shell completion | `zot completions` | `commands/completions.py` | Click completion script 生成 | 文档化不同 shell 的安装链 |
| MCP server 启动 | `zot mcp serve` | `commands/mcp.py` | CLI -> import `mcp_server` -> `run(transport="stdio")` | 后续可扩展 SSE/HTTP transport |

---

## 6. 配置与环境管理功能

## 6.1 功能清单

| 功能 | CLI | 核心文件 | 数据落点 | 逻辑链路 |
|---|---|---|---|---|
| 初始化配置 | `config init` | `commands/config.py` | `~/.config/zot/config.toml` | prompt/参数 -> `AppConfig` -> `save_config()` |
| 查看配置 | `config show` | `commands/config.py` | 配置文件 + 本地 DB 路径 | `load_config()` -> `get_data_dir()` -> 数据库存在性检查 |
| profile 列表 | `config profile list` | `commands/config.py` | 配置文件 | `list_profiles()` + `get_default_profile()` |
| profile 切换 | `config profile set` | `commands/config.py` | 配置文件 | 文本层写回默认 profile |
| cache 清空 | `config cache clear` | `commands/config.py` | PDF cache sqlite | `PdfCache.stats()` -> `clear()` |
| cache 统计 | `config cache stats` | `commands/config.py` | PDF cache sqlite | `PdfCache.stats()` |
| cache 列表 | `config cache list` | `commands/config.py` | PDF cache sqlite | SQL 查询 -> `format_cache_list()` |

## 6.2 逻辑链路

```text
config command
  -> load_config() / save_config()
  -> detect_zotero_data_dir()
  -> get_data_dir()
  -> path validation / cache sqlite
```

## 6.3 优化关注点

- `config show` 当前更偏人类输出，和统一 JSON contract 还有提升空间。
- `profile set` 直接修改配置文本，后续可考虑统一 TOML 写回策略。
- cache 子命令可补更多诊断信息，例如命中率、按 extractor 分布。

---

## 7. 检索与浏览功能

## 7.1 功能清单

| 功能 | CLI | MCP Tool | 核心文件 | 读写类型 | 逻辑链路 | 优化关注点 |
|---|---|---|---|---|---|---|
| 搜索 | `search` | `search` | `commands/search.py` + `core/reader.py` | 读 | `search_cmd` -> `ZoteroReader.search()` -> `format_items` | SQL 性能、collection filter、stream 模式 |
| 列表 | `list` | `list_items` | `commands/list_cmd.py` + `core/reader.py` | 读 | 空查询 -> `reader.search("")` | 大库分页、排序性能 |
| 读取详情 | `read` | `read` | `commands/read.py` + `core/reader.py` | 读 | `reader.get_item()` + `reader.get_notes()` | detail 精细化、note 展示 |
| 相关文章 | `relate` | `relate` | `commands/relate.py` + `core/reader.py` | 读 | `reader.get_related_items()` | 相关性定义可扩展 |
| 最近条目 | `recent` | `recent` | `commands/recent.py` + `core/reader.py` | 读 | `get_recent_items(since, sort_field, limit)` | 支持更多筛选维度 |
| 重复项 | `duplicates` | `duplicates` | `commands/duplicates.py` + `core/reader.py` | 读 | `find_duplicates(strategy, threshold, limit)` | 大库性能是当前明确瓶颈 |
| 统计 | `stats` | `stats` | `commands/stats.py` + `core/reader.py` | 读 | 聚合 items/types/tags/collections | 可补增量缓存 |
| 打开资源 | `open` | 无 | `commands/open_cmd.py` | 读/系统动作 | 找 PDF 或 URL -> 系统打开 | 跨平台兼容、失败可观测性 |

## 7.2 搜索与列表共享链路

```text
search / list
  -> load_config()
  -> get_data_dir()
  -> resolve_library_id()
  -> ZoteroReader.search(...)
  -> format_items() 或 stream_items()
```

### 共享优化入口

- `reader.search()` 同时承担搜索、列表、collection filter、排序，职责较重。
- `sort=creator/title/date*` 的 SQL/排序路径值得单独 benchmark。
- 对大库应评估缓存与分页游标，而不只是 `LIMIT/OFFSET`。

## 7.3 已知优化信号

- `duplicates` 在真实库上已经出现明显性能问题，后续应优先拆分：
  - DOI 精确重复检测
  - title 相似度候选召回
  - 相似度计算与阈值过滤

---

## 8. PDF 与内容抽取功能

## 8.1 功能清单

| 功能 | CLI | MCP Tool | 核心文件 | 逻辑链路 | 优化关注点 |
|---|---|---|---|---|---|
| PDF 全文提取 | `pdf KEY` | `pdf` | `commands/pdf.py` + `core/pdf_extractor.py` + `core/pdf_cache.py` | 解析附件路径 -> 选 extractor -> 缓存命中/提取 -> 输出 | extractor fallback、缓存策略 |
| 页码范围提取 | `pdf --pages` | `pdf(pages=...)` | 同上 | 解析 page range -> extractor.extract_text(pages=...) | 参数校验与异常语义 |
| 文档大纲 | `pdf --outline` | CLI only direct option，MCP 可通过 `pdf` 获取文本后外部处理 | `commands/pdf.py` | `_parse_outline()` | heading 识别质量 |
| 指定 section | `pdf --section N` | CLI only direct option | `commands/pdf.py` | `_extract_section()` | heading 层级策略 |
| PDF 注释 | `pdf --annotations` | `annotations` | `commands/pdf.py` + `core/pdf_extractor.py` | 强制 `pymupdf` 注释提取 | 注释模型统一 |
| DOI 提取 | `add --pdf` 的子流程 | `add_from_pdf` | `core/pdf_extractor.py::extract_doi` | PDF -> DOI -> metadata resolve -> writer | DOI 召回率 |

## 8.2 逻辑链路

```text
pdf command
  -> reader.get_pdf_attachment(key)
  -> attachment resolved to local file
  -> choose extractor (mineru / pymupdf)
  -> PdfCache get/put
  -> outline parse / section extract / annotations extract
  -> format_pdf_text / format_pdf_annotations
```

## 8.3 关键模块职责

- `core/pdf_extractor.py`
  - `PyMuPdfExtractor`
  - `MinerUExtractor`
  - fallback 与 retry/backoff
- `core/pdf_cache.py`
  - 全文缓存
  - cache list/stats/clear 复用
- `commands/pdf.py`
  - 参数解析
  - extractor fallback 控制
  - outline / section 的 CLI 层逻辑

## 8.4 优化关注点

- `outline/section` 目前是基于 markdown heading 解析，不是结构化 PDF 章节树。
- `mineru -> pymupdf` fallback 已有，但失败诊断仍可更细。
- cache 是功能正确性的关键点，后续如果改 extractor，一定要同步设计 cache key。

---

## 9. 笔记、标签、引用与导出功能

## 9.1 功能清单

| 功能 | CLI | MCP Tool | 核心文件 | 类型 | 逻辑链路 | 优化关注点 |
|---|---|---|---|---|---|---|
| 查看 notes | `note KEY` | `note_view` | `commands/note.py` + `core/reader.py` | 读 | `get_notes()` -> formatter | note HTML/plain text 呈现 |
| 新增 note | `note KEY --add` | `note_add` | `commands/note.py` + `core/writer.py` | 写 | validation -> writer.add_note | note diff / idempotency |
| 更新 note | 无独立 CLI，走 MCP | `note_update` | `mcp_server.py` + `core/writer.py` | 写 | tool -> writer.update_note | CLI/MCP 面是否继续镜像 |
| 查看 tags | `tag KEY` | `tag_view` | `commands/tag.py` + `core/reader.py` | 读 | `get_item()` -> item.tags | tag 聚合统计 |
| 添加 tag | `tag --add` | `tag_add` | `commands/tag.py` + `core/writer.py` | 写 | writer.add_tags | 批量效率 |
| 移除 tag | `tag --remove` | `tag_remove` | `commands/tag.py` + `core/writer.py` | 写 | writer.remove_tags | 批量效率 |
| 导出 citation/raw | `export` | `export` | `commands/export.py` + `core/reader.py` | 读 | `reader.export_citation(fmt)` | 格式支持面 |
| 格式化引用 | `cite` | `cite` | `commands/cite.py` | 读 | item -> style format -> clipboard/print | style 扩展 |
| 单条摘要 | `summarize` | `summarize` | `commands/summarize.py` + `reader` | 读 | item + notes -> summary object | 结构字段扩展 |
| 批量摘要 | `summarize-all` | `summarize_all` | `commands/summarize_all.py` + `reader` | 读 | search all -> export summary list | 分页与大库吞吐 |

## 9.2 逻辑链路

### note/tag 读链

```text
note/tag read
  -> reader.get_notes() / reader.get_item()
  -> formatter
```

### note/tag 写链

```text
note/tag write
  -> writer
  -> Zotero API
  -> sync reminder / partial result
```

### citation/export 链

```text
export/cite
  -> reader.export_citation()
  -> raw export or formatted citation
```

## 9.3 优化关注点

- `note`、`tag` 是读写混合命令，help/schema 和安全分层可进一步精细化。
- `note_update` 仅在 MCP 暴露，CLI 是否也需要镜像是一个产品面决定。
- `summarize` 当前更像结构化抽取，不是真正 LLM 摘要；后续可明确语义。

---

## 10. 集合与回收站功能

## 10.1 集合功能

| 功能 | CLI | MCP Tool | 核心文件 | 类型 | 逻辑链路 | 优化关注点 |
|---|---|---|---|---|---|---|
| 列出集合 | `collection list` | `collection_list` | `commands/collection.py` + `reader` | 读 | `get_collections()` -> tree/json | 大型嵌套集合展示 |
| 查看集合条目 | `collection items KEY` | `collection_items` | 同上 | 读 | `get_collection_items()` | collection key/name 解析一致性 |
| 创建集合 | `collection create` | `collection_create` | `collection.py` + `writer` | 写 | writer.create_collection | 安全分层细化 |
| 移动条目 | `collection move` | `collection_move` | 同上 | 写 | item -> collection writer move | 批量移动能力 |
| 重命名集合 | `collection rename` | `collection_rename` | 同上 | 写 | writer.rename_collection | 冲突检查 |
| 删除集合 | `collection delete` | `collection_delete` | 同上 | 写 | writer.delete_collection | dry-run 与确认流程 |
| 批量重组 | `collection reorganize` | `collection_reorganize` | 同上 | 写 | plan -> create collections -> move items | 失败回滚/幂等性 |

## 10.2 回收站功能

| 功能 | CLI | MCP Tool | 核心文件 | 类型 | 逻辑链路 | 优化关注点 |
|---|---|---|---|---|---|---|
| 查看 trash | `trash list` | `trash_list` | `commands/trash.py` + `reader` | 读 | `get_trash_items()` | 更多 filter |
| 恢复 trash | `trash restore` | `trash_restore` | `commands/trash.py` + `writer` | 写 | writer.restore_from_trash | 批量恢复与 dry-run 一致性 |

## 10.3 优化关注点

- `collection` group 在顶层帮助和 schema 里是 read group，但子命令中有明显写操作。
- 如果后续优化面向 agent，建议给子命令单独标记安全级别，而不是只按顶层 group 分层。

---

## 11. 写入与变更管理功能

## 11.1 功能清单

| 功能 | CLI | MCP Tool | 核心文件 | 类型 | 逻辑链路 | 优化关注点 |
|---|---|---|---|---|---|---|
| 新增条目 | `add` | `add` | `commands/add.py` + `metadata_resolver.py` + `writer.py` | 写 | 参数解析 -> dry-run/idempotency -> DOI resolve -> writer.add_item | 写入事务拆分与重试 |
| PDF 建条目 | `add --pdf` | `add_from_pdf` | `commands/add.py` + `pdf_extractor.py` + `writer.py` | 写 | PDF -> DOI -> Crossref -> add item -> upload attachment | 失败补偿链 |
| 更新字段 | `update` | `update` | `commands/update.py` + `writer.py` | 写 | field merge -> writer.update_item | 字段级 diff 与校验 |
| 删除条目 | `delete` | `delete` | `commands/delete.py` + `writer.py` | destructive | confirm/dry-run/idempotency -> writer.delete_item | 批量删除可观测性 |
| 上传附件 | `attach` | `attach` | `commands/attach.py` + `writer.py` | 写 | file path -> upload_attachment | 大文件/失败重试 |
| 更新预印本状态 | `update-status` | `update_status` | `commands/update_status.py` + `semantic_scholar.py` + `writer.py` | destructive / optional write | read items -> check publication -> optional writer.update_item | API rate limit、dry-run 一致性 |

## 11.2 `add` 逻辑链路

```text
add
  -> 参数分支: DOI / URL / file / PDF
  -> dry-run 提前返回
  -> 凭证检查
  -> idempotency cache lookup
  -> 若 DOI: Crossref resolve_doi()
  -> writer.add_item()
  -> envelope_ok(sync_required=True)
  -> idempotency store
```

### 关键优化点

- `add --pdf` 是“多阶段动作”：
  - 先建条目
  - 再传附件
  - 如果第二步失败，需要保留补偿路径
- `resolve_doi()` 与 `writer.add_item()` 当前是串联的，可以考虑更好的失败分类。

## 11.3 `update-status` 逻辑链路

```text
update-status
  -> reader.get_item() 或 get_arxiv_preprints()
  -> extract_preprint_info()
  -> SemanticScholarClient.check_publication()
  -> dry-run 输出 or writer.update_item()
```

### 关键优化点

- 当前“检查”和“实际写回”在同一命令中，后续可拆成：
  - status inspect
  - status apply
- API 限流和批量进度可继续细化。

---

## 12. 工作区与 RAG 功能

## 12.1 工作区功能清单

| 功能 | CLI | MCP Tool | 核心文件 | 类型 | 逻辑链路 | 优化关注点 |
|---|---|---|---|---|---|---|
| 新建 workspace | `workspace new` | `workspace_new` | `commands/workspace.py` + `core/workspace.py` | 本地写 | validate name -> `save_workspace()` | metadata 扩展 |
| 删除 workspace | `workspace delete` | `workspace_delete` | 同上 | 本地删 | confirm -> `delete_workspace()` | 清理关联 idx |
| 列表 | `workspace list` | `workspace_list` | 同上 | 本地读 | `list_workspaces()` | 增加 indexed 状态显示 |
| 添加条目 | `workspace add` | `workspace_add` | `workspace.py` + `reader` | 本地写 | validate -> `reader.get_item()` -> TOML append | 批量性能 |
| 移除条目 | `workspace remove` | `workspace_remove` | `workspace.py` | 本地写 | `ws.remove_item()` -> save | 变更审计 |
| 展示条目 | `workspace show` | `workspace_show` | `workspace.py` + `reader` | 读 | TOML keys -> `reader.get_item()` -> formatter | 缺失条目清理策略 |
| 导出工作区 | `workspace export` | `workspace_export` | `workspace.py` + `reader` | 读 | items -> markdown/json/bibtex | 更丰富导出格式 |
| 导入工作区 | `workspace import` | `workspace_import` | `workspace.py` + `reader` | 本地写 | from collection/tag/search -> dedup -> save | tag/import 查询效率 |
| 工作区内搜索 | `workspace search` | `workspace_search` | `workspace.py` + `reader` | 读 | 逐条 resolve item -> substring match | 大 workspace 性能 |

## 12.2 RAG 功能清单

| 功能 | CLI | MCP Tool | 核心文件 | 类型 | 逻辑链路 | 优化关注点 |
|---|---|---|---|---|---|---|
| 建索引 | `workspace index` | `workspace_index` | `commands/workspace.py` + `rag.py` + `rag_index.py` + `pdf_extractor.py` | 本地写 | 提取 PDF -> chunk -> BM25 term -> optional embeddings | 吞吐、断点续跑、增量更新 |
| 语义问答检索 | `workspace query` | `workspace_query` | `commands/workspace.py` + `rag.py` + `rag_index.py` | 读 | load idx -> choose mode -> score -> RRF -> output | ranking 质量、结果解释性 |

## 12.3 工作区元数据链路

```text
workspace command
  -> core/workspace.py
  -> ~/.config/zot/workspaces/<name>.toml
```

### TOML 里存什么

- workspace 名称
- 创建时间
- 描述
- item key 列表
- 每个 key 对应的 title 和 added 时间

## 12.4 `workspace index` 逻辑链路

```text
workspace index
  -> load_workspace()
  -> reader.get_item() / get_pdf_attachment()
  -> convert_pdf_to_text() / convert_pdfs_to_text()
  -> build_metadata_chunk()
  -> chunk_text()
  -> RagIndex.insert_chunk_no_commit()
  -> insert_bm25_terms_no_commit()
  -> optional embed_texts()
  -> idx.set_embeddings_bulk()
  -> idx.set_meta()
```

### 关键优化点

- 这是当前最重的离线流程。
- 它混合了：
  - I/O
  - PDF 提取
  - 分块
  - 词频计算
  - embedding 生成
  - SQLite 写入
- 后续优化建议优先拆分阶段边界，使得每阶段都可单独 benchmark。

## 12.5 `workspace query` 逻辑链路

```text
workspace query
  -> open RagIndex
  -> detect whether embeddings exist
  -> choose mode: auto / bm25 / semantic / hybrid
  -> bm25_score_chunks()
  -> semantic_score_chunks()
  -> reciprocal_rank_fusion()
  -> format_workspace_query()
```

### 关键优化点

- `auto` 模式的启发式目前比较轻量，后续可增强。
- BM25 与 semantic 的归一化、融合策略是检索质量的核心优化位。
- 结果当前主要返回 chunk，不做更高层聚合。

---

## 13. MCP 功能面

## 13.1 MCP server 本体

| 功能 | 入口 | 核心文件 | 逻辑链路 | 优化关注点 |
|---|---|---|---|---|
| 启动 stdio server | `zot mcp serve` | `commands/mcp.py` + `mcp_server.py` | import FastMCP app -> `run(transport="stdio")` | 可扩 transport，连接诊断 |
| tool 注册 | `@mcp.tool()` | `mcp_server.py` | tool function -> `_handle_*` -> core | tool 元信息、output schema |
| 结构化输出 | FastMCP lowlevel | `mcp_server.py` | `dict[str, Any]` return annotation -> `outputSchema` -> `structuredContent` | 保持所有 tool 类型一致 |

## 13.2 MCP tool 总表

### 读类 tools

- `search`
- `list_items`
- `read`
- `pdf`
- `annotations`
- `summarize`
- `summarize_all`
- `export`
- `relate`
- `recent`
- `note_view`
- `tag_view`
- `collection_list`
- `collection_items`
- `duplicates`
- `cite`
- `stats`

### 写类 tools

- `note_add`
- `note_update`
- `tag_add`
- `tag_remove`
- `add`
- `delete`
- `update`
- `collection_create`
- `collection_move`
- `collection_delete`
- `collection_rename`
- `collection_reorganize`
- `trash_list`
- `trash_restore`
- `attach`
- `add_from_pdf`
- `update_status`

### workspace / RAG tools

- `workspace_new`
- `workspace_delete`
- `workspace_add`
- `workspace_remove`
- `workspace_list`
- `workspace_show`
- `workspace_export`
- `workspace_import`
- `workspace_search`
- `workspace_index`
- `workspace_query`

## 13.3 MCP 逻辑链路

```text
client.call_tool(name, args)
  -> FastMCP tool
  -> mcp_server.py public tool function
  -> _handle_* private handler
  -> core module
  -> return dict[str, Any]
  -> FastMCP outputSchema validation
  -> CallToolResult(content + structuredContent)
```

## 13.4 MCP 侧重点优化项

- 继续保证所有 tools 的 `output_schema` 可生成。
- CLI 与 MCP 的功能面要么镜像，要么明确标注文档差异。
- 对长文本 tool（如 `pdf`）可考虑 future pagination / chunked tool response。

---

## 14. 当前已知优化热点

下面这些点是后续完善时最值得优先看的：

## 14.1 高优先级

1. `duplicates` 大库性能
   - 真实库上已出现明显超时迹象
   - 应拆分候选召回与相似度计算阶段

2. `workspace index` 吞吐与可恢复性
   - 当前是重链路
   - 应提升阶段化、断点恢复、增量索引能力

3. CLI / docs / skill / schema 一致性
   - 这次已修复 `recent --sort` 示例漂移
   - 后续应建立自动校验

4. MCP structured output 一致性
   - 这次已修复主路径
   - 后续新增 tool 时必须保持返回类型可生成 `outputSchema`

## 14.2 中优先级

1. collection / tag / note 的安全分层
   - 当前顶层帮助和 schema 仍偏 group 级
   - 细粒度风险标记可提升 agent 使用安全性

2. `config show` 的 JSON 契约一致性
   - 当前更偏人类输出
   - 若面向代理，建议对齐 envelope

3. `workspace search` 的大 workspace 性能
   - 当前是逐 item resolve + substring match
   - 可考虑轻量缓存或局部索引

## 14.3 低优先级但值得规划

1. `open` 的跨平台与失败诊断
2. `cite` 的 style 扩展
3. `summarize` 语义定义更明确
4. embedding provider 路由的可观察性

---

## 15. 优化时的推荐阅读顺序

如果你准备逐项优化，推荐按下面顺序阅读代码：

1. `src/zotero_cli_agents/cli.py`
2. `src/zotero_cli_agents/formatter.py`
3. `src/zotero_cli_agents/exit_codes.py`
4. `src/zotero_cli_agents/config.py`
5. `src/zotero_cli_agents/core/reader.py`
6. `src/zotero_cli_agents/core/writer.py`
7. `src/zotero_cli_agents/commands/add.py`
8. `src/zotero_cli_agents/commands/pdf.py`
9. `src/zotero_cli_agents/commands/workspace.py`
10. `src/zotero_cli_agents/core/rag.py`
11. `src/zotero_cli_agents/core/rag_index.py`
12. `src/zotero_cli_agents/mcp_server.py`

---

## 16. 附录：功能与文件快速对照

| 功能域 | 主要命令文件 | 主要核心文件 |
|---|---|---|
| 搜索/列表/读取 | `search.py`, `list_cmd.py`, `read.py`, `recent.py`, `relate.py`, `duplicates.py`, `stats.py` | `reader.py` |
| PDF | `pdf.py` | `pdf_extractor.py`, `pdf_cache.py`, `reader.py` |
| 引用/导出/摘要 | `cite.py`, `export.py`, `summarize.py`, `summarize_all.py` | `reader.py`, `formatter.py` |
| 写入 | `add.py`, `update.py`, `delete.py`, `attach.py`, `update_status.py` | `writer.py`, `metadata_resolver.py`, `semantic_scholar.py` |
| notes/tags/collections/trash | `note.py`, `tag.py`, `collection.py`, `trash.py` | `reader.py`, `writer.py` |
| workspace/RAG | `workspace.py` | `workspace.py`, `rag.py`, `rag_index.py`, `pdf_extractor.py` |
| MCP | `mcp.py` | `mcp_server.py` |
| 配置/agent interface | `config.py`, `schema.py`, `completions.py` | `config.py`, `formatter.py`, `exit_codes.py` |

---

如果后续你要继续推进，我建议下一步不是直接“全面重构”，而是按这个文档逐组做：

1. 先定要优化的功能组
2. 再定该组的“正确性、性能、接口一致性”哪个是主目标
3. 最后才拆到具体文件与测试

这样不会把 `reader / writer / MCP / RAG` 四条链路混在一起改。

如果准备先处理第 1 批高优先级问题，可继续看：

- [`high-priority-optimization-plan.md`](./high-priority-optimization-plan.md)
