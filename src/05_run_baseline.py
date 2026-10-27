"""
05_run_baseline.py - schema-only BASELINE: no retrieval, no governance rules, no dry-run self-healing.

Usage (from the src folder):
    python 05_run_baseline.py --limit 5
    python 05_run_baseline.py
    python 05_run_baseline.py --ids eval_07,eval_17

Uses the same generation model setting (LLM_MODEL), the same dry-run check and the same Claude judge as the
governed engine, so the only difference between the two systems is the governance layer itself.
"""
import re
import time

import pandas as pd

import text_to_sql_engine as engine
from text_to_sql_engine import LLM_MODEL, ai_client, validate_sql_dry_run
import eval_common as ec


def naive_generate_sql(question: str) -> str:
    """BASELINE APPROACH: Schema-only prompting with NO Dataform rules, NO RAG, and NO dry-runs."""
    # Read the schema and convert the ENTIRE dataframe to a raw CSV string
    schemas_df = pd.read_csv(ec.DATA_DIR / "Apex Table Schemas.csv")
    schemas_string = schemas_df.to_csv(index=False)

    prompt = f"""
    Write BigQuery Standard SQL to answer this business question for APEX Activewear.

    DATABASE SCHEMAS:
    {schemas_string}

    QUESTION: {question}

    Output ONLY raw executable SQL inside standard ```sql ``` markdown blocks. Do not explain your logic.
    """

    response = ai_client.models.generate_content(model=LLM_MODEL, contents=prompt)
    engine._count_gemini(response)
    text = response.text or ""

    # Extract the SQL
    sql_match = re.search(r"```(?:sql)?\s*(.*?)\s*```", text, re.DOTALL | re.IGNORECASE)
    if sql_match:
        return sql_match.group(1).strip()
    return text.strip()


def run_baseline_suite(args):
    cases = ec.load_cases(args.eval_file, args.ids, args.limit)
    ec.preflight(args.judge_model)
    print(f"Starting BASELINE evaluation (no RAG, no governance) on {len(cases)} questions | generator: {LLM_MODEL}\n")

    results = []
    for case in cases:
        print(f"[{case['id']}] {case['question'][:70]}...")

        engine.reset_usage()
        gen_sql, gen_error, latency = None, None, None
        start = time.time()
        try:
            print("   Asking Gemini...", flush=True)
            gen_sql = ec.call_with_timeout(naive_generate_sql, ec.GENERATION_TIMEOUT_S, case["question"])
            latency = round(time.time() - start, 2)
        except Exception as e:
            gen_error = str(e)
            print(f"   Generation error: {e}")

        is_valid, dry_err, answer_bytes = False, gen_error, 0
        if gen_sql:
            try:
                is_valid, dry_err, answer_bytes = validate_sql_dry_run(gen_sql)
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
            **grade,
        })
        ec.write_results(args.out, {"system": "Baseline (schema-only)", "partial": True, "done": len(results), "of": len(cases)}, results, quiet=True)  # checkpoint

    summary = ec.summarize("Baseline (schema-only)", results, args.judge_model, extra={"generator_model": LLM_MODEL})
    ec.print_summary(summary)
    ec.write_results(args.out, summary, results)


if __name__ == "__main__":
    run_baseline_suite(ec.parse_args("Evaluate the schema-only baseline.",
                                     ec.RESULTS_DIR / "baseline_results_claude_judge.json"))
