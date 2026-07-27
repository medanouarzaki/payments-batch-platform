import dataclasses

import pytest

from payments.config import ConfigError, get_settings


def test_default_paths_derive_from_each_other():
    settings = get_settings()
    assert settings.raw_transactions_dir == settings.data_dir / "raw" / "transactions"
    assert settings.warehouse_path.name == "warehouse.duckdb"
    assert settings.warehouse_path.parent == settings.data_dir
    assert settings.serving_dir == settings.data_dir / "serving"


def test_data_dir_env_var_changes_derived_paths(monkeypatch, tmp_path):
    monkeypatch.setenv("PAYMENTS_DATA_DIR", str(tmp_path))
    settings = get_settings()
    assert settings.data_dir == tmp_path
    assert settings.raw_transactions_dir == tmp_path / "raw" / "transactions"
    assert settings.warehouse_path == tmp_path / "warehouse.duckdb"
    assert settings.serving_dir == tmp_path / "serving"


def test_warehouse_path_env_var_overrides_default(monkeypatch, tmp_path):
    override = tmp_path / "elsewhere.duckdb"
    monkeypatch.setenv("PAYMENTS_WAREHOUSE_PATH", str(override))
    settings = get_settings()
    assert settings.warehouse_path == override


def test_invalid_log_level_raises_config_error(monkeypatch):
    monkeypatch.setenv("PAYMENTS_LOG_LEVEL", "NOPE")
    with pytest.raises(ConfigError, match="PAYMENTS_LOG_LEVEL"):
        get_settings()


def test_non_integer_generator_seed_raises_config_error(monkeypatch):
    monkeypatch.setenv("PAYMENTS_GENERATOR_SEED", "abc")
    with pytest.raises(ConfigError):
        get_settings()


def test_rows_min_greater_than_rows_max_raises_config_error(monkeypatch):
    monkeypatch.setenv("PAYMENTS_ROWS_MIN", "500")
    monkeypatch.setenv("PAYMENTS_ROWS_MAX", "100")
    with pytest.raises(ConfigError):
        get_settings()


def test_get_settings_has_no_side_effect_on_disk(monkeypatch, tmp_path):
    monkeypatch.setenv("PAYMENTS_DATA_DIR", str(tmp_path / "data"))
    get_settings()
    assert not (tmp_path / "data").exists()


def test_ensure_directories_creates_dirs_and_is_repeatable(monkeypatch, tmp_path):
    monkeypatch.setenv("PAYMENTS_DATA_DIR", str(tmp_path / "data"))
    settings = get_settings()
    settings.ensure_directories()
    assert settings.data_dir.is_dir()
    assert settings.raw_transactions_dir.is_dir()
    assert settings.serving_dir.is_dir()
    settings.ensure_directories()


def test_settings_is_immutable():
    settings = get_settings()
    with pytest.raises(dataclasses.FrozenInstanceError):
        settings.log_level = "DEBUG"


def test_fx_api_base_url_defaults_to_frankfurter_v1():
    settings = get_settings()
    assert settings.fx_api_base_url == "https://api.frankfurter.dev/v1"


def test_fx_api_base_url_env_var_overrides_default(monkeypatch):
    monkeypatch.setenv("PAYMENTS_FX_API_BASE_URL", "https://example.test/fx")
    settings = get_settings()
    assert settings.fx_api_base_url == "https://example.test/fx"
