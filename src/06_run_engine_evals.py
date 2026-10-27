"""
06_run_engine_evals.py - benchmark the governed RAG engine.

Usage (from the src folder):
    python 06_run_engine_evals.py --limit 5                 # cheap first check: only 5 questions
    python 06_run_engine_evals.py                           # full benchmark
    python 06_run_engine_evals.py --ids eval_07,eval_17     # re-run specific questions
    python 06_run_engine_evals.py --judge-model claude-opus-5-5 --out ../results/eval_results_opus.json

The semantic verdict comes from the shared Claude judge in judge.py (same judge and prompt as 05_run_baseline.py).
"""
import time

import text_to_sql_engine as engine
import eval_common as ec

_escalations = []


def _auto_hitl(user_query, generated_sql, scanned_mb, confidence_score, escalation_reasons):
    """Non-interactive stand-in for the engine's human-approval prompt.
    An automated run must not wait for keyboard input, so the SQL is approved for grading and the
    escalation is recorded in the results (useful for judging how well the escalation rules work)."""
    _escalations.append({"scanned_mb": round(scanned_mb, 2), "confidence": confidence_score,
                         "reasons": list(escalation_reasons)})
    print(f"   Escalation (auto-approved for evaluation): {escalation_reasons}")
    return "APPROVE", None


engine.trigger_hitl_escalation = _auto_hitl  # the engine looks this name up at call time


def run_evaluation_suite(args):
    cases = ec.load_cases(args.eval_file, args.ids, args.limit)
    ec.preflight(args.judge_model)
    print(f"Starting governed-engine evaluation on {len(cases)} questions...\n")

    results = []
    for case in cases:
        _escalations.clear()
        engine.reset_usage()
        print(f"[{case['id']}] {case['question'][:70]}...")

        gen_sql, gen_error, latency = None, None, None
        start = time.time()
        try:
            gen_sql = ec.call_with_timeout(engine.generate_governed_sql, ec.GENERATION_TIMEOUT_S, case["question"])
            latency = round(time.time() - start, 2)
        except Exception as e:
            gen_error = str(e)
            print(f"   Engine error: {e}")

        is_valid, dry_err, answer_bytes = False, gen_error, 0
        if gen_sql:
            try:
                is_valid, dry_err, answer_bytes = engine.validate_sql_dry_run(gen_sql)
            except Exception as e:
                is_valid, dry_err = False, str(e)
        usage = dict(engine.USAGE)
        usage["bigquery_bytes"] += answer_bytes or 0  # running the final SQL once to get the answer
        print(f"   Dry-run: {'PASSED' if is_valid else 'FAILED'}")

        grade = ec.grade_case(case, gen_sql, is_valid, args.judge_model)
        print(f"   Schema precision: {'PASSED' if grade['schema_precision_pass'] else 'FAILED'} | "
              f"Judge: {grade['judge_verdict']} - {grade['judge_reason']}")

        results.append({
            "id": case["id"],
            "question": case["question"],
            "expected_tables": case["expected_tables"],
            "golden_sql": case["golden_sql"],
            "generated_sql": gen_sql,
            "latency_seconds": latency,
            "usage": usage,
            "cost_usd": round(engine.usage_cost_usd(usage), 6),
            "dry_run_pass": is_valid,
            "dry_run_error": None if is_valid else dry_err,
            "escalated": bool(_escalations),
            "escalation_details": list(_escalations),
            **grade,
        })
        ec.write_results(args.out, {"system": "Governed RAG engine", "partial": True, "done": len(results), "of": len(cases)}, results, quiet=True)  # checkpoint

    summary = ec.summarize("Governed RAG engine", results, args.judge_model,
                           extra={"escalated_questions": sum(1 for r in results if r["escalated"])})
    ec.print_summary(summary)
    ec.write_results(args.out, summary, results)


if __name__ == "__main__":
    run_evaluation_suite(ec.parse_args("Evaluate the governed RAG engine.",
                                       ec.RESULTS_DIR / "eval_results_claude_judge.json"))
