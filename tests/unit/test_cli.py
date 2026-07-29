"""Behavior of the payments CLI: exit codes, JSON summaries, subcommands."""

import json
import subprocess
import sys
from datetime import UTC, date, datetime

import pytest

from payments.cli import (
    EXIT_CONFIG_ERROR,
    EXIT_INVALID_DATE,
    EXIT_LANDING_ERROR,
    build_parser,
    main,
)
from payments.config import ConfigError
from payments.fx import DEFAULT_QUOTE_CURRENCIES, FetchFxResult, FxRateRow
from payments.ingestion import LandingError
from payments.publish.export_marts import ExportResult


@pytest.fixture
def raw_dir(tmp_path, monkeypatch):
    monkeypatch.setenv("PAYMENTS_DATA_DIR", str(tmp_path))
    return tmp_path / "raw" / "transactions"


def _stdout_lines(capsys):
    return [line for line in capsys.readouterr().out.splitlines() if line]


def test_generate_writes_partition_and_prints_single_json_line(raw_dir, capsys):
    code = main(["generate", "--date", "2026-06-01", "--rows", "200"])
    assert code == 0

    partition = raw_dir / "ingestion_date=2026-06-01"
    assert partition.is_dir()
    assert (partition / "part-0000.parquet").exists()

    lines = _stdout_lines(capsys)
    assert len(lines) == 1
    payload = json.loads(lines[0])
    for key in (
        "command",
        "run_date",
        "rows_in",
        "rows_out",
        "defect_counts",
        "path",
        "bytes",
        "sha256",
        "duration_s",
    ):
        assert key in payload, f"missing key {key!r}"
    assert payload["command"] == "generate"
    assert payload["run_date"] == "2026-06-01"


def test_no_land_skips_write_and_omits_path(raw_dir, capsys):
    code = main(["generate", "--date", "2026-06-01", "--rows", "100", "--no-land"])
    assert code == 0
    assert not raw_dir.exists()

    lines = _stdout_lines(capsys)
    assert len(lines) == 1
    payload = json.loads(lines[0])
    assert "path" not in payload
    assert "bytes" not in payload
    assert "sha256" not in payload


def test_two_runs_produce_same_sha256(raw_dir, capsys):
    code_1 = main(["generate", "--date", "2026-06-01", "--rows", "150", "--seed", "7"])
    assert code_1 == 0
    payload_1 = json.loads(_stdout_lines(capsys)[0])

    code_2 = main(["generate", "--date", "2026-06-01", "--rows", "150", "--seed", "7"])
    assert code_2 == 0
    payload_2 = json.loads(_stdout_lines(capsys)[0])

    assert payload_1["sha256"] == payload_2["sha256"]


@pytest.mark.parametrize("bad_date", ["2026-13-45", "hier"])
def test_malformed_date_returns_four_and_writes_nothing(raw_dir, bad_date):
    code = main(["generate", "--date", bad_date, "--rows", "10"])
    assert code == 4
    assert not raw_dir.exists()


@pytest.mark.parametrize("bad_rows", [0, -5])
def test_non_positive_rows_returns_nonzero_and_writes_nothing(raw_dir, bad_rows):
    code = main(["generate", "--date", "2026-06-01", "--rows", str(bad_rows)])
    assert code != 0
    assert not raw_dir.exists()


def test_landing_error_returns_three(raw_dir, monkeypatch):
    def _boom(rows, run_date, base_dir=None):
        raise LandingError("simulated landing failure")

    monkeypatch.setattr("payments.cli.land_batch", _boom)

    code = main(["generate", "--date", "2026-06-01", "--rows", "10"])
    assert code == EXIT_LANDING_ERROR
    assert code == 3


def test_config_error_returns_two(raw_dir, monkeypatch):
    def _boom(run_date, n_rows=None, seed=None, rates=None):
        raise ConfigError("simulated configuration failure")

    monkeypatch.setattr("payments.cli.build_daily_batch", _boom)

    code = main(["generate", "--date", "2026-06-01", "--rows", "10"])
    assert code == EXIT_CONFIG_ERROR
    assert code == 2


def test_inspect_missing_partition_returns_nonzero(raw_dir):
    code = main(["inspect", "--date", "2099-01-01"])
    assert code != 0


def test_inspect_after_generate_reports_row_count(raw_dir, capsys):
    generate_code = main(["generate", "--date", "2026-06-01", "--rows", "200"])
    assert generate_code == 0
    generate_payload = json.loads(_stdout_lines(capsys)[0])

    inspect_code = main(["inspect", "--date", "2026-06-01"])
    assert inspect_code == 0
    inspect_payload = json.loads(_stdout_lines(capsys)[0])

    assert inspect_payload["rows"] == generate_payload["rows_out"]
    assert inspect_payload["exists"] is True
    assert inspect_payload["file_count"] == 1


def test_stdout_never_carries_non_json_lines(raw_dir, capsys):
    main(["generate", "--date", "2026-06-01", "--rows", "50"])
    main(["inspect", "--date", "2026-06-01"])
    main(["generate", "--date", "hier"])

    out = capsys.readouterr().out
    for line in out.splitlines():
        if not line:
            continue
        json.loads(line)


def test_module_execution_via_subprocess(tmp_path):
    env = {**__import__("os").environ, "PAYMENTS_DATA_DIR": str(tmp_path)}
    result = subprocess.run(
        [sys.executable, "-m", "payments", "generate", "--date", "2026-06-01", "--rows", "50"],
        capture_output=True,
        text=True,
        env=env,
        check=False,
    )
    assert result.returncode == 0
    lines = [line for line in result.stdout.splitlines() if line]
    assert len(lines) == 1
    payload = json.loads(lines[0])
    assert payload["command"] == "generate"


def test_build_parser_exposes_subcommands_and_help_does_not_crash():
    parser = build_parser()
    subcommand_actions = [
        action for action in parser._subparsers._group_actions if hasattr(action, "choices")
    ]
    assert subcommand_actions, "no subparsers action found"
    choices = subcommand_actions[0].choices
    assert set(choices) == {"generate", "inspect", "fetch-fx", "export-marts"}

    with pytest.raises(SystemExit) as exc_info:
        parser.parse_args(["--help"])
    assert exc_info.value.code == 0


def _make_stub_fetch_fx_rates(calls_log):
    def _stub(db_path, *, dates, symbols, base):
        calls_log.append((tuple(dates), tuple(symbols), base))
        rows = [
            FxRateRow(
                rate_date=requested_date,
                quote_currency=symbol,
                base_currency=base,
                rate=1.0,
                effective_rate_date=requested_date,
                is_carried_forward=False,
                fx_status="ok",
                unavailable_reason=None,
                fetched_at=datetime(2026, 6, 1, tzinfo=UTC),
            )
            for requested_date in dates
            for symbol in symbols
        ]
        return FetchFxResult(rows=rows, network_calls=len(dates))

    return _stub


def test_fetch_fx_nominal_date_writes_summary(raw_dir, capsys, monkeypatch, tmp_path):
    calls_log = []
    monkeypatch.setattr("payments.cli.fetch_fx_rates", _make_stub_fetch_fx_rates(calls_log))

    code = main(["fetch-fx", "--date", "2026-06-01"])
    assert code == 0
    assert calls_log == [((date(2026, 6, 1),), tuple(DEFAULT_QUOTE_CURRENCIES), "EUR")]
    assert not (tmp_path / "warehouse.duckdb").exists()

    lines = _stdout_lines(capsys)
    assert len(lines) == 1
    payload = json.loads(lines[0])
    for key in (
        "command",
        "dates",
        "rows_written",
        "fx_status_counts",
        "unavailable_reason_counts",
        "network_calls",
        "duration_s",
    ):
        assert key in payload, f"missing key {key!r}"
    assert payload["command"] == "fetch-fx"
    assert payload["dates"] == ["2026-06-01"]
    assert payload["rows_written"] == len(DEFAULT_QUOTE_CURRENCIES)
    assert payload["fx_status_counts"] == {"ok": len(DEFAULT_QUOTE_CURRENCIES)}
    assert payload["unavailable_reason_counts"] == {}
    assert payload["network_calls"] == 1


def test_fetch_fx_range_processes_inclusive_chronological_dates(raw_dir, monkeypatch):
    calls_log = []
    monkeypatch.setattr("payments.cli.fetch_fx_rates", _make_stub_fetch_fx_rates(calls_log))

    code = main(["fetch-fx", "--from", "2026-06-01", "--to", "2026-06-03"])
    assert code == 0
    assert calls_log[0][0] == (date(2026, 6, 1), date(2026, 6, 2), date(2026, 6, 3))


def test_fetch_fx_both_date_and_range_is_config_error(raw_dir, monkeypatch):
    monkeypatch.setattr("payments.cli.fetch_fx_rates", _make_stub_fetch_fx_rates([]))

    code = main(["fetch-fx", "--date", "2026-06-01", "--from", "2026-06-01", "--to", "2026-06-02"])
    assert code == EXIT_CONFIG_ERROR


def test_fetch_fx_neither_date_nor_range_is_config_error(raw_dir, monkeypatch):
    monkeypatch.setattr("payments.cli.fetch_fx_rates", _make_stub_fetch_fx_rates([]))

    code = main(["fetch-fx"])
    assert code == EXIT_CONFIG_ERROR


def test_fetch_fx_malformed_date_returns_invalid_date_code(raw_dir, monkeypatch):
    monkeypatch.setattr("payments.cli.fetch_fx_rates", _make_stub_fetch_fx_rates([]))

    code = main(["fetch-fx", "--date", "2026-13-45"])
    assert code == EXIT_INVALID_DATE


def test_export_marts_command_writes_the_serving_file(raw_dir, tmp_path, capsys, monkeypatch):
    calls = []

    def _stub_export_marts(warehouse_path, serving_path):
        calls.append((warehouse_path, serving_path))
        return ExportResult(
            serving_path=serving_path,
            row_counts={"agg_transactions_daily": 3, "dim_country": 2},
        )

    monkeypatch.setattr("payments.cli.export_marts", _stub_export_marts)

    code = main(["export-marts"])
    assert code == 0

    assert len(calls) == 1
    warehouse_path, serving_path = calls[0]
    assert warehouse_path == tmp_path / "warehouse.duckdb"
    assert serving_path == tmp_path / "serving" / "marts.duckdb"

    lines = _stdout_lines(capsys)
    assert "agg_transactions_daily 3" in lines
    assert "dim_country 2" in lines
