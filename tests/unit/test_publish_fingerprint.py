"""table_fingerprint must not depend on, and must not leak, the session time zone."""

from __future__ import annotations

import duckdb

from payments.publish.fingerprint import table_fingerprint


def _make_table(con: duckdb.DuckDBPyConnection) -> None:
    con.execute("create table events (id integer, seen_at timestamptz)")
    con.execute(
        "insert into events values "
        "(1, timestamptz '2026-01-01 10:00:00+00'), "
        "(2, timestamptz '2026-06-15 22:30:00+00')"
    )


def test_fingerprint_is_identical_across_session_time_zones() -> None:
    con = duckdb.connect()
    _make_table(con)

    fingerprints = []
    for zone in ("UTC", "Africa/Casablanca", "Europe/Luxembourg"):
        con.execute(f"set timezone = '{zone}'")
        fingerprints.append(table_fingerprint(con, "events"))

    assert fingerprints[0] == fingerprints[1] == fingerprints[2]


def test_fingerprint_restores_the_session_time_zone() -> None:
    con = duckdb.connect()
    _make_table(con)

    con.execute("set timezone = 'Africa/Casablanca'")
    table_fingerprint(con, "events")

    assert con.execute("select current_setting('TimeZone')").fetchone()[0] == "Africa/Casablanca"
