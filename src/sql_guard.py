"""
sql_guard.py - hard safety check on generated SQL, run before the BigQuery dry-run.

The prompt asks the LLM to use only certified tables, but a prompt is a request, not a rule.
This check enforces it in code:
1. Read-only: the SQL must be exactly one SELECT query (no DELETE, DROP, UPDATE, INSERT, MERGE, scripts).
2. Certified tables only: every table must live in an allowed dataset of the APEX project.

Uses sqlglot to parse the SQL, so CTE names, comments and string literals are not mistaken for tables.
"""
from typing import Optional

import sqlglot
from sqlglot import exp

PROJECT_ID = "apex-activewear"
ALLOWED_DATASETS = {"gold_layer", "silver_layer"}


def check_sql_safety(sql: str) -> Optional[str]:
    """Returns None if the SQL is safe to run, otherwise a plain-English reason it was blocked."""
    try:
        statements = [s for s in sqlglot.parse(sql, read="bigquery") if s is not None]
    except sqlglot.errors.ParseError as e:
        return f"BLOCKED: the SQL could not be parsed ({str(e).splitlines()[0]})."

    if len(statements) != 1:
        return f"BLOCKED: expected exactly one query, found {len(statements)} statements."

    statement = statements[0]
    if not isinstance(statement, exp.Query):
        return f"BLOCKED: only read-only SELECT queries are allowed, got a {statement.key.upper()} statement."

    # Any write or schema change nested inside the query is also refused.
    for node in statement.walk():
        if isinstance(node, (exp.Insert, exp.Update, exp.Delete, exp.Merge, exp.Create, exp.Drop, exp.Alter)):
            return f"BLOCKED: the query contains a {node.key.upper()} statement; only read-only SELECT is allowed."

    cte_names = {cte.alias_or_name.lower() for cte in statement.find_all(exp.CTE)}
    blocked = []
    for table in statement.find_all(exp.Table):
        name, dataset, project = table.name, table.db, table.catalog
        if not name:
            continue  # e.g. UNNEST(...) or a table function, not a stored table
        if not dataset and name.lower() in cte_names:
            continue  # a CTE defined in this query
        full_name = ".".join(part for part in (project, dataset, name) if part)
        if dataset.lower() not in ALLOWED_DATASETS or (project and project.lower() != PROJECT_ID):
            blocked.append(full_name)

    if blocked:
        allowed = ", ".join(f"`{PROJECT_ID}.{d}`" for d in sorted(ALLOWED_DATASETS))
        return (f"BLOCKED: the query uses tables outside the certified datasets: {', '.join(sorted(set(blocked)))}. "
                f"Only tables in {allowed} are allowed.")
    return None
