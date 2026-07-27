from pathlib import Path

import pytest
import yaml

from payments.config import ConfigError, load_defect_rates

REPO_DEFECTS_CONFIG = Path(__file__).resolve().parents[2] / "config" / "defects.yml"

EXPECTED_RATES = {
    "duplicate_exact": 0.005,
    "near_duplicate": 0.003,
    "late_event": 0.02,
    "missing_currency": 0.004,
    "unknown_currency": 0.002,
    "lowercase_currency": 0.01,
    "non_positive_amount": 0.003,
    "amount_formatting": 0.01,
    "malformed_country": 0.015,
    "naive_timestamp": 0.08,
    "offset_timestamp": 0.10,
    "missing_transaction_id": 0.0005,
}


def _base_document():
    return {
        "rates": dict(EXPECTED_RATES),
        "late_event": {"min_days": 1, "max_days": 5},
    }


def _write_yaml(tmp_path, document):
    path = tmp_path / "defects.yml"
    path.write_text(yaml.safe_dump(document))
    return path


def test_repo_defects_config_loads_all_twelve_rates():
    rates = load_defect_rates(REPO_DEFECTS_CONFIG)
    for key in EXPECTED_RATES:
        value = getattr(rates, key)
        assert 0 < value < 1


def test_repo_defects_config_values_match_exactly():
    rates = load_defect_rates(REPO_DEFECTS_CONFIG)
    for key, expected in EXPECTED_RATES.items():
        assert getattr(rates, key) == expected
    assert rates.late_event_min_days == 1
    assert rates.late_event_max_days == 5


def test_missing_key_raises_config_error(tmp_path):
    document = _base_document()
    del document["rates"]["unknown_currency"]
    path = _write_yaml(tmp_path, document)
    with pytest.raises(ConfigError):
        load_defect_rates(path)


def test_unknown_key_raises_config_error(tmp_path):
    document = _base_document()
    document["rates"]["totally_unknown_defect"] = 0.01
    path = _write_yaml(tmp_path, document)
    with pytest.raises(ConfigError):
        load_defect_rates(path)


def test_rate_above_one_raises_config_error(tmp_path):
    document = _base_document()
    document["rates"]["duplicate_exact"] = 1.5
    path = _write_yaml(tmp_path, document)
    with pytest.raises(ConfigError):
        load_defect_rates(path)


def test_rate_below_zero_raises_config_error(tmp_path):
    document = _base_document()
    document["rates"]["duplicate_exact"] = -0.1
    path = _write_yaml(tmp_path, document)
    with pytest.raises(ConfigError):
        load_defect_rates(path)


def test_min_days_greater_than_max_days_raises_config_error(tmp_path):
    document = _base_document()
    document["late_event"] = {"min_days": 10, "max_days": 5}
    path = _write_yaml(tmp_path, document)
    with pytest.raises(ConfigError):
        load_defect_rates(path)


def test_missing_file_raises_config_error(tmp_path):
    with pytest.raises(ConfigError):
        load_defect_rates(tmp_path / "does_not_exist.yml")


def test_currency_family_rates_summing_to_one_point_two_raises_config_error(tmp_path):
    document = _base_document()
    document["rates"]["missing_currency"] = 0.4
    document["rates"]["unknown_currency"] = 0.4
    document["rates"]["lowercase_currency"] = 0.4
    path = _write_yaml(tmp_path, document)
    with pytest.raises(ConfigError, match="currency"):
        load_defect_rates(path)


def test_amount_family_rates_summing_to_one_point_two_raises_config_error(tmp_path):
    document = _base_document()
    document["rates"]["non_positive_amount"] = 0.6
    document["rates"]["amount_formatting"] = 0.6
    path = _write_yaml(tmp_path, document)
    with pytest.raises(ConfigError, match="amount"):
        load_defect_rates(path)


def test_timestamp_family_rates_summing_to_one_point_two_raises_config_error(tmp_path):
    document = _base_document()
    document["rates"]["naive_timestamp"] = 0.6
    document["rates"]["offset_timestamp"] = 0.6
    path = _write_yaml(tmp_path, document)
    with pytest.raises(ConfigError, match="timestamp"):
        load_defect_rates(path)
