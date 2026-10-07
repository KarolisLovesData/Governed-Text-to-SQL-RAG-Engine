import json
import time
import os
from google import genai
from google.cloud import bigquery

# Import functions and client from the text_to_sql_engine module
from text_to_sql_engine import (
    generate_governed_sql,
    validate_sql_dry_run,
    bq_client
)


def llm_as_a_judge(question: str, golden_sql: str, generated_sql: str) -> bool:
    """Uses Gemini to evaluate if the generated SQL is semantically correct."""
    api_key = os.getenv("GEMINI_API_KEY")
    if not api_key:
        print("   ⚠️ Judge AI failed: GEMINI_API_KEY not found in environment.")
        return False

    client = genai.Client(api_key=api_key)

    eval_prompt = f"""
    You are a strict Senior Data Engineer evaluating Text-to-SQL outputs.

    USER QUESTION: "{question}"

    GROUND TRUTH SQL (Baseline):
    ```sql
    {golden_sql}
    ```

    AI GENERATED SQL:
    ```sql
    {generated_sql}
    ```

    INSTRUCTIONS:
    Evaluate if the AI GENERATED SQL correctly answers the USER QUESTION and aligns with the core intent of the GROUND TRUTH SQL.

    Pass Criteria:
    - It retrieves the core requested metrics and dimensions.
    - It is acceptable (and encouraged) if the AI added helpful derived columns (e.g., percentages, growth rates) not explicitly in the ground truth.
    - It is acceptable if the AI uses different column aliases or table aliases.
    - It is acceptable if the AI uses a different structure (CTEs vs subqueries) as long as the logic holds.

    Respond strictly with a single word: "PASS" if it meets the criteria, or "FAIL" if it hallucinates, misses core logic, or answers the wrong question.
    """

    try:
        response = client.models.generate_content(
            model="gemini-3.7-flash",
            contents=eval_prompt
        )
        verdict = response.text.strip().upper()
        return "PASS" in verdict
    except Exception as e:
        print(f"   ⚠️ Judge AI failed to evaluate: {e}")
        return False


def run_evaluation_suite(eval_file="eval_queries.json", output_file="eval_results.json"):
    """Runs automated benchmark testing and exports structured results to a JSON file."""
    try:
        with open(eval_file, "r", encoding="utf-8") as f:
            eval_cases = json.load(f)
    except FileNotFoundError:
        print(f"Error: {eval_file} not found. Please ensure the file exists.")
        return

    total_tests = len(eval_cases)
    passed_dry_run = 0
    correct_tables = 0
    semantic_matches = 0
    latencies = []

    detailed_results = []

    print(f"🧪 Starting Evaluation Suite across {total_tests} test cases...\n")

    for case in eval_cases:
        test_id = case["id"]
        question = case["question"]
        expected_tables = case["expected_tables"]
        golden_sql = case["golden_sql"]

        print(f"🔹 Processing [{test_id}]: '{question[:60]}...'")

        start_time = time.time()
        gen_sql = ""
        gen_error = None

        # 1. Generate SQL via RAG engine
        try:
            gen_sql = generate_governed_sql(question)
            latency = time.time() - start_time
            latencies.append(latency)
        except Exception as e:
            gen_error = str(e)
            print(f"   ❌ Engine Generation Error: {e}\n")
            detailed_results.append({
                "id": test_id,
                "question": question,
                "expected_tables": expected_tables,
                "golden_sql": golden_sql,
                "generated_sql": None,
                "latency_seconds": None,
                "dry_run_pass": False,
                "dry_run_error": gen_error,
                "schema_precision_pass": False,
                "semantic_logic_pass": False
            })
            continue

        # 2. Metric A: Dry-Run Syntax Pass
        is_valid, dry_run_err, _ = validate_sql_dry_run(gen_sql)
        if is_valid:
            passed_dry_run += 1
            print("   ✅ Dry-Run Syntax: PASSED")
        else:
            print(f"   ❌ Dry-Run Syntax: FAILED ({str(dry_run_err)[:60]}...)")

        # 3. Metric B: Schema Precision (Table Join Check)
        tables_found = all(tbl.lower() in gen_sql.lower() for tbl in expected_tables)
        if tables_found:
            correct_tables += 1
            print("   ✅ Schema Precision: PASSED")
        else:
            print(f"   ❌ Schema Precision: FAILED (Expected: {expected_tables})")

        # 4. Metric C: Semantic Logic Match (LLM-as-a-Judge)
        is_semantic_match = False
        if is_valid:
            is_semantic_match = llm_as_a_judge(question, golden_sql, gen_sql)

            if is_semantic_match:
                semantic_matches += 1
                print("   ✅ Semantic Logic Match: PASSED (LLM Judge)")
            else:
                print("   ⚠️ Semantic Logic Match: MISMATCH (LLM Judge flagged logic error)")
        else:
            print("   ⚠️ Semantic Logic Match: SKIPPED (Query failed dry-run)")

        # Record test case details for JSON export
        detailed_results.append({
            "id": test_id,
            "question": question,
            "expected_tables": expected_tables,
            "golden_sql": golden_sql,
            "generated_sql": gen_sql,
            "latency_seconds": round(latency, 2),
            "dry_run_pass": is_valid,
            "dry_run_error": dry_run_err if not is_valid else None,
            "schema_precision_pass": tables_found,
            "semantic_logic_pass": is_semantic_match
        })

        print("*" * 50)

    avg_latency = round(sum(latencies) / len(latencies), 2) if latencies else 0.0
    dry_run_pct = round((passed_dry_run / total_tests) * 100, 1) if total_tests else 0.0
    schema_precision_pct = round((correct_tables / total_tests) * 100, 1) if total_tests else 0.0
    semantic_match_pct = round((semantic_matches / total_tests) * 100, 1) if total_tests else 0.0

    # Compile complete output structure
    output_data = {
        "summary": {
            "total_test_cases": total_tests,
            "dry_run_syntax_accuracy_pct": dry_run_pct,
            "schema_precision_pct": schema_precision_pct,
            "semantic_logic_match_pct": semantic_match_pct,
            "avg_latency_seconds": avg_latency
        },
        "results": detailed_results
    }

    # Save to JSON file
    with open(output_file, "w", encoding="utf-8") as f:
        json.dump(output_data, f, indent=4)

    print("\n" + "*" * 55)
    print("📊 EVALUATION RESULTS BENCHMARK SUMMARY")
    print("*" * 55)
    print(f"Total Test Cases Processed: {total_tests}")
    print(f"Dry-Run Syntax Accuracy:    {dry_run_pct}%")
    print(f"Schema Precision (Tables):  {schema_precision_pct}%")
    print(f"Semantic Logic Match (LLM): {semantic_match_pct}%")
    print(f"Avg Generation Latency:     {avg_latency}s")
    print("*" * 55)
    print(f"💾 Evaluation results successfully saved to '{output_file}'\n")


if __name__ == "__main__":
    run_evaluation_suite()