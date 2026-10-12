"""
01_check_schema_drift.py - compares 'Apex Table Schemas.csv' (what the baseline is shown) with the LIVE BigQuery
schema (what the governed engine's index is built from).

Why: if the two differ, the Baseline and the Champion are answering from different versions of the warehouse,
which makes the comparison unfair. Free: it only reads INFORMATION_SCHEMA.

Usage (from src):   python 01_check_schema_drift.py
"""
import csv
from text_to_sql_engine import bq_client, PROJECT_ID
import eval_common as ec

live = {}
for ds in ("gold_layer", "silver_layer"):
    sql = f"SELECT table_name, column_name, data_type FROM `{PROJECT_ID}.{ds}.INFORMATION_SCHEMA.COLUMNS` ORDER BY 1, ordinal_position"
    for r in bq_client.query(sql).result():
        live.setdefault((ds, r.table_name), {})[r.column_name] = r.data_type

doc = {}
for r in csv.DictReader(open(ec.DATA_DIR / "Apex Table Schemas.csv", encoding="utf-8")):
    doc.setdefault((r["dataset_name"], r["table_name"]), {})[r["column_name"]] = r["data_type"]

print("Tables in the live warehouse but NOT in the CSV:")
for k in sorted(set(live) - set(doc)):
    print(f"  {k[0]}.{k[1]}  columns: {', '.join(f'{c} ({t})' for c, t in live[k].items())}")
print("\nTables in the CSV but NOT in the live warehouse:")
for k in sorted(set(doc) - set(live)):
    print(f"  {k[0]}.{k[1]}")
print("\nColumn differences in tables present in both:")
n = 0
for k in sorted(set(doc) & set(live)):
    add, gone = set(live[k]) - set(doc[k]), set(doc[k]) - set(live[k])
    chg = [c for c in set(live[k]) & set(doc[k]) if live[k][c] != doc[k][c]]
    if add or gone or chg:
        n += 1
        print(f"  {k[0]}.{k[1]}: only live={sorted(add)} only CSV={sorted(gone)} type changed={sorted(chg)}")
print("\nNo column differences." if n == 0 else f"\n{n} table(s) differ.")
