# zot — Let Zotero Fly in Your Terminal

<p align="center">
  <img src="asserts/banner_official.png" alt="zotero-cli-agent banner" width="720">
</p>

<p align="center">
  <a href="https://pypi.org/project/zotero-cli-agent/"><img src="https://img.shields.io/pypi/v/zotero-cli-agent?color=blue" alt="PyPI version"></a>
  <a href="https://github.com/liuchzzyy/zotero-cli-agent/actions/workflows/ci.yml"><img src="https://github.com/liuchzzyy/zotero-cli-agent/actions/workflows/ci.yml/badge.svg" alt="CI"></a>
  <a href="https://pypi.org/project/zotero-cli-agent/"><img src="https://img.shields.io/pypi/pyversions/zotero-cli-agent" alt="Python versions"></a>
  <a href="https://creativecommons.org/licenses/by-nc/4.0/"><img src="https://img.shields.io/badge/license-CC%20BY--NC%204.0-lightgrey" alt="License"></a>
  <a href="https://liuchzzyy.github.io/zotero-cli-agent/"><img src="https://img.shields.io/badge/docs-GitHub%20Pages-blue" alt="Docs"></a>
</p>

[中文](README_CN.md) | [Documentation](https://liuchzzyy.github.io/zotero-cli-agent/)

`zotero-cli-agent` is a Zotero CLI built for [Claude Code](https://claude.ai/code) and AI agents.

- **Reads** — direct local SQLite, zero-config, offline, millisecond response
- **Writes** — safe via Zotero Web API, Zotero stays in sync
- **PDF + RAG** — extract full text with caching; built-in BM25 (+ optional embedding) search over per-topic workspaces
- **Agent-native** — stable JSON envelope, typed exit codes, `zot schema`, `--dry-run`, `--idempotency-key`, NDJSON streaming
- **MCP server** — exposes 45 tools to Claude Desktop / LM Studio / Cursor via `zot mcp serve`

## Architecture

<p align="center">
  <img src="asserts/architecture.png" alt="Architecture diagram" width="720">
</p>

## Install

```bash
uv tool install zotero-cli-agent      # recommended
pipx install zotero-cli-agent         # or
pip install zotero-cli-agent          # or
```

## 60-second quickstart

```bash
# Reads work out of the box — no API key, Zotero data dir auto-detected
zot search "transformer attention"
zot read ABC123
zot export ABC123                  # BibTeX

# Writes need a Web API key (https://www.zotero.org/settings/keys)
zot config init
zot add --doi "10.1038/s41586-023-06139-9"
```

In Claude Code, just ask in natural language — the bundled skill maps requests to `zot` commands automatically:

```bash
cp -r skill/zotero-cli-agent ~/.claude/skills/
```

When stdout is not a TTY, `zot` automatically emits a stable JSON envelope so agents never need `--json`:

```json
{ "ok": true, "data": { ... }, "meta": { "request_id": "...", "cli_version": "0.4.3" } }
```

## Documentation

Full docs live at **https://liuchzzyy.github.io/zotero-cli-agent/**.

| Topic | Link |
|---|---|
| Installation & setup | [Getting started](https://liuchzzyy.github.io/zotero-cli-agent/getting-started/installation/) |
| Search, list, read | [Search guide](https://liuchzzyy.github.io/zotero-cli-agent/guide/search/) |
| Notes, tags, citations | [Notes & tags](https://liuchzzyy.github.io/zotero-cli-agent/guide/notes-tags/), [Citations](https://liuchzzyy.github.io/zotero-cli-agent/guide/citations/) |
| Add / update / delete items | [Item management](https://liuchzzyy.github.io/zotero-cli-agent/guide/item-management/) |
| Collections | [Collections](https://liuchzzyy.github.io/zotero-cli-agent/guide/collections/) |
| Workspaces + RAG | [Workspaces](https://liuchzzyy.github.io/zotero-cli-agent/guide/workspace/) |
| PDF extraction | [PDF](https://liuchzzyy.github.io/zotero-cli-agent/guide/pdf/) |
| Preprint → published | [update-status](https://liuchzzyy.github.io/zotero-cli-agent/guide/update-status/) |
| MCP setup & tools | [MCP](https://liuchzzyy.github.io/zotero-cli-agent/mcp/setup/) |
| Full CLI reference | [CLI reference](https://liuchzzyy.github.io/zotero-cli-agent/reference/cli/) |
| Agent contract (envelope, exit codes, schema) | [`docs/agent-interface.md`](docs/agent-interface.md) |
| Comparison with similar tools | [Comparison](https://liuchzzyy.github.io/zotero-cli-agent/comparison/) |
| Roadmap | [`ROADMAP.md`](ROADMAP.md) |

**Why zotero-cli-agent?** The only actively maintained Python CLI that reads Zotero's local SQLite database directly, with a clean read/write split: SQLite for fast offline reads, Web API for safe writes that Zotero stays aware of. See the [comparison page](https://liuchzzyy.github.io/zotero-cli-agent/comparison/) for a feature-by-feature breakdown against similar tools.

## Community

Join us for help, Q&A, and updates:

- **Discord:** https://discord.gg/79JF5Atuk
- **WeChat:** scan the QR code below

<p align="center">
  <img src="https://raw.githubusercontent.com/Agents365-ai/images_payment/main/qrcode/agents365ai_wechat_1.png" width="200" alt="WeChat Community Group">
</p>

## Support

If `zot` helps you, consider supporting the author:

<table>
  <tr>
    <td align="center">
      <img src="https://raw.githubusercontent.com/Agents365-ai/images_payment/main/qrcode/wechat-pay.png" width="180" alt="WeChat Pay">
      <br>
      <b>WeChat Pay</b>
    </td>
    <td align="center">
      <img src="https://raw.githubusercontent.com/Agents365-ai/images_payment/main/qrcode/alipay.png" width="180" alt="Alipay">
      <br>
      <b>Alipay</b>
    </td>
    <td align="center">
      <img src="https://raw.githubusercontent.com/Agents365-ai/images_payment/main/qrcode/buymeacoffee.png" width="180" alt="Buy Me a Coffee">
      <br>
      <b>Buy Me a Coffee</b>
    </td>
    <td align="center">
      <img src="https://raw.githubusercontent.com/Agents365-ai/images_payment/main/awarding/award.gif" width="180" alt="Give a Reward">
      <br>
      <b>Give a Reward</b>
    </td>
  </tr>
</table>

## Author

**Agents365-ai**

- Bilibili: https://space.bilibili.com/441831884
- GitHub: https://github.com/Agents365-ai

## License

[CC BY-NC 4.0](https://creativecommons.org/licenses/by-nc/4.0/) — free for non-commercial use.

