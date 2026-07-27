"""Command-line entry point for generating and inspecting daily batches."""

from __future__ import annotations

import argparse
import hashlib
import json
import time
from datetime import date, timedelta

import duckdb

from payments.config import ConfigError, get_settings
from payments.fx import BASE_CURRENCY, DEFAULT_QUOTE_CURRENCIES, fetch_fx_rates
from payments.generator import build_daily_batch
from payments.ingestion import LandingError, land_batch, partition_path
from payments.logging_setup import configure_logging, get_logger

EXIT_SUCCESS = 0
EXIT_UNEXPECTED_ERROR = 1
EXIT_CONFIG_ERROR = 2
EXIT_LANDING_ERROR = 3
EXIT_INVALID_DATE = 4

_EXIT_CODES_HELP = (
    "exit codes: 0 success, 1 unexpected error, 2 configuration error, "
    "3 landing error, 4 invalid date argument"
)


def _parse_date(raw: str) -> date:
    return date.fromisoformat(raw)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="payments",
        description="Generate and land synthetic daily payment batches.",
        epilog=_EXIT_CODES_HELP,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "--log-level",
        default=None,
        help="overrides the configured log level (DEBUG, INFO, WARNING, ERROR, CRITICAL)",
    )

    subparsers = parser.add_subparsers(dest="command", required=True)

    generate_parser = subparsers.add_parser(
        "generate", help="generate a daily batch and land it to the raw zone"
    )
    generate_parser.add_argument("--date", required=True, help="run date, YYYY-MM-DD")
    generate_parser.add_argument("--rows", type=int, default=None, help="row count override")
    generate_parser.add_argument("--seed", type=int, default=None, help="generator seed override")
    generate_parser.add_argument(
        "--no-land",
        action="store_true",
        help="produce the batch without writing a partition",
    )

    inspect_parser = subparsers.add_parser(
        "inspect", help="report the state of a partition without modifying it"
    )
    inspect_parser.add_argument("--date", required=True, help="partition date, YYYY-MM-DD")

    fetch_fx_parser = subparsers.add_parser(
        "fetch-fx", help="cache-first fetch of exchange rates for one date or a date range"
    )
    fetch_fx_parser.add_argument("--date", default=None, help="single date to fetch, YYYY-MM-DD")
    fetch_fx_parser.add_argument(
        "--from", dest="from_date", default=None, help="range start date, YYYY-MM-DD, inclusive"
    )
    fetch_fx_parser.add_argument(
        "--to", dest="to_date", default=None, help="range end date, YYYY-MM-DD, inclusive"
    )

    return parser


def _run_generate(args: argparse.Namespace, logger) -> int:
    try:
        run_date = _parse_date(args.date)
    except ValueError:
        logger.error("invalid --date value %r, expected YYYY-MM-DD", args.date)
        return EXIT_INVALID_DATE

    if args.rows is not None and args.rows <= 0:
        logger.error("--rows must be a positive integer, got %r", args.rows)
        return EXIT_UNEXPECTED_ERROR

    start = time.perf_counter()
    rows, report = build_daily_batch(run_date, n_rows=args.rows, seed=args.seed)

    summary = {
        "command": "generate",
        "run_date": run_date.isoformat(),
        "rows_in": report.rows_in,
        "rows_out": report.rows_out,
        "defect_counts": report.counts,
    }

    if not args.no_land:
        result = land_batch(rows, run_date)
        summary["path"] = str(result.path)
        summary["bytes"] = result.bytes_written
        summary["sha256"] = result.sha256

    summary["duration_s"] = time.perf_counter() - start

    print(json.dumps(summary))
    return EXIT_SUCCESS


def _run_inspect(args: argparse.Namespace, logger) -> int:
    try:
        run_date = _parse_date(args.date)
    except ValueError:
        logger.error("invalid --date value %r, expected YYYY-MM-DD", args.date)
        return EXIT_INVALID_DATE

    partition = partition_path(run_date)
    files = sorted(f for f in partition.iterdir() if f.is_file()) if partition.exists() else []

    if not files:
        logger.error("no partition found for %s at %s", run_date.isoformat(), partition)
        return EXIT_UNEXPECTED_ERROR

    con = duckdb.connect()
    glob = str(partition / "*.parquet")
    row_count = con.execute(f"select count(*) from read_parquet('{glob}')").fetchone()[0]

    hasher = hashlib.sha256()
    total_bytes = 0
    for file_path in files:
        data = file_path.read_bytes()
        hasher.update(data)
        total_bytes += len(data)

    summary = {
        "command": "inspect",
        "run_date": run_date.isoformat(),
        "exists": True,
        "file_count": len(files),
        "rows": row_count,
        "bytes": total_bytes,
        "sha256": hasher.hexdigest(),
    }

    print(json.dumps(summary))
    return EXIT_SUCCESS


def _run_fetch_fx(args: argparse.Namespace, logger) -> int:
    has_date = args.date is not None
    has_from = args.from_date is not None
    has_to = args.to_date is not None
    has_range = has_from or has_to

    if has_date == has_range or (has_range and has_from != has_to):
        logger.error("provide exactly one of --date, or --from together with --to")
        return EXIT_CONFIG_ERROR

    try:
        if has_date:
            dates = [_parse_date(args.date)]
        else:
            from_date = _parse_date(args.from_date)
            to_date = _parse_date(args.to_date)
            dates = []
            current = from_date
            while current <= to_date:
                dates.append(current)
                current += timedelta(days=1)
    except ValueError:
        logger.error("invalid date value, expected YYYY-MM-DD")
        return EXIT_INVALID_DATE

    settings = get_settings()
    start = time.perf_counter()
    result = fetch_fx_rates(
        settings.warehouse_path,
        dates=dates,
        symbols=DEFAULT_QUOTE_CURRENCIES,
        base=BASE_CURRENCY,
    )
    duration = time.perf_counter() - start

    fx_status_counts: dict[str, int] = {}
    unavailable_reason_counts: dict[str, int] = {}
    for row in result.rows:
        fx_status_counts[row.fx_status] = fx_status_counts.get(row.fx_status, 0) + 1
        if row.unavailable_reason is not None:
            unavailable_reason_counts[row.unavailable_reason] = (
                unavailable_reason_counts.get(row.unavailable_reason, 0) + 1
            )

    summary = {
        "command": "fetch-fx",
        "dates": [requested_date.isoformat() for requested_date in dates],
        "rows_written": len(result.rows),
        "fx_status_counts": fx_status_counts,
        "unavailable_reason_counts": unavailable_reason_counts,
        "network_calls": result.network_calls,
        "duration_s": duration,
    }

    print(json.dumps(summary))
    return EXIT_SUCCESS


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    try:
        args = parser.parse_args(argv)
    except SystemExit as exc:
        code = exc.code
        return code if isinstance(code, int) else EXIT_UNEXPECTED_ERROR

    configure_logging(args.log_level)
    logger = get_logger("payments.cli")

    try:
        if args.command == "generate":
            return _run_generate(args, logger)
        if args.command == "inspect":
            return _run_inspect(args, logger)
        if args.command == "fetch-fx":
            return _run_fetch_fx(args, logger)
        logger.error("unknown command %r", args.command)
        return EXIT_UNEXPECTED_ERROR
    except LandingError as exc:
        logger.error("landing error: %s", exc)
        return EXIT_LANDING_ERROR
    except ConfigError as exc:
        logger.error("configuration error: %s", exc)
        return EXIT_CONFIG_ERROR
    except Exception as exc:  # noqa: BLE001 - top-level command boundary
        logger.error("unexpected error: %s", exc)
        return EXIT_UNEXPECTED_ERROR
