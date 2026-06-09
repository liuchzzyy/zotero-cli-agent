import sys
from pathlib import Path

from zotero_cli_agent.config import (
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
    from zotero_cli_agent.config import get_data_dir

    monkeypatch.setenv("ZOT_DATA_DIR", str(tmp_path))
    cfg = AppConfig(data_dir="/some/other/path")
    result = get_data_dir(cfg)
    assert result == tmp_path


def test_get_data_dir_falls_back_to_config(monkeypatch, tmp_path):
    from zotero_cli_agent.config import get_data_dir

    monkeypatch.delenv("ZOT_DATA_DIR", raising=False)
    cfg = AppConfig(data_dir=str(tmp_path))
    result = get_data_dir(cfg)
    assert result == tmp_path


def test_config_file_path_ignores_env_override(monkeypatch, tmp_path):
    monkeypatch.setenv("ZOT_CONFIG_PATH", str(tmp_path / "config.toml"))
    root = project_root()
    assert config_file_path() == root / ".zot" / "config.toml"


def test_project_root_defaults_to_source_repo(monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path)
    assert project_root() != tmp_path
    assert config_file_path() == project_root() / ".zot" / "config.toml"


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
hf_token = "hf-test"
device = "cuda"
batch_size = 2
""")
    from zotero_cli_agent.config import load_embedding_config

    cfg = load_embedding_config(path=config_file)
    assert cfg.url == "https://api.jina.ai/v1/embeddings"
    assert cfg.api_key == "test-key"
    assert cfg.model == "jina-embeddings-v3"
    assert cfg.hf_token == "hf-test"
    assert cfg.device == "cuda"
    assert cfg.batch_size == 2


def test_load_embedding_config_from_active_profile(tmp_path):
    config_file = tmp_path / "config.toml"
    config_file.write_text("""
[embedding]
active = "api.gitee"

[embedding.local.cpu]
provider = "sentence_transformers"
url = ""
model = "BAAI/bge-m3"
device = "cpu"
batch_size = 4

[embedding.api.gitee]
provider = "gitee"
url = "https://ai.gitee.com/v1"
api_key = "gitee-key"
model = "bge-m3"
batch_size = 10
""")
    from zotero_cli_agent.config import load_embedding_config

    cfg = load_embedding_config(path=config_file)
    assert cfg.active == "api.gitee"
    assert cfg.provider == "gitee"
    assert cfg.url == "https://ai.gitee.com/v1"
    assert cfg.api_key == "gitee-key"
    assert cfg.model == "bge-m3"
    assert cfg.batch_size == 10


def test_load_embedding_config_active_env_selects_local_gpu(tmp_path, monkeypatch):
    config_file = tmp_path / "config.toml"
    config_file.write_text("""
[embedding]
active = "api.gitee"

[embedding.api.gitee]
provider = "gitee"
url = "https://ai.gitee.com/v1"
api_key = "gitee-key"
model = "bge-m3"

[embedding.local.gpu]
provider = "sentence_transformers"
url = ""
model = "BAAI/bge-m3"
device = "cuda"
batch_size = 1
""")
    monkeypatch.setenv("ZOT_EMBEDDING_ACTIVE", "local.gpu")
    from zotero_cli_agent.config import load_embedding_config

    cfg = load_embedding_config(path=config_file, apply_env_overrides=True)
    assert cfg.active == "local.gpu"
    assert cfg.provider == "sentence_transformers"
    assert cfg.url == ""
    assert cfg.model == "BAAI/bge-m3"
    assert cfg.device == "cuda"
    assert cfg.batch_size == 1


def test_load_embedding_config_defaults(tmp_path):
    config_file = tmp_path / "config.toml"
    config_file.write_text("[zotero]\ndata_dir = '/tmp'\n")
    from zotero_cli_agent.config import load_embedding_config

    cfg = load_embedding_config(path=config_file)
    assert cfg.url == "https://api.jina.ai/v1/embeddings"
    assert cfg.api_key == ""
    assert cfg.model == "jina-embeddings-v3"
    assert cfg.device == "cpu"
    assert cfg.batch_size == 8


def test_load_embedding_config_env_override(tmp_path, monkeypatch):
    config_file = tmp_path / "config.toml"
    config_file.write_text("[zotero]\ndata_dir = '/tmp'\n")
    monkeypatch.setenv("ZOT_EMBEDDING_URL", "http://localhost:11434/v1/embeddings")
    monkeypatch.setenv("ZOT_EMBEDDING_KEY", "local-key")
    monkeypatch.setenv("ZOT_EMBEDDING_MODEL", "custom-model")
    monkeypatch.setenv("ZOT_EMBEDDING_PROVIDER", "sentence_transformers")
    monkeypatch.setenv("ZOT_EMBEDDING_HF_TOKEN", "hf-env")
    monkeypatch.setenv("ZOT_EMBEDDING_DEVICE", "cuda:0")
    monkeypatch.setenv("ZOT_EMBEDDING_BATCH_SIZE", "1")
    from zotero_cli_agent.config import load_embedding_config

    cfg = load_embedding_config(path=config_file, apply_env_overrides=True)
    assert cfg.url == "http://localhost:11434/v1/embeddings"
    assert cfg.api_key == "local-key"
    assert cfg.model == "custom-model"
    assert cfg.provider == "sentence_transformers"
    assert cfg.hf_token == "hf-env"
    assert cfg.device == "cuda:0"
    assert cfg.batch_size == 1


def test_embedding_config_is_configured():
    from zotero_cli_agent.config import EmbeddingConfig

    assert EmbeddingConfig(url="http://x", api_key="k", model="m").is_configured is True
    assert EmbeddingConfig(url="http://x", api_key="", model="m").is_configured is False
    assert EmbeddingConfig(url="", api_key="", model="Qwen/Qwen3-Embedding-0.6B", provider="sentence_transformers").is_configured is True
    assert EmbeddingConfig(url="", api_key="", model="", provider="sentence_transformers").is_configured is False


def test_load_rerank_config_from_toml(tmp_path):
    config_file = tmp_path / "config.toml"
    config_file.write_text("""
[embedding]
hf_token = "hf-from-embedding"

[rerank]
provider = "bge_reranker"
url = "https://example.invalid/rerank"
api_key = "rerank-key"
model = "BAAI/bge-reranker-v2-m3"
batch_size = 2
max_length = 384
""")
    from zotero_cli_agent.config import load_rerank_config

    cfg = load_rerank_config(path=config_file)
    assert cfg.provider == "bge_reranker"
    assert cfg.url == "https://example.invalid/rerank"
    assert cfg.api_key == "rerank-key"
    assert cfg.model == "BAAI/bge-reranker-v2-m3"
    assert cfg.hf_token == "hf-from-embedding"
    assert cfg.batch_size == 2
    assert cfg.max_length == 384
    assert cfg.is_configured is True


def test_load_rerank_config_from_active_profile(tmp_path):
    config_file = tmp_path / "config.toml"
    config_file.write_text("""
[rerank]
active = "api.gitee"

[rerank.local.bge]
provider = "bge_reranker"
model = "BAAI/bge-reranker-v2-m3"
batch_size = 4
max_length = 512

[rerank.api.gitee]
provider = "gitee"
url = "https://ai.gitee.com/v1/rerank"
api_key = "gitee-key"
model = "bge-reranker-v2-m3"
batch_size = 16
""")
    from zotero_cli_agent.config import load_rerank_config

    cfg = load_rerank_config(path=config_file)
    assert cfg.active == "api.gitee"
    assert cfg.provider == "gitee"
    assert cfg.url == "https://ai.gitee.com/v1/rerank"
    assert cfg.api_key == "gitee-key"
    assert cfg.model == "bge-reranker-v2-m3"
    assert cfg.batch_size == 16
    assert cfg.is_configured is True


def test_load_rerank_config_active_env_selects_local(tmp_path, monkeypatch):
    config_file = tmp_path / "config.toml"
    config_file.write_text("""
[rerank]
active = "api.gitee"

[rerank.api.gitee]
provider = "gitee"
url = "https://ai.gitee.com/v1/rerank"
api_key = "gitee-key"
model = "bge-reranker-v2-m3"

[rerank.local.bge]
provider = "bge_reranker"
model = "BAAI/bge-reranker-v2-m3"
batch_size = 4
""")
    monkeypatch.setenv("ZOT_RERANK_ACTIVE", "local.bge")
    from zotero_cli_agent.config import load_rerank_config

    cfg = load_rerank_config(path=config_file, apply_env_overrides=True)
    assert cfg.active == "local.bge"
    assert cfg.provider == "bge_reranker"
    assert cfg.model == "BAAI/bge-reranker-v2-m3"
    assert cfg.batch_size == 4


def test_load_rerank_config_env_override(tmp_path, monkeypatch):
    config_file = tmp_path / "config.toml"
    config_file.write_text("[rerank]\nprovider = ''\n")
    monkeypatch.setenv("ZOT_RERANK_PROVIDER", "bge_reranker")
    monkeypatch.setenv("ZOT_RERANK_URL", "https://example.invalid/rerank")
    monkeypatch.setenv("ZOT_RERANK_KEY", "rerank-key")
    monkeypatch.setenv("ZOT_RERANK_MODEL", "custom-reranker")
    monkeypatch.setenv("ZOT_RERANK_HF_TOKEN", "hf-rerank")
    monkeypatch.setenv("ZOT_RERANK_BATCH_SIZE", "3")
    monkeypatch.setenv("ZOT_RERANK_MAX_LENGTH", "256")
    from zotero_cli_agent.config import load_rerank_config

    cfg = load_rerank_config(path=config_file, apply_env_overrides=True)
    assert cfg.provider == "bge_reranker"
    assert cfg.url == "https://example.invalid/rerank"
    assert cfg.api_key == "rerank-key"
    assert cfg.model == "custom-reranker"
    assert cfg.hf_token == "hf-rerank"
    assert cfg.batch_size == 3
    assert cfg.max_length == 256


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
