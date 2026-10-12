"""
07_audit_judge.py - re-judge a sample of verdicts with a stronger model (Opus) and measure agreement.

Why: the benchmark is only as trustworthy as its judge. If a stronger, independent judge mostly agrees with the
Sonnet verdicts, the headline numbers are credible; where they disagree, those verdicts need a human look.

Sample = every FAIL and every question where engine and baseline differ (the verdicts that decide the result),
plus a random handful of PASSes. Uses the first run of each system and set.

Usage (from src):   python 07_audit_judge.py              # default model claude-opus-5-5, max 40 verdicts
                    python 07_audit_judge.py --max 30 --model claude-opus-5-5
"""
import argparse
import json
import random

import eval_common as ec
import judge

RUNS = {  # (set, system): first-run result file
    ("A", "engine"): "eval_results_claude_judge.json", ("A", "baseline"): "baseline_results_claude_judge.json",
    ("B", "engine"): "set_b_engine.json", ("B", "baseline"): "set_b_baseline.json",
}


def kappa(pairs):
    n = len(pairs)
    po = sum(a == b for a, b in pairs) / n
    pa = sum(a for a, _ in pairs) / n
    pb = sum(b for _, b in pairs) / n
    pe = pa * pb + (1 - pa) * (1 - pb)
    return (po - pe) / (1 - pe) if pe < 1 else 1.0


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--model", default="claude-opus-5-5")
    ap.add_argument("--max", type=int, default=40)
    ap.add_argument("--seed", type=int, default=7)
    ap.add_argument("--out", default=str(ec.RESULTS_DIR / "judge_audit_opus.json"))
    a = ap.parse_args()
    ec.preflight(a.model)

    rows = {}
    for (s, sysname), f in RUNS.items():
        for r in json.load(open(ec.RESULTS_DIR / f, encoding="utf-8"))["results"]:
            rows[(s, sysname, r["id"])] = r
    pool_fail, pool_diff, pool_pass = [], [], []
    for (s, sysname, qid), r in rows.items():
        if r["semantic_logic_pass"] is None or not r["generated_sql"]:
            continue
        other = rows.get((s, "baseline" if sysname == "engine" else "engine", qid))
        differs = other is not None and other["semantic_logic_pass"] != r["semantic_logic_pass"]
        (pool_fail if r["semantic_logic_pass"] is False else pool_diff if differs else pool_pass).append((s, sysname, qid))
    random.Random(a.seed).shuffle(pool_pass)
    chosen = (pool_fail + pool_diff)[: a.max]
    chosen += pool_pass[: max(0, min(10, a.max - len(chosen)))]
    print(f"Auditing {len(chosen)} verdicts ({len(pool_fail)} FAIL, {len(pool_diff)} differing PASS, rest random PASS) with {a.model}\n")

    out, pairs = [], []
    for s, sysname, qid in chosen:
        r = rows[(s, sysname, qid)]
        v = judge.judge_sql(r["question"], r["golden_sql"], r["generated_sql"], model=a.model)
        if v["verdict"] == "ERROR":
            print(f"  {s} {sysname:8} {qid:18} ERROR {v['reason'][:80]}")
            continue
        sonnet, opus = r["semantic_logic_pass"], v["verdict"] == "PASS"
        pairs.append((sonnet, opus))
        tag = "agree   " if sonnet == opus else "DISAGREE"
        print(f"  {s} {sysname:8} {qid:18} sonnet={'PASS' if sonnet else 'FAIL'} opus={v['verdict']}  {tag}")
        out.append({"set": s, "system": sysname, "id": qid, "sonnet_pass": sonnet, "opus_verdict": v["verdict"],
                    "opus_reason": v["reason"], "sonnet_reason": r["judge_reason"], "opus_failure_type": v.get("failure_type"),
                    "agree": sonnet == opus})
    n = len(pairs)
    agree = sum(a_ == b_ for a_, b_ in pairs)
    summ = {"audit_model": a.model, "audited": n, "agree": agree, "agreement_pct": round(100 * agree / n, 1) if n else None,
            "cohen_kappa": round(kappa(pairs), 2) if n and len({p[0] for p in pairs}) > 1 and len({p[1] for p in pairs}) > 1 else None,
            "disagreements": [o["id"] + " (" + o["set"] + "/" + o["system"] + ")" for o in out if not o["agree"]],
            "judge_usage": judge.usage_summary()}
    ec.write_results(a.out, summ, out)
    print("\nAgreement Sonnet vs", a.model, ":", f"{agree}/{n} = {summ['agreement_pct']}%", "| kappa:", summ["cohen_kappa"])
    print("Disagreements:", summ["disagreements"] or "none")
    print("Usage:", summ["judge_usage"])


if __name__ == "__main__":
    main()
