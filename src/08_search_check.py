"""
08_search_check.py - tests the search step on its own, before any SQL is written.

For every benchmark question, did the search bring back the schema of each table the reference query uses?
If it did not, the LLM never saw that table, so a wrong answer is the search's fault, not the LLM's.
No judge and no SQL generation: one embedding call and two small BigQuery queries per question.

Usage (from src):   python 08_search_check.py
"""
import json

import text_to_sql_engine as engine
import eval_common as ec

EVAL_FILES = ["eval_queries.json", "eval_queries_set_b.json"]
CUTOFFS = [5, 10, 30]   # 30 is what the engine actually sends to the LLM (top_k=30)
OUT_PATH = ec.RESULTS_DIR / "search_check.json"


def schema_ids(table):
    return {f"schema_{dataset}_{table}" for dataset in ("gold_layer", "silver_layer")}


def all_tables_found(expected_tables, ranked_ids, k):
    top = set(ranked_ids[:k])
    return all(schema_ids(t) & top for t in expected_tables)


def search_one(question, max_k):
    """Ranked chunk ids for each search method, exactly as the engine retrieves them."""
    dense = engine.dense_search(engine.get_query_embedding(question), max_k)
    try:
        sparse = engine.keyword_search(question, max_k)
    except Exception as e:
        print(f"   Keyword search failed: {e}")
        sparse = dense.iloc[0:0]
    hybrid = {k: [doc_id for doc_id, _ in engine.fuse_rrf(dense.head(k), sparse.head(k), k)] for k in CUTOFFS}
    return {"vector": list(dense["id"]), "keyword": list(sparse["id"]), "hybrid": hybrid}


def main():
    cases = [c for name in EVAL_FILES for c in ec.load_cases(ec.DATA_DIR / name)]
    max_k = max(CUTOFFS)
    print(f"Search-only check on {len(cases)} questions...\n")

    results = []
    for case in cases:
        ranked = search_one(case["question"], max_k)
        found = {
            method: {k: all_tables_found(case["expected_tables"],
                                         ranked["hybrid"][k] if method == "hybrid" else ranked[method], k)
                     for k in CUTOFFS}
            for method in ("vector", "keyword", "hybrid")
        }
        mark = "found" if found["hybrid"][max_k] else "MISSED"
        print(f"[{case['id']}] hybrid top {max_k}: {mark}  (needs {', '.join(case['expected_tables'])})")
        results.append({"id": case["id"], "question": case["question"],
                        "expected_tables": case["expected_tables"], "found": found})

    n = len(results)
    summary = {method: {f"top_{k}": sum(r["found"][method][k] for r in results) for k in CUTOFFS}
               for method in ("vector", "keyword", "hybrid")}

    print("\nQuestions where search found every table the answer needs:")
    print(f"{'':10}" + "".join(f"{'top ' + str(k):>10}" for k in CUTOFFS))
    for method, label in (("vector", "Vector"), ("keyword", "Keyword"), ("hybrid", "Hybrid")):
        print(f"{label:10}" + "".join(f"{str(summary[method][f'top_{k}']) + '/' + str(n):>10}" for k in CUTOFFS))

    missed = [r["id"] for r in results if not r["found"]["hybrid"][max_k]]
    print(f"\nThe engine (hybrid, top {max_k}) missed a needed table on: {', '.join(missed) if missed else 'none'}")

    ec.write_results(OUT_PATH, {"questions": n, "code_commit": ec.code_version(), "found": summary}, results)


if __name__ == "__main__":
    main()
