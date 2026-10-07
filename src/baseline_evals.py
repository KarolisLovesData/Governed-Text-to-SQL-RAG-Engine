import json
import time
import os
import re

from dotenv import load_dotenv
from google import genai
from google.cloud import bigquery
from google.cloud.exceptions import GoogleCloudError
import pandas as pd

# Re-use the BigQuery client and LLM Judge from your existing setup
bq_client = bigquery.Client(project="apex-activewear", location="US")
load_dotenv()


def llm_as_a_judge(question: str, golden_sql: str, generated_sql: str) -> bool:
    """Uses Gemini to evaluate if the generated SQL is semantically correct."""
    api_key = os.getenv("GEMINI_API_KEY")
    client = genai.Client(api_key=api_key)

    eval_prompt = f"""
    You are a strict Senior Data Engineer evaluating Text-to-SQL outputs.
    USER QUESTION: "{question}"
    GROUND TRUTH SQL (Baseline): ```sql {golden_sql} ```
    AI GENERATED SQL: ```sql {generated_sql} ```

    Evaluate if the AI GENERATED SQL correctly answers the USER QUESTION. 
    Respond strictly with a single word: "PASS" or "FAIL".
    """
    try:
        response = client.models.generate_content(model="gemini-3.7-flash", contents=eval_prompt)
        return "PASS" in response.text.strip().upper()
    except Exception:
        return False


def naive_generate_sql(question: str) -> str:
    """BASELINE APPROACH: Schema-only prompting with NO Dataform rules, NO RAG, and NO dry-runs."""
    api_key = os.getenv("GEMINI_API_KEY")
    client = genai.Client(api_key=api_key)

    # Read the schema and convert the ENTIRE dataframe to a raw CSV string
    schemas_df = pd.read_csv("Apex Table Schemas.csv")
    schemas_string = schemas_df.to_csv(index=False)

    prompt = f"""
    Write BigQuery Standard SQL to answer this business question for APEX Activewear.

    DATABASE SCHEMAS:
    {schemas_string}

    QUESTION: {question}

    Output ONLY raw executable SQL inside standard ```sql ``` markdown blocks. Do not explain your logic.
    """

    response = client.models.generate_content(model="gemini-3.7-flash", contents=prompt)

    # Extract the SQL
    sql_match = re.search(r"```(?:sql)?\s*(.*?)\s*```", response.text, re.DOTALL | re.IGNORECASE)
    if sql_match:
        return sql_match.group(1).strip()
    return response.text.strip()


def run_baseline_suite(eval_file="eval_queries.json"):
    with open(eval_file, "r", encoding="utf-8") as f:
        eval_cases = json.load(f)

    total_tests = len(eval_cases)
    passed_dry_run = 0
    correct_tables = 0
    semantic_matches = 0
    latencies = []

    # 🆕 Initialize the results log
    results_log = []

    print(f"⚠️ Starting BASELINE Evaluation (No RAG, No Governance) across {total_tests} cases...\n")

    for case in eval_cases:
        test_id = case["id"]
        question = case["question"]
        expected_tables = case["expected_tables"]
        golden_sql = case["golden_sql"]

        print(f"🔹 Processing [{test_id}]: {question[:60]}...")
        start_time = time.time()

        # 1. Generate NAIVE SQL (Zero-Shot)
        gen_sql = naive_generate_sql(question)
        latency = time.time() - start_time
        latencies.append(latency)

        print("\n[GOLDEN SQL]")
        print(golden_sql)
        print("\n[GENERATED BASELINE SQL]")
        print(gen_sql)
        print("\n" + "-" * 40)

        # 2. Dry-Run Check
        is_valid = False
        try:
            job_config = bigquery.QueryJobConfig(dry_run=True)
            bq_client.query(gen_sql, job_config=job_config)
            is_valid = True
            passed_dry_run += 1
            print("   ✅ Dry-Run Syntax: PASSED")
        except GoogleCloudError as e:
            print(f"   ❌ Dry-Run Syntax: FAILED (Hallucination or Syntax Error)")

        # 3. Schema Precision Check
        tables_found = all(tbl.lower() in gen_sql.lower() for tbl in expected_tables)
        if tables_found:
            correct_tables += 1
            print("   ✅ Schema Precision: PASSED")
        else:
            print(f"   ❌ Schema Precision: FAILED")

        # 4. Semantic Match (LLM Judge)
        is_semantic_match = False
        if is_valid:
            is_semantic_match = llm_as_a_judge(question, golden_sql, gen_sql)
            if is_semantic_match:
                semantic_matches += 1
                print("   ✅ Semantic Logic: PASSED")
            else:
                print("   ⚠️ Semantic Logic: FAILED")
        else:
            print("   ⚠️ Semantic Logic: SKIPPED (Crashed on Dry-Run)")

        print("=" * 60 + "\n")

        # 🆕 Append the specific results of this test case to the log
        results_log.append({
            "id": test_id,
            "dry_run_pass": is_valid,
            "schema_precision_pass": tables_found,
            "semantic_logic_pass": is_semantic_match,
            "latency_seconds": round(latency, 2),
            "generated_sql": gen_sql
        })

    # 🆕 Export the results log to a JSON file
    export_filename = "baseline_eval_results.json"
    with open(export_filename, "w", encoding="utf-8") as f:
        json.dump(results_log, f, indent=4)

    print(f"💾 Results successfully exported to {export_filename}")

    print("\n🚨 BASELINE (NAIVE LLM) RESULTS 🚨")
    print(f"Dry-Run Syntax Accuracy:    {(passed_dry_run / total_tests) * 100:.1f}%")
    print(f"Schema Precision (Tables):  {(correct_tables / total_tests) * 100:.1f}%")
    print(f"Semantic Logic Match (LLM): {(semantic_matches / total_tests) * 100:.1f}%")
    print(f"Avg Generation Latency:     {sum(latencies) / len(latencies):.2f}s")


if __name__ == "__main__":
    run_baseline_suite()