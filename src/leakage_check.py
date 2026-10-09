"""
leakage_check.py - eval/index leakage audit for the Governed Text-to-SQL RAG Engine.

Question it answers: are any eval questions near-duplicates of (or heavily overlapping with)
the few-shot examples the engine retrieves at answer time?

Run from the repo root (reads data/*.json|csv, writes leakage_report.csv + eval_split.json):

    python src/leakage_check.py                 # semantic check with gemini-embedding-001 (needs GEMINI_API_KEY)
    python src/leakage_check.py --offline       # TF-IDF only, no API calls
    python src/leakage_check.py --baseline baseline_eval_results.json   # adds baseline vs champion by stratum

Tiers (per eval question):
    HIGH    near-duplicate question of a golden few-shot (semantic >= --high, or TF-IDF >= 0.45),
            or the generated SQL reuses author-chosen names that exist only in a few-shot.
    MEDIUM  semantic >= --review, or the ground-truth SQL shares a table with a golden few-shot.
    LOW     none of the above -> treat as held-out.
Note: MEDIUM is a weak signal (shared tables are common). HIGH is the one to act on.
"""
import argparse
import csv
import difflib
import json
import math
import os
import re
import statistics
from pathlib import Path

TABLE_RE = re.compile(r"`apex-activewear\.(?:gold_layer|silver_layer)\.([a-z0-9_]+)`", re.I)


# ----------------------------------------------------------------- helpers
def tables(sql):
    return {t.lower() for t in TABLE_RE.findall(sql or "")}


def norm_sql(sql):
    s = re.sub(r"`apex-activewear\.[a-z_]+\.", "`", (sql or "").lower()).replace("`", "")
    return re.sub(r"\s+", " ", s).strip()


def sql_tokens(sql):
    return re.findall(r"[a-z_][a-z0-9_]*|\d+", norm_sql(sql))


def norm_text(t):
    return re.sub(r"[^a-z0-9 ]", "", t.lower()).strip()


def defined_names(sql):
    """CTE names and AS-aliases = identifiers an author chooses (a copy fingerprint)."""
    n = norm_sql(sql)
    return set(re.findall(r"\bas\s+([a-z_][a-z0-9_]*)", n)) | set(re.findall(r"\b([a-z_][a-z0-9_]*)\s+as\s*\(", n))


def wilson(k, n, z=1.96):
    if not n:
        return (0.0, 0.0)
    p, d = k / n, 1 + z * z / n
    c = p + z * z / (2 * n)
    h = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n))
    return ((c - h) / d, (c + h) / d)


def mcnemar_exact(b, c):
    """Two-sided exact McNemar p-value from discordant counts (b: champion-only pass, c: baseline-only pass)."""
    n = b + c
    if n == 0:
        return 1.0
    k = min(b, c)
    return min(1.0, 2 * sum(math.comb(n, i) for i in range(k + 1)) / 2 ** n)


def cosine(a, b):
    num = sum(x * y for x, y in zip(a, b))
    den = math.sqrt(sum(x * x for x in a)) * math.sqrt(sum(y * y for y in b))
    return num / den if den else 0.0


# --------------------------------------------------------------- embeddings
def make_embedder():
    from google import genai
    try:
        from dotenv import load_dotenv
        for p in (Path("src/.env"), Path(".env"), Path(__file__).resolve().parent / ".env"):
            if p.exists():
                load_dotenv(p)
    except ImportError:
        pass
    key = os.getenv("GEMINI_API_KEY")
    if not key:
        raise SystemExit("GEMINI_API_KEY not found (set it, or run with --offline).")
    client = genai.Client(api_key=key)

    def embed(text):  # same call pattern as build_bq_hybrid_index.py
        try:
            return client.models.embed_content(model="gemini-embedding-001", contents=text).embeddings[0].values
        except Exception:
            return client.models.embed_content(model="models/gemini-embedding-001", contents=text).embeddings[0].values

    return embed


# --------------------------------------------------------------------- main
def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--data-dir", default="data")
    ap.add_argument("--out-dir", default=".")
    ap.add_argument("--offline", action="store_true", help="skip embeddings; use TF-IDF only")
    ap.add_argument("--high", type=float, default=0.85, help="cosine >= this => HIGH (tune using the printed distribution)")
    ap.add_argument("--review", type=float, default=0.75, help="cosine >= this => MEDIUM")
    ap.add_argument("--baseline", default=None, help="baseline_eval_results.json from baseline_evals.py")
    a = ap.parse_args()

    d = Path(a.data_dir)
    evals = json.load(open(d / "eval_queries.json", encoding="utf-8"))
    golden = json.load(open(d / "golden_queries.json", encoding="utf-8"))
    res_path = d / "eval_results.json"
    results = {}
    if res_path.exists():
        results = {r["id"]: r for r in json.load(open(res_path, encoding="utf-8"))["results"]}
    schema_cols = set()
    sp = d / "Apex Table Schemas.csv"
    if sp.exists():
        schema_cols = {r["column_name"] for r in csv.DictReader(open(sp, encoding="utf-8"))}

    # lexical similarity (TF-IDF if sklearn is available)
    try:
        from sklearn.feature_extraction.text import TfidfVectorizer
        from sklearn.metrics.pairwise import cosine_similarity
        vec = TfidfVectorizer(ngram_range=(1, 2), sublinear_tf=True, stop_words="english").fit([x["question"] for x in evals + golden])
        tfidf = cosine_similarity(vec.transform([e["question"] for e in evals]), vec.transform([g["question"] for g in golden]))
    except ImportError:
        def toks(t): return set(re.findall(r"[a-z0-9]+", t.lower()))
        tfidf = [[len(toks(e["question"]) & toks(g["question"])) / max(1, len(toks(e["question"]) | toks(g["question"]))) for g in golden] for e in evals]

    # semantic similarity (embeds golden *questions*, exactly what the index embeds for few-shots)
    sem = None
    if not a.offline:
        embed = make_embedder()
        g_vec = [embed(g["question"]) for g in golden]
        e_vec = [embed(e["question"]) for e in evals]
        sem = [[cosine(ev, gv) for gv in g_vec] for ev in e_vec]
        flat = [x for row in sem for x in row]
        print(f"Semantic cosine, all eval x golden pairs: median={statistics.median(flat):.3f} max={max(flat):.3f}  "
              f"(HIGH>={a.high}, MEDIUM>={a.review}; tune if the median is already near the thresholds)\n")

    rows = []
    for i, e in enumerate(evals):
        best, best_shared = None, ("", [])
        for j, g in enumerate(golden):
            sh = sorted(tables(e["golden_sql"]) & tables(g["sql"]))
            if len(sh) > len(best_shared[1]):
                best_shared = (g["id"], sh)  # checked against ALL goldens, not just the nearest-text one
            p = {
                "golden": g["id"],
                "exact_q": norm_text(e["question"]) == norm_text(g["question"]),
                "tfidf": round(float(tfidf[i][j]), 3),
                "semantic": round(sem[i][j], 3) if sem else None,
                "sql_seq": round(difflib.SequenceMatcher(None, sql_tokens(e["golden_sql"]), sql_tokens(g["sql"])).ratio(), 3),
                "shared_tables": sh,
            }
            key = (p["exact_q"], p["semantic"] or p["tfidf"], p["tfidf"], p["sql_seq"])
            if best is None or key > best[0]:
                best = (key, p)
        p = best[1]

        # fingerprint probe on the generated SQL (names not derivable from the question, not in this eval's own ground truth)
        gen = (results.get(e["id"]) or {}).get("generated_sql") or ""
        q_words = {w.rstrip("s") for w in re.findall(r"[a-z0-9]+", e["question"].lower())}
        derivable = lambda n: all(t.rstrip("s") in q_words for t in n.split("_"))
        own = defined_names(e["golden_sql"]) | schema_cols
        fp, fp_src = [], None
        for g in golden:
            hit = sorted(n for n in (defined_names(gen) & defined_names(g["sql"])) - own if not derivable(n))
            if len(hit) > len(fp):
                fp, fp_src = hit, g["id"]

        near_dup = p["exact_q"] or p["tfidf"] >= 0.45 or (p["semantic"] is not None and p["semantic"] >= a.high)
        medium = (p["semantic"] is not None and p["semantic"] >= a.review) or bool(best_shared[1])
        tier = "HIGH" if (near_dup or fp) else ("MEDIUM" if medium else "LOW")

        r = results.get(e["id"], {})
        exp = {t.lower() for t in e["expected_tables"]}
        rows.append({
            "id": e["id"], "tier": tier, "nearest_golden": p["golden"], "tfidf": p["tfidf"], "semantic": p["semantic"],
            "sql_seq": p["sql_seq"], "shared_tables": ";".join(best_shared[1]), "shared_with": best_shared[0],
            "copied_names": ";".join(fp),
            "copied_from": fp_src or "", "champion_semantic_pass": r.get("semantic_logic_pass"),
            "schema_pass_reported": r.get("schema_precision_pass"),
            "schema_pass_exact": (exp <= tables(gen)) if gen else None,
        })

    # eval-vs-eval duplicates (they shrink the effective n)
    dups = []
    for i in range(len(evals)):
        for j in range(i + 1, len(evals)):
            s = difflib.SequenceMatcher(None, sql_tokens(evals[i]["golden_sql"]), sql_tokens(evals[j]["golden_sql"])).ratio()
            if s >= 0.85:
                dups.append((evals[i]["id"], evals[j]["id"], round(s, 2)))

    out = Path(a.out_dir)
    out.mkdir(parents=True, exist_ok=True)
    with open(out / "leakage_report.csv", "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
        w.writeheader()
        w.writerows(rows)
    split = {
        "held_out_LOW": [r["id"] for r in rows if r["tier"] == "LOW"],
        "pattern_seen_MEDIUM": [r["id"] for r in rows if r["tier"] == "MEDIUM"],
        "near_duplicate_HIGH": [r["id"] for r in rows if r["tier"] == "HIGH"],
        "eval_vs_eval_duplicate_sql": dups,
    }
    json.dump(split, open(out / "eval_split.json", "w", encoding="utf-8"), indent=2)

    # ------------------------------------------------------------- report
    print(f"{'id':19}{'tier':7}{'nearest golden':23}{'tfidf':>6}{'sem':>7}{'sqlseq':>7}  shared tables | copied names")
    for r in rows:
        sm = f"{r['semantic']:.2f}" if r["semantic"] is not None else "  -"
        print(f"{r['id']:19}{r['tier']:7}{r['nearest_golden']:23}{r['tfidf']:6.2f}{sm:>7}{r['sql_seq']:7.2f}  {r['shared_tables'] or '-'} | {r['copied_names'] or '-'}")
    print("\nTier counts:", {t: sum(1 for r in rows if r["tier"] == t) for t in ("HIGH", "MEDIUM", "LOW")})
    print("Eval-vs-eval duplicate ground-truth SQL (effective n is smaller):", dups or "none")

    def stratum(label, sel, key):
        sel = [r for r in sel if r[key] is not None]
        k, n = sum(1 for r in sel if r[key]), len(sel)
        lo, hi = wilson(k, n)
        print(f"  {label:32}{k}/{n} = {100 * k / n:5.1f}%  (95% CI {100 * lo:.0f}-{100 * hi:.0f}%)" if n else f"  {label:32}n/a")

    if results:
        print("\nChampion semantic pass by stratum:")
        stratum("all", rows, "champion_semantic_pass")
        stratum("held-out (LOW)", [r for r in rows if r["tier"] == "LOW"], "champion_semantic_pass")
        stratum("seen pattern (MEDIUM+HIGH)", [r for r in rows if r["tier"] != "LOW"], "champion_semantic_pass")
        print("Schema precision, reported (substring) vs exact table match:")
        stratum("reported", rows, "schema_pass_reported")
        stratum("exact", rows, "schema_pass_exact")

    if a.baseline and Path(a.baseline).exists():
        base = {r["id"]: r for r in json.load(open(a.baseline, encoding="utf-8"))}
        print("\nBaseline vs champion (semantic pass), paired by question:")
        for label, sel in (("all", rows), ("held-out (LOW)", [r for r in rows if r["tier"] == "LOW"]),
                           ("seen pattern (MEDIUM+HIGH)", [r for r in rows if r["tier"] != "LOW"])):
            sel = [r for r in sel if r["id"] in base and r["champion_semantic_pass"] is not None]
            ch = sum(1 for r in sel if r["champion_semantic_pass"])
            bs = sum(1 for r in sel if base[r["id"]]["semantic_logic_pass"])
            b = sum(1 for r in sel if r["champion_semantic_pass"] and not base[r["id"]]["semantic_logic_pass"])
            c = sum(1 for r in sel if not r["champion_semantic_pass"] and base[r["id"]]["semantic_logic_pass"])
            print(f"  {label:32}champion {ch}/{len(sel)}  baseline {bs}/{len(sel)}  champion-only wins={b} baseline-only wins={c}  McNemar p={mcnemar_exact(b, c):.3f}")
        missed = [r["id"] for r in rows if r["id"] in base and not base[r["id"]]["semantic_logic_pass"]]
        print("  baseline misses:", missed)
    print(f"\nWrote {out / 'leakage_report.csv'} and {out / 'eval_split.json'}")


if __name__ == "__main__":
    main()
