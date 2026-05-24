# Installation

## Requirements

- Python 3.10 or later
- A local Zotero installation (for the SQLite database)

## Install

=== "uv (recommended)"

    ```bash
    uv tool install zotero-cli-agents
    ```

=== "pipx"

    ```bash
    pipx install zotero-cli-agents
    ```

=== "pip"

    ```bash
    pip install zotero-cli-agents
    ```

## Upgrade

=== "uv"

    ```bash
    uv tool upgrade zotero-cli-agents
    ```

=== "pipx"

    ```bash
    pipx upgrade zotero-cli-agents
    ```

=== "pip"

    ```bash
    pip install -U zotero-cli-agents
    ```

## MCP Support

To use zotero-cli-agents as an MCP server (for Claude Desktop, Cursor, LM Studio):

```bash
pip install zotero-cli-agents[mcp]
```

## Verify Installation

```bash
zot --version
```
