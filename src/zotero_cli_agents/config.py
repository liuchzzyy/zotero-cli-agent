from __future__ import annotations

import os
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any

if sys.version_info >= (3, 11):
    import tomllib
else:
    try:
        import tomllib
    except ModuleNotFoundError:
        import tomli as tomllib  # type: ignore[no-redef]

SETTINGS_DIRNAME = ".zot"
CONFIG_FILENAME = "config.toml"
STATE_DIRNAME = "state"


def project_root(start: Path | None = None) -> Path:
    current = (start or Path.cwd()).resolve()
    for candidate in (current, *current.parents):
        if (candidate / ".git").exists() or (candidate / "pyproject.toml").exists():
            return candidate
    return current


def settings_dir(start: Path | None = None) -> Path:
    return project_root(start) / SETTINGS_DIRNAME


def config_file_path(start: Path | None = None) -> Path:
    override = os.environ.get("ZOT_CONFIG_PATH")
    if override:
        return Path(override).expanduser().resolve()
    return settings_dir(start) / CONFIG_FILENAME


def state_dir(start: Path | None = None) -> Path:
    return settings_dir(start) / STATE_DIRNAME


CONFIG_DIR = settings_dir()
CONFIG_FILE = config_file_path()


def _load_toml_data(path: Path | None = None) -> dict[str, Any]:
    resolved = path or config_file_path()
    if not resolved.exists():
        return {}
    with open(resolved, "rb") as f:
        loaded = tomllib.load(f)
    return loaded if isinstance(loaded, dict) else {}


def _detect_zotero_data_dir_from_registry() -> Path | None:
    """Detect Zotero data directory from Windows Registry."""
    if sys.platform != "win32":
        return None

    try:
        import winreg

        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, r"Software\Zotero\Zotero") as key:
            data_dir, _ = winreg.QueryValueEx(key, "dataDir")
            if data_dir and Path(data_dir).exists():
                return Path(data_dir)
    except (OSError, FileNotFoundError, ImportError):
        pass

    return None


@dataclass
class AppConfig:
    data_dir: str = ""
    library_id: str = ""
    api_key: str = ""
    semantic_scholar_api_key: str = ""
    crossref_mailto: str = ""
    default_format: str = "table"
    default_limit: int = 50
    default_export_style: str = "bibtex"
    prefs_js_path: str = ""

    @property
    def has_write_credentials(self) -> bool:
        return bool(self.library_id and self.api_key)


@dataclass
class EmbeddingConfig:
    url: str = "https://api.jina.ai/v1/embeddings"
    api_key: str = ""
    model: str = "jina-embeddings-v3"
    provider: str = "jina"

    @property
    def is_configured(self) -> bool:
        return bool(self.url and self.api_key)


@dataclass
class PdfConfig:
    extractor: str = "mineru"
    mineru_token: str = ""


@dataclass
class AiNoteConfig:
    api_key: str = ""
    base_url: str = ""
    model: str = "gpt-5.5"
    reasoning_effort: str = ""
    pdf_input_mode: str = ""
    api_mode: str = "auto"
    chat_token_param: str = "auto"
    max_extracted_chars: int = 180000
    max_images: int = 24
    max_image_mb: int = 8


def load_config(path: Path | None = None, profile: str | None = None) -> AppConfig:
    data = _load_toml_data(path)
    if not data:
        return AppConfig()

    if "profile" in data:
        profile_name = profile or data.get("default", {}).get("profile", "")
        if profile_name and profile_name in data["profile"]:
            profile_data = data["profile"][profile_name]
            output = profile_data.get("output", data.get("output", {}))
            export = profile_data.get("export", data.get("export", {}))
            integrations = profile_data.get("integrations", data.get("integrations", {}))
            return AppConfig(
                data_dir=profile_data.get("data_dir", ""),
                library_id=profile_data.get("library_id", ""),
                api_key=profile_data.get("api_key", ""),
                semantic_scholar_api_key=profile_data.get("semantic_scholar_api_key", ""),
                crossref_mailto=profile_data.get("crossref_mailto", integrations.get("crossref_mailto", "")),
                default_format=output.get("default_format", "table"),
                default_limit=output.get("limit", 50),
                default_export_style=export.get("default_style", "bibtex"),
                prefs_js_path=profile_data.get("prefs_js_path", ""),
            )

    zotero = data.get("zotero", {})
    output = data.get("output", {})
    export = data.get("export", {})
    integrations = data.get("integrations", {})
    return AppConfig(
        data_dir=zotero.get("data_dir", ""),
        library_id=zotero.get("library_id", ""),
        api_key=zotero.get("api_key", ""),
        semantic_scholar_api_key=zotero.get("semantic_scholar_api_key", ""),
        crossref_mailto=integrations.get("crossref_mailto", ""),
        default_format=output.get("default_format", "table"),
        default_limit=output.get("limit", 50),
        default_export_style=export.get("default_style", "bibtex"),
        prefs_js_path=zotero.get("prefs_js_path", ""),
    )


def load_embedding_config(path: Path | None = None, *, apply_env_overrides: bool = False) -> EmbeddingConfig:
    defaults = EmbeddingConfig()
    data = _load_toml_data(path)
    if data:
        emb = data.get("embedding", {})
        defaults = EmbeddingConfig(
            url=emb.get("url", defaults.url),
            api_key=emb.get("api_key", defaults.api_key),
            model=emb.get("model", defaults.model),
            provider=emb.get("provider", defaults.provider),
        )
    if apply_env_overrides:
        defaults.url = os.environ.get("ZOT_EMBEDDING_URL", defaults.url)
        defaults.api_key = os.environ.get("ZOT_EMBEDDING_KEY", defaults.api_key)
        defaults.model = os.environ.get("ZOT_EMBEDDING_MODEL", defaults.model)
        defaults.provider = os.environ.get("ZOT_EMBEDDING_PROVIDER", defaults.provider)
    return defaults


def load_pdf_config(path: Path | None = None) -> PdfConfig:
    defaults = PdfConfig()
    data = _load_toml_data(path)
    if not data:
        return defaults
    pdf = data.get("pdf", {})
    return PdfConfig(
        extractor=pdf.get("extractor", defaults.extractor),
        mineru_token=pdf.get("mineru_token", defaults.mineru_token),
    )


def load_ai_note_config(path: Path | None = None) -> AiNoteConfig:
    defaults = AiNoteConfig()
    data = _load_toml_data(path)
    if not data:
        return defaults
    ai_notes = data.get("ai_notes", {})
    return AiNoteConfig(
        api_key=ai_notes.get("api_key", defaults.api_key),
        base_url=ai_notes.get("base_url", defaults.base_url),
        model=ai_notes.get("model", defaults.model),
        reasoning_effort=ai_notes.get("reasoning_effort", defaults.reasoning_effort),
        pdf_input_mode=ai_notes.get("pdf_input_mode", defaults.pdf_input_mode),
        api_mode=ai_notes.get("api_mode", defaults.api_mode),
        chat_token_param=ai_notes.get("chat_token_param", defaults.chat_token_param),
        max_extracted_chars=int(ai_notes.get("max_extracted_chars", defaults.max_extracted_chars)),
        max_images=int(ai_notes.get("max_images", defaults.max_images)),
        max_image_mb=int(ai_notes.get("max_image_mb", defaults.max_image_mb)),
    )


def list_profiles(path: Path | None = None) -> list[str]:
    """List all profile names from config."""
    return list(_load_toml_data(path).get("profile", {}).keys())


def get_default_profile(path: Path | None = None) -> str:
    """Get the default profile name from config."""
    return str(_load_toml_data(path).get("default", {}).get("profile", ""))


def save_config(config: AppConfig, path: Path | None = None) -> None:
    resolved = path or config_file_path()
    resolved.parent.mkdir(parents=True, exist_ok=True)
    lines = [
        "[zotero]",
        f"data_dir = '{config.data_dir}'",
        f"library_id = '{config.library_id}'",
        f"api_key = '{config.api_key}'",
        f"semantic_scholar_api_key = '{config.semantic_scholar_api_key}'",
        f"prefs_js_path = '{config.prefs_js_path}'",
        "",
        "[integrations]",
        f"crossref_mailto = '{config.crossref_mailto}'",
        "",
        "[output]",
        f"default_format = '{config.default_format}'",
        f"limit = {config.default_limit}",
        "",
        "[export]",
        f"default_style = '{config.default_export_style}'",
        "",
    ]
    resolved.write_text("\n".join(lines), encoding="utf-8")


def detect_zotero_data_dir(config: AppConfig) -> Path:
    if config.data_dir:
        return Path(config.data_dir).expanduser()

    if sys.platform == "win32":
        registry_dir = _detect_zotero_data_dir_from_registry()
        if registry_dir:
            return registry_dir

        appdata = Path(os.environ.get("APPDATA", ""))
        if appdata and (appdata / "Zotero").exists():
            return appdata / "Zotero"

        local_appdata = Path(os.environ.get("LOCALAPPDATA", ""))
        if local_appdata and (local_appdata / "Zotero").exists():
            return local_appdata / "Zotero"

        return appdata / "Zotero"

    return Path.home() / "Zotero"


def get_data_dir(config: AppConfig) -> Path:
    """Get Zotero data dir: env override > config > default."""
    env_dir = os.environ.get("ZOT_DATA_DIR")
    if env_dir:
        return Path(env_dir)
    return detect_zotero_data_dir(config)


def get_prefs_js_path(config: AppConfig) -> Path | None:
    """Get Zotero prefs.js path: env override > config."""
    env_path = os.environ.get("ZOT_PREFS_JS_PATH")
    if env_path:
        path = Path(env_path).expanduser()
        if path.exists():
            if path.is_dir():
                path = path / "prefs.js"
            return path if path.exists() else None
        return None
    if config.prefs_js_path:
        path = Path(config.prefs_js_path).expanduser()
        if path.exists():
            if path.is_dir():
                path = path / "prefs.js"
            return path if path.exists() else None
        return None
    return None


def resolve_write_credentials(config: AppConfig, *, library_type: str = "user", group_id: str | None = None) -> tuple[str, str]:
    library_id = os.environ.get("ZOT_LIBRARY_ID", config.library_id)
    api_key = os.environ.get("ZOT_API_KEY", config.api_key)
    if library_type == "group" and group_id:
        library_id = group_id
    return library_id, api_key


def resolve_semantic_scholar_api_key(config: AppConfig, explicit: str | None = None) -> str:
    return explicit or config.semantic_scholar_api_key


def resolve_crossref_mailto(config: AppConfig) -> str:
    return config.crossref_mailto.strip()


def resolve_library_id(db_path: Path, ctx_obj: dict) -> int:
    """Resolve the library_id from ctx.obj, defaulting to 1 (user library)."""
    if ctx_obj.get("library_type") != "group" or not ctx_obj.get("group_id"):
        return 1
    from zotero_cli_agents.core.reader import ZoteroReader

    reader = ZoteroReader(db_path)
    try:
        resolved = reader.resolve_group_library_id(int(ctx_obj["group_id"]))
    finally:
        reader.close()
    if resolved is None:
        import click

        raise click.ClickException(f"Group '{ctx_obj['group_id']}' not found in local database")
    return resolved
