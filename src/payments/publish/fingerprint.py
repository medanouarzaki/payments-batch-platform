"""Content fingerprinting for warehouse tables."""

import duckdb


def table_fingerprint(con: duckdb.DuckDBPyConnection, table: str) -> str:
    """Return a content fingerprint for a table, as an md5 hexadecimal digest."""
    query = (
        f"select md5(string_agg(h, '' order by h)) "
        f"from (select md5(x::varchar) as h from {table} x)"
    )
    return con.sql(query).fetchone()[0]
