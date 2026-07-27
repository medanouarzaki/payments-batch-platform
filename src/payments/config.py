"""Typed, validated configuration for the payments batch platform."""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml

_VALID_LOG_LEVELS = {"DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"}

_FAMILY_RATE_KEYS: dict[str, tuple[str, ...]] = {
    "currency": ("missing_currency", "unknown_currency", "lowercase_currency"),
    "amount": ("non_positive_amount", "amount_formatting"),
    "timestamp": ("naive_timestamp", "offset_timestamp"),
}

_EXPECTED_RATE_KEYS = {
    "duplicate_exact",
    "near_duplicate",
    "late_event",
    "missing_currency",
    "unknown_currency",
    "lowercase_currency",
    "non_positive_amount",
    "amount_formatting",
    "malformed_country",
    "naive_timestamp",
    "offset_timestamp",
    "missing_transaction_id",
}


class ConfigError(Exception):
    """Raised when configuration values are missing or invalid."""


@dataclass(frozen=True)
class Settings:
    project_root: Path
    data_dir: Path
    raw_transactions_dir: Path
    warehouse_path: Path
    serving_dir: Path
    defects_config_path: Path
    log_level: str
    generator_seed: int
    rows_min: int
    rows_max: int
    fx_api_base_url: str

    def ensure_directories(self) -> None:
        self.data_dir.mkdir(parents=True, exist_ok=True)
        self.raw_transactions_dir.mkdir(parents=True, exist_ok=True)
        self.serving_dir.mkdir(parents=True, exist_ok=True)


@dataclass(frozen=True)
class DefectRates:
    duplicate_exact: float
    near_duplicate: float
    late_event: float
    missing_currency: float
    unknown_currency: float
    lowercase_currency: float
    non_positive_amount: float
    amount_formatting: float
    malformed_country: float
    naive_timestamp: float
    offset_timestamp: float
    missing_transaction_id: float
    late_event_min_days: int
    late_event_max_days: int


def _parse_int(name: str, raw: str) -> int:
    try:
        return int(raw)
    except ValueError as exc:
        raise ConfigError(f"{name} must be an integer, got {raw!r}") from exc


def get_settings() -> Settings:
    project_root = Path(
        os.environ.get("PAYMENTS_PROJECT_ROOT", str(Path(__file__).resolve().parents[2]))
    )
    data_dir = Path(os.environ.get("PAYMENTS_DATA_DIR", str(project_root / "data")))
    raw_transactions_dir = Path(
        os.environ.get("PAYMENTS_RAW_TRANSACTIONS_DIR", str(data_dir / "raw" / "transactions"))
    ).resolve()
    warehouse_path = Path(
        os.environ.get("PAYMENTS_WAREHOUSE_PATH", str(data_dir / "warehouse.duckdb"))
    ).resolve()
    serving_dir = data_dir / "serving"
    defects_config_path = Path(
        os.environ.get("PAYMENTS_DEFECTS_CONFIG", str(project_root / "config" / "defects.yml"))
    )

    log_level = os.environ.get("PAYMENTS_LOG_LEVEL", "INFO").upper()
    if log_level not in _VALID_LOG_LEVELS:
        raise ConfigError(
            f"PAYMENTS_LOG_LEVEL must be one of {sorted(_VALID_LOG_LEVELS)}, got {log_level!r}"
        )

    generator_seed = _parse_int(
        "PAYMENTS_GENERATOR_SEED", os.environ.get("PAYMENTS_GENERATOR_SEED", "20260601")
    )
    rows_min = _parse_int("PAYMENTS_ROWS_MIN", os.environ.get("PAYMENTS_ROWS_MIN", "30000"))
    rows_max = _parse_int("PAYMENTS_ROWS_MAX", os.environ.get("PAYMENTS_ROWS_MAX", "40000"))

    fx_api_base_url = os.environ.get("PAYMENTS_FX_API_BASE_URL", "https://api.frankfurter.dev/v1")

    if rows_min <= 0:
        raise ConfigError(f"PAYMENTS_ROWS_MIN must be positive, got {rows_min}")
    if rows_max <= 0:
        raise ConfigError(f"PAYMENTS_ROWS_MAX must be positive, got {rows_max}")
    if rows_min > rows_max:
        raise ConfigError(
            f"PAYMENTS_ROWS_MIN ({rows_min}) must not exceed PAYMENTS_ROWS_MAX ({rows_max})"
        )

    return Settings(
        project_root=project_root,
        data_dir=data_dir,
        raw_transactions_dir=raw_transactions_dir,
        warehouse_path=warehouse_path,
        serving_dir=serving_dir,
        defects_config_path=defects_config_path,
        log_level=log_level,
        generator_seed=generator_seed,
        rows_min=rows_min,
        rows_max=rows_max,
        fx_api_base_url=fx_api_base_url,
    )


def _require_rate(data: dict[str, Any], key: str) -> float:
    if key not in data:
        raise ConfigError(f"defects config is missing required key 'rates.{key}'")
    value = data[key]
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ConfigError(f"defects config rate 'rates.{key}' must be a number, got {value!r}")
    if not (0 <= value <= 1):
        raise ConfigError(f"defects config rate 'rates.{key}' must be within [0, 1], got {value!r}")
    return float(value)


def load_defect_rates(path: Path | None = None) -> DefectRates:
    if path is None:
        path = get_settings().defects_config_path

    if not path.is_file():
        raise ConfigError(f"defects config file not found: {path}")

    with path.open("r", encoding="utf-8") as handle:
        document = yaml.safe_load(handle)

    if not isinstance(document, dict):
        raise ConfigError(f"defects config must be a mapping, got {type(document).__name__}")

    if "rates" not in document:
        raise ConfigError("defects config is missing required key 'rates'")
    rates = document["rates"]
    if not isinstance(rates, dict):
        raise ConfigError("defects config key 'rates' must be a mapping")

    unknown_rate_keys = set(rates) - _EXPECTED_RATE_KEYS
    if unknown_rate_keys:
        raise ConfigError(f"defects config has unknown rate keys: {sorted(unknown_rate_keys)}")

    rate_values = {key: _require_rate(rates, key) for key in _EXPECTED_RATE_KEYS}

    for family, keys in _FAMILY_RATE_KEYS.items():
        family_sum = sum(rate_values[key] for key in keys)
        if family_sum >= 1:
            raise ConfigError(
                f"defects config rates for the '{family}' family sum to {family_sum!r}, "
                "which must be strictly less than 1"
            )

    if "late_event" not in document:
        raise ConfigError("defects config is missing required key 'late_event'")
    late_event = document["late_event"]
    if not isinstance(late_event, dict):
        raise ConfigError("defects config key 'late_event' must be a mapping")

    unknown_late_event_keys = set(late_event) - {"min_days", "max_days"}
    if unknown_late_event_keys:
        raise ConfigError(
            f"defects config has unknown late_event keys: {sorted(unknown_late_event_keys)}"
        )

    if "min_days" not in late_event:
        raise ConfigError("defects config is missing required key 'late_event.min_days'")
    if "max_days" not in late_event:
        raise ConfigError("defects config is missing required key 'late_event.max_days'")

    min_days = late_event["min_days"]
    max_days = late_event["max_days"]
    if isinstance(min_days, bool) or not isinstance(min_days, int):
        raise ConfigError(f"'late_event.min_days' must be an integer, got {min_days!r}")
    if isinstance(max_days, bool) or not isinstance(max_days, int):
        raise ConfigError(f"'late_event.max_days' must be an integer, got {max_days!r}")

    if min_days < 1:
        raise ConfigError(f"'late_event.min_days' must be >= 1, got {min_days}")
    if min_days > max_days:
        raise ConfigError(
            f"'late_event.min_days' ({min_days}) must not exceed 'late_event.max_days' ({max_days})"
        )

    return DefectRates(
        **rate_values,
        late_event_min_days=min_days,
        late_event_max_days=max_days,
    )
