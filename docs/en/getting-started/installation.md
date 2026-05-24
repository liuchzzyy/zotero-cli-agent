# Installation

## Requirements

- Python 3.10 or later
- A local Zotero installation (for the SQLite database)

## Install

=== "uv (recommended)"

    ```bash
    uv tool install zotero-cli-agent
    ```

=== "pipx"

    ```bash
    pipx install zotero-cli-agent
    ```

=== "pip"

    ```bash
    pip install zotero-cli-agent
    ```

## Upgrade

=== "uv"

    ```bash
    uv tool upgrade zotero-cli-agent
    ```

=== "pipx"

    ```bash
    pipx upgrade zotero-cli-agent
    ```

=== "pip"

    ```bash
    pip install -U zotero-cli-agent
    ```

## MCP Support

To use zotero-cli-agent as an MCP server (for Claude Desktop, Cursor, LM Studio):

```bash
pip install zotero-cli-agent[mcp]
```

## Verify Installation

```bash
zot --version
```

