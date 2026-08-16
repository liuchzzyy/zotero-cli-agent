# zotero-cli-agent

面向 Claude Code 与 AI Agent 的 Zotero 命令行工具（命令入口：`zot`）。

读操作直连本地 Zotero 的 SQLite 数据库，快且不依赖网络；写操作统一走 Zotero Web API，
绝不直接改写本地数据库，避免破坏 Zotero 的同步状态。

## 核心特性

- **检索与阅读**：`search` / `read` / `list` / `recent` / `stats` / `duplicates`，本地 SQLite 直读，秒级响应
- **引用与导出**：`cite`（格式化引用复制到剪贴板）、`export`（BibTeX / CSL-JSON / RIS / JSON）
- **安全写入**：`add` / `attach` / `note` / `tag` / `update` 走 Web API，支持 `--dry-run` 与幂等键
- **PDF 处理**：`pdf` 提取全文、大纲、指定章节（PyMuPDF，可选 MinerU 高精度解析）
- **主题工作区**：`workspace` 按主题整理文献，支持 FTS5 关键词检索 + Qdrant 语义检索（RAG）
- **AI 分析**：`ai_analyze` 用 LLM 分析条目与 PDF，生成结构化 HTML 笔记写回 Zotero
- **Agent 原生接口**：`--json` 稳定输出、类型化退出码、`zot schema` 自省、NDJSON 流式输出

## 安装

要求 Python 3.10+，包管理使用 [uv](https://docs.astral.sh/uv/)。

```powershell
git clone git@github.com:liuchzzyy/zotero-cli-agent.git
cd zotero-cli-agent
uv sync
```

## 快速开始

```powershell
uv run zot search "attention mechanism"    # 检索文献
uv run zot read ABC123                     # 查看条目详情
uv run zot cite ABC123 --style apa         # 复制 APA 格式引用
uv run zot --json search "BERT"            # JSON 输出，供 Agent 消费
uv run zot schema                          # 查看全部命令的机器可读 schema
```

## 配置

配置优先级：CLI 参数 > 环境变量 > 活动 profile > 默认值。

- 配置文件：`.zot/config.toml`（支持多 profile 切换）
- 环境变量：`ZOT_DATA_DIR`、`ZOT_LIBRARY_ID`、`ZOT_API_KEY`、`ZOT_PROFILE`
- 写入操作需要在 Zotero 设置页生成 API 密钥，并配置 `ZOT_LIBRARY_ID` 与 `ZOT_API_KEY`

## 架构

- 读：`core/reader.py` 直读本地 `zotero.sqlite`（只读，禁止直写）
- 写：`core/writer.py` 经 `pyzotero` 调用 Zotero Web API
- 命令按安全等级分为三级：read / write / destructive（见 `zot --help` 与 `zot schema`）

## 开发

```powershell
uv sync --dev
uv run ruff check src tests
uv run python -m mypy src/zotero_cli_agent
uv run pytest -q
```

## License

[CC BY-NC 4.0](LICENSE)
