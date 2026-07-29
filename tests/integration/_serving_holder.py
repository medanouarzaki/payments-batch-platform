"""Hold a DuckDB connection open and answer probe queries on demand.

This is a standalone script, launched via sys.executable, never imported by a
test module. Its leading underscore keeps pytest from collecting it.

Usage: _serving_holder.py <path> <ro|rw> <table>
Protocol on stdin, one command per line: Q runs a probe query, X exits.
"""

import sys
import traceback

import duckdb

path, mode, table = sys.argv[1], sys.argv[2], sys.argv[3]

try:
    con = duckdb.connect(path, read_only=(mode == "ro"))
    con.execute("select 1")
except Exception:
    print("HOLDER_CONNECT_FAILED", flush=True)
    traceback.print_exc(file=sys.stdout)
    sys.stdout.flush()
    sys.exit(1)

print("READY", flush=True)

for line in sys.stdin:
    command = line.strip()
    if command == "Q":
        try:
            count = con.execute(f"select count(*) from {table}").fetchone()[0]
            print(f"QUERY_OK count={count}", flush=True)
        except Exception:
            print("QUERY_FAILED", flush=True)
            traceback.print_exc(file=sys.stdout)
            sys.stdout.flush()
    elif command == "X":
        break

con.close()
print("HOLDER_CLOSED", flush=True)
