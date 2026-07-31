"""Content fingerprinting for warehouse tables."""

import duckdb


def table_fingerprint(con: duckdb.DuckDBPyConnection, table: str) -> str:
    """Return a content fingerprint that does not depend on the session time zone.

    The fingerprint hashes the textual rendering of every row. DuckDB renders a
    TIMESTAMP WITH TIME ZONE value in the session time zone, so a single stored
    instant produces a different string, and therefore a different fingerprint, on
    a host set to Africa/Casablanca and inside a container set to UTC. The session
    is pinned to UTC for the computation and restored afterwards, so that
    fingerprints stay comparable across machines, containers and runs.
    """
    previous = con.execute("select current_setting('TimeZone')").fetchone()[0]
    con.execute("set timezone = 'UTC'")
    try:
        query = (
            f"select md5(string_agg(h, '' order by h)) "
            f"from (select md5(x::varchar) as h from {table} x)"
        )
        return con.sql(query).fetchone()[0]
    finally:
        con.execute(f"set timezone = '{previous}'")
