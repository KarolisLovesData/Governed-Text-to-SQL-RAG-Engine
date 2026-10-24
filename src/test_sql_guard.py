"""
test_sql_guard.py - checks the SQL safety guard. No API keys or BigQuery needed.

Run from src:  python test_sql_guard.py
1. Unsafe queries (writes, schema changes, other datasets) must be blocked.
2. Every reference and example query in data/ must still pass, so the guard never blocks good SQL.
"""
import json
from pathlib import Path

from sql_guard import check_sql_safety

DATA_DIR = Path(__file__).resolve().parent.parent / "data"

MUST_BLOCK = {
    "delete": "DELETE FROM `apex-activewear.gold_layer.customer_churn_scores` WHERE TRUE",
    "drop": "DROP TABLE `apex-activewear.gold_layer.customer_churn_scores`",
    "update": "UPDATE `apex-activewear.silver_layer.stg_users` SET country = 'x' WHERE TRUE",
    "insert": "INSERT INTO `apex-activewear.gold_layer.customer_churn_scores` (user_id) VALUES (1)",
    "second statement": "SELECT 1; DROP TABLE `apex-activewear.gold_layer.customer_churn_scores`",
    "raw bronze table": "SELECT * FROM `apex-activewear.apex_activewear_bronze.order_items`",
    "bronze hidden in a subquery": """
        WITH u AS (SELECT * FROM `apex-activewear.silver_layer.stg_users`
                   WHERE user_id IN (SELECT user_id FROM `apex-activewear.apex_activewear_bronze.users`))
        SELECT * FROM u""",
    "other project": "SELECT * FROM `other-project.gold_layer.customer_churn_scores`",
    "job history": "SELECT * FROM `region-us`.INFORMATION_SCHEMA.JOBS",
}

MUST_PASS = {
    "cte": "WITH t AS (SELECT * FROM `apex-activewear.gold_layer.customer_churn_scores`) SELECT * FROM t",
    "short table name": "SELECT * FROM gold_layer.customer_churn_scores",
    "union": "SELECT user_id FROM gold_layer.customer_churn_scores UNION ALL SELECT user_id FROM silver_layer.stg_users",
    "unnest": "SELECT v FROM `apex-activewear.gold_layer.customer_churn_scores`, UNNEST([1, 2]) AS v",
    "keywords in comments and text": "-- DROP TABLE x\nSELECT 'DELETE' AS label FROM gold_layer.customer_churn_scores",
}


def reference_queries():
    for name in ("eval_queries.json", "eval_queries_set_b.json"):
        for case in json.load(open(DATA_DIR / name, encoding="utf-8")):
            yield case["id"], case["golden_sql"]
    for case in json.load(open(DATA_DIR / "golden_queries.json", encoding="utf-8")):
        yield case["id"], case["sql"]


def main():
    failures = []
    for label, sql in MUST_BLOCK.items():
        if check_sql_safety(sql) is None:
            failures.append(f"not blocked: {label}")
    for label, sql in {**MUST_PASS, **dict(reference_queries())}.items():
        reason = check_sql_safety(sql)
        if reason:
            failures.append(f"wrongly blocked: {label} -> {reason}")

    checked = len(MUST_BLOCK) + len(MUST_PASS) + len(list(reference_queries()))
    if failures:
        print("\n".join(failures))
        raise SystemExit(f"{len(failures)} of {checked} checks failed")
    print(f"All {checked} checks passed.")


if __name__ == "__main__":
    main()
