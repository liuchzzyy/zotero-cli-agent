import sys
from pathlib import Path

from zotero_cli_agents.config import (
    AppConfig,
    config_file_path,
    detect_zotero_data_dir,
    get_default_profile,
    list_profiles,
    load_ai_note_config,
    load_config,
    project_root,
    save_config,
    state_dir,
)


def test_default_config():
    cfg = AppConfig()
    assert cfg.library_id == ""
    assert cfg.api_key == ""
    assert cfg.default_format == "table"
    assert cfg.default_limit == 50
    assert cfg.default_export_style == "bibtex"


def test_save_and_load_config(tmp_path):
    config_path = tmp_path / "config.toml"
    cfg = AppConfig(library_id="123", api_key="abc")
    save_config(cfg, config_path)
    loaded = load_config(config_path)
    assert loaded.library_id == "123"
    assert loaded.api_key == "abc"


def test_load_missing_config(tmp_path):
    config_path = tmp_path / "nonexistent.toml"
    cfg = load_config(config_path)
    assert cfg.library_id == ""


def test_detect_zotero_data_dir_with_override(tmp_path):
    db = tmp_path / "zotero.sqlite"
    db.touch()
    cfg = AppConfig(data_dir=str(tmp_path))
    result = detect_zotero_data_dir(cfg)
    assert result == tmp_path


def test_detect_zotero_data_dir_default(monkeypatch):
    result = detect_zotero_data_dir(AppConfig())
    if sys.platform == "win32":
        assert "Zotero" in str(result)
    else:
        assert result == Path.home() / "Zotero"


def test_config_has_write_credentials():
    cfg = AppConfig(library_id="123", api_key="abc")
    assert cfg.has_write_credentials is True
    cfg2 = AppConfig()
    assert cfg2.has_write_credentials is False


def test_get_data_dir_env_override(tmp_path, monkeypatch):
    from zotero_cli_agents.config import get_data_dir

    monkeypatch.setenv("ZOT_DATA_DIR", str(tmp_path))
    cfg = AppConfig(data_dir="/some/other/path")
    result = get_data_dir(cfg)
    assert result == tmp_path


def test_get_data_dir_falls_back_to_config(monkeypatch, tmp_path):
    from zotero_cli_agents.config import get_data_dir

    monkeypatch.delenv("ZOT_DATA_DIR", raising=False)
    cfg = AppConfig(data_dir=str(tmp_path))
    result = get_data_dir(cfg)
    assert result == tmp_path


# --- Multi-profile tests ---


def test_load_config_with_profile(tmp_path):
    config_file = tmp_path / "config.toml"
    config_file.write_text("""
[default]
profile = "lab"

[profile.personal]
library_id = "111"
api_key = "aaa"

[profile.lab]
data_dir = "/shared/zotero"
library_id = "222"
api_key = "bbb"
""")
    cfg = load_config(config_file, profile="lab")
    assert cfg.library_id == "222"
    assert cfg.api_key == "bbb"
    assert cfg.data_dir == "/shared/zotero"


def test_load_config_default_profile(tmp_path):
    config_file = tmp_path / "config.toml"
    config_file.write_text("""
[default]
profile = "personal"

[profile.personal]
library_id = "111"
api_key = "aaa"
""")
    cfg = load_config(config_file)
    assert cfg.library_id == "111"


def test_load_config_no_profiles_backward_compat(tmp_path):
    config_file = tmp_path / "config.toml"
    config_file.write_text("""
[zotero]
library_id = "old"
api_key = "old_key"
""")
    cfg = load_config(config_file)
    assert cfg.library_id == "old"


def test_list_profiles_func(tmp_path):
    config_file = tmp_path / "config.toml"
    config_file.write_text("""
[default]
profile = "personal"

[profile.personal]
library_id = "111"

[profile.lab]
library_id = "222"
""")
    profiles = list_profiles(config_file)
    assert set(profiles) == {"personal", "lab"}


def test_get_default_profile_func(tmp_path):
    config_file = tmp_path / "config.toml"
    config_file.write_text("""
[default]
profile = "lab"

[profile.lab]
library_id = "222"
""")
    assert get_default_profile(config_file) == "lab"


def test_save_and_load_config_with_backslashes(tmp_path):
    """Ensure Windows-style paths with backslashes survive save/load round-trip."""
    config_path = tmp_path / "config.toml"
    windows_path = r"C:\Users\testuser\Zotero"
    cfg = AppConfig(data_dir=windows_path, library_id="123", api_key="abc")
    save_config(cfg, config_path)
    loaded = load_config(config_path)
    assert loaded.data_dir == windows_path
    assert loaded.library_id == "123"
    assert loaded.api_key == "abc"


def test_load_embedding_config_from_toml(tmp_path):
    config_file = tmp_path / "config.toml"
    config_file.write_text("""
[zotero]
data_dir = '/tmp/zotero'

[embedding]
url = "https://api.jina.ai/v1/embeddings"
api_key = "test-key"
model = "jina-embeddings-v3"
""")
    from zotero_cli_agents.config import load_embedding_config

    cfg = load_embedding_config(path=config_file)
    assert cfg.url == "https://api.jina.ai/v1/embeddings"
    assert cfg.api_key == "test-key"
    assert cfg.model == "jina-embeddings-v3"


def test_load_embedding_config_defaults(tmp_path):
    config_file = tmp_path / "config.toml"
    config_file.write_text("[zotero]\ndata_dir = '/tmp'\n")
    from zotero_cli_agents.config import load_embedding_config

    cfg = load_embedding_config(path=config_file)
    assert cfg.url == "https://api.jina.ai/v1/embeddings"
    assert cfg.api_key == ""
    assert cfg.model == "jina-embeddings-v3"


def test_load_embedding_config_env_override(tmp_path, monkeypatch):
    config_file = tmp_path / "config.toml"
    config_file.write_text("[zotero]\ndata_dir = '/tmp'\n")
    monkeypatch.setenv("ZOT_EMBEDDING_URL", "http://localhost:11434/v1/embeddings")
    monkeypatch.setenv("ZOT_EMBEDDING_KEY", "local-key")
    monkeypatch.setenv("ZOT_EMBEDDING_MODEL", "custom-model")
    from zotero_cli_agents.config import load_embedding_config

    cfg = load_embedding_config(path=config_file, apply_env_overrides=True)
    assert cfg.url == "http://localhost:11434/v1/embeddings"
    assert cfg.api_key == "local-key"
    assert cfg.model == "custom-model"


def test_embedding_config_is_configured():
    from zotero_cli_agents.config import EmbeddingConfig

    assert EmbeddingConfig(url="http://x", api_key="k", model="m").is_configured is True
    assert EmbeddingConfig(url="http://x", api_key="", model="m").is_configured is False


def test_repo_local_config_path():
    root = project_root()
    assert config_file_path() == root / ".zot" / "config.toml"


def test_repo_local_state_dir():
    root = project_root()
    assert state_dir() == root / ".zot" / "state"


def test_load_ai_note_config_from_toml(tmp_path):
    config_file = tmp_path / "config.toml"
    config_file.write_text("""
[ai_notes]
api_key = "test-key"
base_url = "https://api.example.com/v1"
model = "deepseek-v4-pro"
reasoning_effort = "max"
pdf_input_mode = "mineru-text"
api_mode = "chat"
chat_token_param = "max_tokens"
max_extracted_chars = 1234
max_images = 6
max_image_mb = 3
""")
    cfg = load_ai_note_config(config_file)
    assert cfg.api_key == "test-key"
    assert cfg.base_url == "https://api.example.com/v1"
    assert cfg.model == "deepseek-v4-pro"
    assert cfg.reasoning_effort == "max"
    assert cfg.pdf_input_mode == "mineru-text"
    assert cfg.api_mode == "chat"
    assert cfg.chat_token_param == "max_tokens"
    assert cfg.max_extracted_chars == 1234
    assert cfg.max_images == 6
    assert cfg.max_image_mb == 3
