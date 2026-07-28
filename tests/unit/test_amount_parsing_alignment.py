"""Guards against the SQL and Python amount-parsing rules drifting apart.

`_parse_amount` in defects.py and the `parse_amount` dbt macro implement the same
rule (strip spaces, swap comma for dot, parse as a number) in two languages with
no shared code path; nothing stops one from being edited without the other. This
test extracts the macro body from its source file at run time, executes it in an
in-memory DuckDB connection, and compares its output against `_parse_amount` on a
large sample of generator output plus explicit edge cases, so a future edit to
either implementation that changes behavior on their shared domain is caught here
rather than downstream in dbt.
"""

import re
from datetime import date

import duckdb
import pytest

from payments.config import get_settings, load_defect_rates
from payments.generator.defects import _parse_amount, apply_defects
from payments.generator.generate import generate_batch

_MACRO_PATTERN = re.compile(
    r"\{%-?\s*macro\s+parse_amount\(column\)\s*-?%\}(.*?)\{%-?\s*endmacro\s*-?%\}",
    re.DOTALL,
)
_COLUMN_PLACEHOLDER = re.compile(r"\{\{-?\s*column\s*-?\}\}")


def _load_parse_amount_sql(column_expr: str) -> str:
    macro_path = get_settings().project_root / "dbt" / "macros" / "parse_amount.sql"
    source = macro_path.read_text(encoding="utf-8")
    match = _MACRO_PATTERN.search(source)
    assert match is not None, (
        f"could not find a parse_amount(column) macro body in {macro_path}; "
        "the extraction pattern may be out of sync with the macro file"
    )
    body = match.group(1)
    assert _COLUMN_PLACEHOLDER.search(body) is not None, (
        f"parse_amount macro body has no {{{{ column }}}} placeholder to substitute in {macro_path}"
    )
    return _COLUMN_PLACEHOLDER.sub(column_expr, body)


_EDGE_CASES = [
    "12,50",  # comma decimal separator
    "1 234,56",  # thousands space plus comma decimal
    "42",  # plain integer, no decimal part
    "-12.34",  # negative, dot decimal
    "0.00",  # zero
]

_OUT_OF_DOMAIN_CASES = ["", "not a number"]


def _real_generator_amounts() -> list[str]:
    rates = load_defect_rates()
    amounts: list[str] = []
    for offset in range(3):
        run_date = date(2026, 7, 1 + offset)
        rows = generate_batch(run_date, n_rows=400, seed=1000 + offset)
        mutated, _ = apply_defects(rows, rates, seed=1000 + offset, run_date=run_date)
        amounts.extend(row["amount"] for row in mutated if row["amount"] is not None)
    return amounts


@pytest.fixture(scope="module")
def sample_amounts() -> list[str]:
    amounts = _real_generator_amounts()
    assert len(amounts) >= 1000, (
        f"expected at least 1000 generator-produced amounts, got {len(amounts)}"
    )
    return amounts + _EDGE_CASES


@pytest.fixture(scope="module")
def sql_expression() -> str:
    return _load_parse_amount_sql("amount_raw")


def test_sql_and_python_amount_parsing_agree_on_generator_output(sample_amounts, sql_expression):
    con = duckdb.connect(":memory:")
    try:
        values_clause = ", ".join(f"(${i + 1})" for i in range(len(sample_amounts)))
        query = f"""
            select amount_raw, {sql_expression} as parsed
            from (values {values_clause}) as t(amount_raw)
        """
        rows = con.execute(query, sample_amounts).fetchall()
    finally:
        con.close()

    assert len(rows) == len(sample_amounts)

    for raw, sql_parsed in rows:
        python_parsed = round(_parse_amount(raw), 2)
        sql_value = float(sql_parsed) if sql_parsed is not None else None
        assert sql_value == python_parsed, (
            f"parse_amount('{raw}') diverged: sql={sql_value} python={python_parsed}"
        )


def test_out_of_domain_inputs_diverge_as_documented(sql_expression):
    # Outside the agreed domain, the two implementations behave differently on
    # purpose: _parse_amount raises on unparseable input (it trusts its caller
    # to only pass syntactically plausible amounts), while the SQL macro uses
    # try_cast and resolves to NULL instead of raising. Both behaviors are
    # asserted here so a change to either is visible rather than silently
    # papered over.
    con = duckdb.connect(":memory:")
    try:
        for raw in _OUT_OF_DOMAIN_CASES:
            with pytest.raises(ValueError):
                _parse_amount(raw)

            sql_value = con.execute(
                f"select {sql_expression} as parsed from (values ($1)) as t(amount_raw)",
                [raw],
            ).fetchone()[0]
            assert sql_value is None, (
                f"expected the SQL macro to return NULL for {raw!r}, got {sql_value!r}"
            )
    finally:
        con.close()
