"""
eval_common.py - code shared by 3_run_evals.py (governed engine) and baseline_evals.py (schema-only baseline).

Why it exists: both systems must be measured by exactly the same code (same judge, same table matching,
same summary maths), otherwise a difference between them could come from the measuring, not from the system.
"""
import argparse
import concurrent.futures
import json
import math
import subprocess
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

import judge

SRC_DIR = Path(__file__).resolve().parent
DATA_DIR = SRC_DIR.parent / "data"          # inputs: questions, examples, schema
RESULTS_DIR = SRC_DIR.parent / "results"    # outputs: run results, leakage report, judge cache


# ------------------------------------------------------------------ CLI / inputs
def parse_args(description, default_out):
    p = argparse.ArgumentParser(description=description)
    p.add_argument("--eval-file", default=str(DATA_DIR / "eval_queries.json"), help="benchmark questions (JSON)")
    p.add_argument("--out", default=str(default_out), help="where to write the results JSON")
    p.add_argument("--limit", type=int, default=None, help="only run the first N questions (cheap dry run)")
    p.add_argument("--ids", default=None, help="only run these question ids, comma-separated (e.g. eval_07,eval_17)")
    p.add_argument("--judge-model", default=judge.DEFAULT_JUDGE_MODEL, help="Claude model used as judge")
    return p.parse_args()


def load_cases(eval_file, ids=None, limit=None):
    cases = json.load(open(eval_file, encoding="utf-8"))
    if ids:
        wanted = [i.strip() for i in ids.split(",") if i.strip()]
        unknown = set(wanted) - {c["id"] for c in cases}
        if unknown:
            raise SystemExit(f"Unknown question ids: {sorted(unknown)}")
        cases = [c for c in cases if c["id"] in wanted]
    if limit:
        cases = cases[:limit]
    return cases


def preflight(judge_model):
    """Fail BEFORE spending anything if the Claude key is missing."""
    judge._get_client()
    print(f"Judge: {judge_model} | prompt {judge.PROMPT_VERSION} | call limit {judge.MAX_CALLS}\n")


def call_with_timeout(fn, seconds, *args, **kwargs):
    """Run fn(*args) but give up after `seconds`, so one stuck network call cannot freeze the whole benchmark."""
    ex = concurrent.futures.ThreadPoolExecutor(max_workers=1)
    fut = ex.submit(fn, *args, **kwargs)
    try:
        return fut.result(timeout=seconds)
    except concurrent.futures.TimeoutError:
        raise TimeoutError(f"no answer after {seconds}s")
    finally:
        ex.shutdown(wait=False)


GENERATION_TIMEOUT_S = 420   # Gemini can take ~2 min on a hard question (seen: 116s); governed engine may also retry


# ------------------------------------------------------------------- grading
def grade_case(case, gen_sql, is_valid, judge_model):
    """Schema precision (exact table names) and semantic verdict, identical for both systems."""
    schema_ok = bool(gen_sql) and judge.exact_table_match(case["expected_tables"], gen_sql)
    if not gen_sql:
        verdict = {"verdict": "FAIL", "reason": "No SQL was generated.", "failure_type": "no_sql"}
    elif not is_valid:
        verdict = {"verdict": "SKIPPED", "reason": "Query failed the BigQuery dry-run, so it was not sent to the judge.",
                   "failure_type": "invalid_sql"}
    else:
        print("   Judging...", flush=True)
        verdict = judge.judge_sql(case["question"], case["golden_sql"], gen_sql, model=judge_model)
    v = verdict["verdict"]
    return {
        "schema_precision_pass": schema_ok,
        "semantic_logic_pass": True if v == "PASS" else (None if v == "ERROR" else False),  # None = judge error, excluded
        "judge_verdict": v,
        "judge_reason": verdict.get("reason", ""),
        "failure_type": verdict.get("failure_type"),
        "judge_model": judge_model,
    }


# ------------------------------------------------------------------- summary
def wilson(k, n, z=1.96):
    if not n:
        return (0.0, 0.0)
    p, d = k / n, 1 + z * z / n
    c = p + z * z / (2 * n)
    h = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n))
    return ((c - h) / d, (c + h) / d)


def code_version():
    """Git commit of the code that produced a run, so results from different code versions are never mixed."""
    try:
        git = lambda *a: subprocess.run(["git", *a], cwd=SRC_DIR, capture_output=True, text=True, check=True).stdout.strip()
        commit = git("rev-parse", "--short", "HEAD")
        return commit + ("-dirty" if git("status", "--porcelain", "--", str(SRC_DIR), str(DATA_DIR)) else "")
    except (OSError, subprocess.CalledProcessError):
        return None


def summarize(system, results, judge_model, extra=None):
    n = len(results)
    pct = lambda k, d: round(100 * k / d, 1) if d else None
    evaluable = [r for r in results if r["semantic_logic_pass"] is not None]
    passed = sum(1 for r in evaluable if r["semantic_logic_pass"])
    lo, hi = wilson(passed, len(evaluable))
    lats = [r["latency_seconds"] for r in results if r.get("latency_seconds") is not None]
    costs = [r["cost_usd"] for r in results if r.get("cost_usd") is not None]
    summary = {
        "system": system,
        "run_at_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "code_commit": code_version(),
        "judge_model": judge_model,
        "judge_prompt_version": judge.PROMPT_VERSION,
        "total_test_cases": n,
        "dry_run_syntax_accuracy_pct": pct(sum(1 for r in results if r["dry_run_pass"]), n),
        "schema_precision_pct": pct(sum(1 for r in results if r["schema_precision_pass"]), n),
        "semantic_logic_match_pct": pct(passed, len(evaluable)),
        "semantic_pass": passed,
        "semantic_evaluated": len(evaluable),
        "semantic_wilson95_pct": [round(100 * lo, 1), round(100 * hi, 1)],
        "judge_errors": n - len(evaluable),
        "failure_types": dict(Counter(r["failure_type"] for r in results if r["semantic_logic_pass"] is False)),
        "avg_latency_seconds": round(sum(lats) / len(lats), 2) if lats else None,
        "max_latency_seconds": max(lats) if lats else None,
        "avg_cost_usd": round(sum(costs) / len(costs), 5) if costs else None,
        "total_cost_usd": round(sum(costs), 4) if costs else None,
        "judge_usage": judge.usage_summary(),
    }
    if extra:
        summary.update(extra)
    return summary


def print_summary(summary):
    s = summary
    print("\n" + "*" * 58)
    print(f"RESULTS: {s['system']}   (judge: {s['judge_model']})")
    print("*" * 58)
    print(f"Questions run:              {s['total_test_cases']}")
    print(f"Dry-run validity:           {s['dry_run_syntax_accuracy_pct']}%")
    print(f"Schema precision (exact):   {s['schema_precision_pct']}%")
    print(f"Semantic logic match:       {s['semantic_logic_match_pct']}%  ({s['semantic_pass']}/{s['semantic_evaluated']}, "
          f"95% CI {s['semantic_wilson95_pct'][0]}-{s['semantic_wilson95_pct'][1]}%)")
    print(f"Failure categories:         {s['failure_types'] or 'none'}")
    print(f"Avg generation latency:     {s['avg_latency_seconds']}s  (slowest {s['max_latency_seconds']}s)")
    if s["avg_cost_usd"] is not None:
        print(f"Cost per answer:            ${s['avg_cost_usd']:.4f}  (whole run ${s['total_cost_usd']:.2f}, judge not included)")
    if s["judge_errors"]:
        print(f"WARNING: {s['judge_errors']} judge ERROR(s) excluded from the semantic score. Re-run those ids with --ids.")
    u = s["judge_usage"]
    print(f"Judge usage:                {u['calls']} calls, {u['cache_hits']} cache hits, "
          f"{u['input_tokens']} in / {u['output_tokens']} out tokens")
    print("*" * 58)


def write_results(path, summary, results, quiet=False):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"summary": summary, "results": results}, indent=2), encoding="utf-8")
    if not quiet:
        print(f"Saved results to {path}\n")
