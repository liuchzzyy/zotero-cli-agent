# 安装

## 环境要求

- Python 3.10 或更高版本
- 本地安装的 Zotero（用于读取 SQLite 数据库）

## 安装

=== "uv（推荐）"

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

## 升级

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

## MCP 支持

如需将 zotero-cli-agent 用作 MCP 服务器（适用于 Claude Desktop、Cursor、LM Studio）：

```bash
pip install zotero-cli-agent[mcp]
```

## 验证安装

```bash
zot --version
```

