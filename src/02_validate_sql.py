"""
02_validate_sql.py - free BigQuery dry-run of EVERY reference query (eval_queries.json) and every few-shot
example (golden_queries.json).

Why: if a reference or example query no longer matches the live warehouse schema, a correct answer can be
graded wrong, or the engine can be taught outdated SQL. A dry-run costs $0 and finds this in seconds.

Usage (from src):   python 02_validate_sql.py
"""
import json
from text_to_sql_engine import validate_sql_dry_run
import eval_common as ec

bad = 0
files = [(p.name, "golden_sql") for p in sorted(ec.DATA_DIR.glob("eval_queries*.json"))] + [("golden_queries.json", "sql")]
for fname, key in files:
    print(f"\n== {fname} ==")
    for row in json.load(open(ec.DATA_DIR / fname, encoding="utf-8")):
        ok, err, _ = validate_sql_dry_run(row[key])
        print(f"  {'OK  ' if ok else 'FAIL'} {row['id']}" + ("" if ok else f"  -> {str(err)[:160]}"))
        bad += 0 if ok else 1
print(f"\n{bad} query(ies) failed the dry-run." if bad else "\nAll queries pass the dry-run.")
