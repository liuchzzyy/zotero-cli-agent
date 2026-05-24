# AGENTS.md

This file provides guidance to coding agents working with code in this repository.

## Project

`zotero-cli-agents` (binary: `zot`) is a Zotero CLI built for Claude Code / agent use. It combines **direct local SQLite reads** with **Zotero Web API writes**, and exposes the same surface via an MCP server.

The CLI follows an agent-native contract documented in `docs/agent-interface.md`:

- stable JSON envelope
- typed exit codes
- `zot schema` introspection
- `--dry-run`
- `--idempotency-key`
- NDJSON streaming

## Common Commands

Uses `uv` as the package manager. `uv.lock` is authoritative.

```powershell
# Install dev environment
uv sync --dev --extra mcp

# Lint / type-check / test
uv run ruff check src tests
uv run mypy src/zotero_cli_agents
uv run pytest -q

# Run a single test / file / node
uv run pytest tests/test_reader.py -v
uv run pytest tests/test_reader.py::test_name -v
uv run pytest -k "search and not rag" -v

# Run the CLI from source
uv run zot --help
uv run zot search "foo"
uv run zot schema

# Build artifacts
uv build
```

CI runs on Python 3.10–3.13.

Note on PyPI publish gating: `.github/workflows/publish.yml` gates release on lint + mypy, not full pytest. Preserve that intentionally unless explicitly changing release policy.

## Architecture

### Read/write split

This is the central design constraint.

- **Reads** go through `core/reader.py` and open `zotero.sqlite` directly from the local Zotero data directory.
- **Writes** go through `core/writer.py` and use `pyzotero` against the Zotero Web API.

Never write to `zotero.sqlite` directly. That would bypass Zotero's sync model and can corrupt sync state.

### CLI shape

- `src/zotero_cli_agents/cli.py` is the Click root group.
- `src/zotero_cli_agents/commands/*.py` are self-contained commands or command groups.
- `src/zotero_cli_agents/formatter.py` implements the dual output contract:
  - Rich / human-readable output for TTY use
  - JSON envelope when piped or when `--json` is enabled
- `src/zotero_cli_agents/exit_codes.py` defines typed exit behavior. Errors should go through `emit_error(...)`.
- `zot schema` reflects the Click tree for agent consumption.

When adding a command, register it in `cli.py` and place it in the correct safety tier set. Otherwise help output and schema reporting drift.

### Core subsystems

- `src/zotero_cli_agents/core/reader.py`: SQLite read layer.
- `src/zotero_cli_agents/core/writer.py`: Web API write layer.
- `src/zotero_cli_agents/core/pdf_extractor.py` and `pdf_cache.py`: PDF extraction and caching.
- `src/zotero_cli_agents/core/workspace.py`: local workspaces under `~/.config/zot/workspaces`.
- `src/zotero_cli_agents/core/rag.py` and `rag_index.py`: workspace retrieval / indexing.
- `src/zotero_cli_agents/core/embedding_router.py`: embedding provider routing.
- `src/zotero_cli_agents/core/idempotency.py`: retry-safe mutation support.
- `src/zotero_cli_agents/core/semantic_scholar.py`: preprint-to-published lookups for `update-status`.
- `src/zotero_cli_agents/core/version_check.py`: version notice logic.

### MCP server

`src/zotero_cli_agents/mcp_server.py` exposes CLI functionality as MCP tools through `zot mcp serve`.

If a CLI command should also be available to MCP clients, mirror it here.

### Docs and skill

- `docs/agent-interface.md` is the authoritative agent contract.
- `docs/` is built with MkDocs Material.
- `skill/zotero-cli-agents/` is the bundled Claude skill.

If the CLI surface changes, keep the docs and skill in sync.

## Config and Profiles

Config lives at:

- `~/.config/zot/config.toml`

The code supports profile-based configuration and a default profile selector.

Resolution order is:

1. CLI flag
2. environment variable
3. active profile
4. defaults

Relevant env vars include:

- `ZOT_DATA_DIR`
- `ZOT_LIBRARY_ID`
- `ZOT_API_KEY`
- `ZOT_PROFILE`

Zotero data dir auto-detects when not configured, but on this machine the repository has already been validated against a real local setup.

Current local config was verified with:

- config file at `C:\Users\chengliu\.config\zot\config.toml`
- active default profile `zotero-cil`
- real local database at `C:\Users\chengliu\Zotero\zotero.sqlite`
- working Web API credentials for writes

## Conventions

- Type hints are required. `mypy` is enforced on `src/zotero_cli_agents`.
- Ruff target is Python 3.10 with line length 120.
- Keep changes surgical. Do not refactor unrelated areas.
- Preserve the current license metadata (`CC-BY-NC-4.0`) unless explicitly asked to change it.
- Do not run `git commit` or `git push` without explicit user instruction.

## Designing New Commands

When adding or refactoring a CLI command, preserve the agent-native surface:

- dual output contract
- typed exit codes
- dry-run conventions
- idempotency behavior
- schema visibility

Every top-level command must be placed in exactly one safety bucket in `src/zotero_cli_agents/cli.py`:

- read
- write
- destructive

This affects both `zot --help` grouping and `zot schema` output consumed by agents.

## Validation

Before closing substantial changes, run the smallest relevant checks first, then broader ones as needed:

1. Targeted `pytest` for touched behavior
2. `uv run mypy src/zotero_cli_agents`
3. `uv run ruff check src tests`
4. `uv run pytest -q`

For this repository on this machine, the environment has already been initialized successfully with:

```powershell
uv sync --dev --extra mcp
uv run zot --help
uv run pytest -q
```

and the full test suite passed during setup.
