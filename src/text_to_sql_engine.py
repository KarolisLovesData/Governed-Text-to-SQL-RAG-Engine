"""
APEX Activewear - Governed Text-to-SQL RAG Engine with HITL Escalation

1. Generates query embeddings using gemini-embedding-001.
2. Performs Hybrid Search in BigQuery (Dense VECTOR_SEARCH + Filtered Keyword SEARCH).
3. Merges context chunks via Reciprocal Rank Fusion (RRF).
4. Generates standard BigQuery SQL using Gemini 3.7 Flash.
5. Executes $0 BigQuery Dry-Run validation + LLM Confidence Scoring.
6. Enforces Human-in-the-Loop (HITL) escalation on cost (>500 MB) or confidence (<0.85) triggers.
"""

import os
import re
import sys
import time
import threading
import itertools
from typing import Optional, Tuple

from google import genai
from google.cloud import bigquery
from google.cloud.exceptions import GoogleCloudError
from dotenv import load_dotenv
import warnings
warnings.filterwarnings("ignore", category=UserWarning, module="google.cloud.bigquery")
# =====================================================================
# 1. GOVERNANCE & HITL CONFIGURATION THRESHOLDS
# =====================================================================
MAX_COST_MB: float = 500.0  # Maximum allowed BigQuery dry-run scan (MB)
MIN_CONFIDENCE_SCORE: float = 0.85  # Minimum acceptable LLM confidence score (0.0 to 1.0)
MAX_RETRIES: int = 3  # Maximum self-healing / feedback loop iterations

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
ENV_PATH = os.path.join(BASE_DIR, ".env")
load_dotenv(dotenv_path=ENV_PATH)

PROJECT_ID = "apex-activewear"
DATASET_ID = "gold_layer"
LOCATION = "US"

INDEX_TABLE = f"`{PROJECT_ID}.{DATASET_ID}.ai_governance_index`"
EMBEDDING_MODEL = "gemini-embedding-001"
LLM_MODEL = "gemini-3.7-flash"

api_key = os.getenv("GEMINI_API_KEY")
if not api_key:
    raise ValueError(f"GEMINI_API_KEY not found in environment or {ENV_PATH}")

bq_client = bigquery.Client(project=PROJECT_ID, location=LOCATION)
ai_client = genai.Client(api_key=api_key)

STOP_WORDS = {
    "what", "is", "the", "are", "by", "for", "across", "compare", "show",
    "return", "get", "rank", "list", "and", "or", "in", "of", "to", "with",
    "whole", "dataset", "total", "average", "each", "all"
}


class TerminalSpinner:
    """Standard library CLI loading spinner using threading."""

    def __init__(self, message="Processing..."):
        self.message = message
        self.spinner = itertools.cycle(['⠋', '⠙', '⠹', '⠸', '⠼', '⠴', '⠦', '⠧', '⠇', '⠏'])
        self.running = False
        self.thread = None

    def spin(self):
        while self.running:
            sys.stdout.write(f"\r{next(self.spinner)}  {self.message}")
            sys.stdout.flush()
            time.sleep(0.08)
        sys.stdout.write(f"\r{' ' * (len(self.message) + 10)}\r")
        sys.stdout.flush()

    def __enter__(self):
        self.running = True
        self.thread = threading.Thread(target=self.spin)
        self.thread.start()
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.running = False
        if self.thread:
            self.thread.join()


def get_query_embedding(text: str):
    """Generates a dense vector representation using the active embedding model."""
    try:
        response = ai_client.models.embed_content(
            model=EMBEDDING_MODEL,
            contents=text
        )
        return response.embeddings[0].values
    except Exception:
        response = ai_client.models.embed_content(
            model=f"models/{EMBEDDING_MODEL}",
            contents=text
        )
        return response.embeddings[0].values


def retrieve_governed_context(user_query: str, top_k: int = 12) -> str:
    """Executes BigQuery Hybrid Search using VECTOR_SEARCH and Lexical SEARCH."""
    query_vector = get_query_embedding(user_query)

    dense_sql = f"""
    SELECT base.id, base.content_chunk, distance
    FROM VECTOR_SEARCH(
      TABLE {INDEX_TABLE},
      'embedding',
      (SELECT @query_vec AS embedding),
      top_k => {top_k}
    )
    """
    job_config_dense = bigquery.QueryJobConfig(
        query_parameters=[
            bigquery.ArrayQueryParameter("query_vec", "FLOAT64", query_vector)
        ]
    )
    dense_results = bq_client.query(dense_sql, job_config=job_config_dense).to_dataframe()

    words = re.findall(r'\w+', user_query.lower())
    domain_keywords = [w for w in words if w not in STOP_WORDS and len(w) > 1]
    search_query_str = " ".join(domain_keywords) if domain_keywords else user_query

    sparse_sql = f"""
    SELECT id, content_chunk, 0.0 AS distance
    FROM {INDEX_TABLE}
    WHERE SEARCH(content_chunk, @search_tokens)
    LIMIT {top_k}
    """
    job_config_sparse = bigquery.QueryJobConfig(
        query_parameters=[
            bigquery.ScalarQueryParameter("search_tokens", "STRING", search_query_str)
        ]
    )

    try:
        sparse_results = bq_client.query(sparse_sql, job_config=job_config_sparse).to_dataframe()
    except Exception:
        sparse_results = dense_results.iloc[0:0]

    rrf_scores = {}
    content_map = {}
    k_constant = 60

    for rank, row in dense_results.iterrows():
        doc_id = row['id']
        content_map[doc_id] = row['content_chunk']
        rrf_scores[doc_id] = rrf_scores.get(doc_id, 0.0) + (1.0 / (k_constant + rank + 1))

    for rank, row in sparse_results.iterrows():
        doc_id = row['id']
        content_map[doc_id] = row['content_chunk']
        rrf_scores[doc_id] = rrf_scores.get(doc_id, 0.0) + (1.0 / (k_constant + rank + 1))

    sorted_docs = sorted(rrf_scores.items(), key=lambda x: x[1], reverse=True)[:top_k]
    retrieved_chunks = [content_map[doc_id] for doc_id, _ in sorted_docs]

    return "\n".join(retrieved_chunks)


def extract_clean_sql(generated_text: str) -> str:
    """Extracts pure SQL code from LLM response, discarding markdown code blocks and intro text."""
    sql_match = re.search(r"```(?:sql)?\s*(.*?)\s*```", generated_text, re.DOTALL | re.IGNORECASE)
    if sql_match:
        return sql_match.group(1).strip()

    lines = [
        line for line in generated_text.strip().split('\n')
        if
        not line.strip().startswith('```') and not re.match(r'^(here|the|this|sure|below)', line.strip(), re.IGNORECASE)
    ]
    return "\n".join(lines).strip()


def validate_sql_dry_run(sql_query: str) -> Tuple[bool, Optional[str], int]:
    """Executes a zero-cost BigQuery dry-run to validate syntax and schema rules."""
    job_config = bigquery.QueryJobConfig(dry_run=True, use_query_cache=False)
    try:
        query_job = bq_client.query(sql_query, job_config=job_config)
        bytes_scanned = query_job.total_bytes_processed
        return True, None, bytes_scanned
    except GoogleCloudError as e:
        return False, str(e), 0


def evaluate_sql_confidence(user_query: str, generated_sql: str) -> float:
    """Uses LLM-as-a-Judge to grade semantic alignment and confidence (0.0 to 1.0)."""
    judge_prompt = f"""
    You are a Senior Data Governance Auditor evaluating Text-to-SQL logic.

    USER INTENT: "{user_query}"
    GENERATED SQL:
    ```sql
    {generated_sql}
    ```

    Evaluate how confidently and accurately this SQL satisfies the user request without ungrounded joins or missing filters.
    Return ONLY a single numerical score between 0.00 and 1.00 (e.g., 0.92). Do not include extra text.
    """
    try:
        response = ai_client.models.generate_content(
            model=LLM_MODEL,
            contents=judge_prompt
        )
        score_match = re.search(r"0\.\d+|1\.0", response.text.strip())
        if score_match:
            return float(score_match.group(0))
        return 0.80  # Default conservative score if regex fails
    except Exception as e:
        print(f"⚠️ Confidence assessment warning: {e}")
        return 0.75


# =====================================================================
# 2. HUMAN-IN-THE-LOOP (HITL) INTERACTIVE TERMINAL UI
# =====================================================================
def trigger_hitl_escalation(
        user_query: str,
        generated_sql: str,
        scanned_mb: float,
        confidence_score: float,
        escalation_reasons: list[str]
) -> Tuple[str, Optional[str]]:
    """Displays a CLI escalation warning and prompts the user for A/D/F decision."""
    print("\n" + "🚨 " + "=" * 65)
    print(" ⚠️  ENTERPRISE GOVERNANCE ESCALATION TRIGGERED (HITL)  ⚠️")
    print("=" * 69)
    print(f"📌 User Intent : \"{user_query}\"")
    print("\n🛑 Escalation Reasons:")
    for reason in escalation_reasons:
        print(f"   • {reason}")

    print("\n📊 Metric Summary:")
    print(f"   • Estimated Scan Size : {scanned_mb:.2f} MB  (Threshold: {MAX_COST_MB:.2f} MB)")
    print(f"   • Confidence Score    : {confidence_score:.2f}     (Threshold: {MIN_CONFIDENCE_SCORE:.2f})")

    print("\n📝 Proposed SQL Query:")
    print("-" * 69)
    print(generated_sql)
    print("-" * 69)

    while True:
        print("\nChoose an action:")
        print("  [A]pprove : Override governance warning and proceed with execution")
        print("  [D]ecline : Abort query execution and return to main prompt")
        print("  [F]eedback : Provide manual instructions to regenerate SQL")

        choice = input("\n👉 Enter choice [A / D / F]: ").strip().upper()

        if choice in ['A', 'APPROVE']:
            print("\n✅ User overridden: Query approved for execution.")
            return 'APPROVE', None

        elif choice in ['D', 'DECLINE']:
            print("\n🛑 User declined: Query execution aborted.")
            return 'DECLINE', None

        elif choice in ['F', 'FEEDBACK']:
            user_feedback = input("\n💬 Enter specific instructions or corrections for the AI:\n> ").strip()
            if not user_feedback:
                print("⚠️ Feedback cannot be empty. Please try again.")
                continue
            return 'FEEDBACK', user_feedback

        else:
            print("❌ Invalid selection. Please enter 'A', 'D', or 'F'.")


# =====================================================================
# 3. GOVERNED SQL GENERATION & HITL LOOP
# =====================================================================
def generate_governed_sql(user_query: str, max_retries: int = MAX_RETRIES) -> Optional[str]:
    """Generates, validates, and self-heals BigQuery SQL with integrated HITL escalation."""
    with TerminalSpinner("Retrieving governed schemas & Dataform assertions via Hybrid Search..."):
        context = retrieve_governed_context(user_query, top_k=30)

    system_instruction = f"""
    You are an expert GCP Analytics Engineer for APEX Activewear.
    Translate the user request into valid BigQuery Standard SQL using ONLY the provided context.

    TARGET PROJECT: `{PROJECT_ID}`
    ALLOWED DATASETS: `gold_layer`, `silver_layer`

    STRICT GOVERNANCE & ROUTING RULES:
    1. Prefer certified `gold_layer` marts for pre-calculated metrics and aggregated cohorts.
    2. Query `silver_layer` tables when specific dimensions or granular transactional data are requested that are absent from Gold marts.
    3. Treat analytical requests for 'growth', 'change', 'rates', or 'trends' as DYNAMIC CALCULATIONS. Derive them dynamically using CTEs, `SUM()`, `COUNT(DISTINCT)`, and window functions like `LAG() OVER (...)`.
    4. Allow natural semantic mapping of synonyms (e.g., 'acquisition channel' maps to 'acquisition_source').
    5. Strictly apply all Dataform assertion business rules (e.g., exclude returns via status filters, check status, handle ghost revenue).
    6. Only output -- ERROR: Required data not available in certified tables if the fundamental entity is missing.
    7. Output ONLY raw executable SQL inside standard ```sql ``` markdown blocks without conversational text.
    8. Treat GOLDEN FEW-SHOT EXAMPLES strictly as structural blueprints.

    GOVERNED CONTEXT & SCHEMAS:
    {context}
    """

    feedback_context = ""

    for attempt in range(max_retries + 1):
        prompt = system_instruction
        if feedback_context:
            prompt += f"\n\nPREVIOUS ATTEMPT CORRECTION / FEEDBACK:\n{feedback_context}\nPlease adjust the SQL structure, joins, and filters accordingly."

        with TerminalSpinner(f"Generating governed BigQuery SQL (Attempt {attempt + 1}/{max_retries + 1})..."):
            response = ai_client.models.generate_content(
                model=LLM_MODEL,
                contents=prompt + f"\n\nUSER QUESTION: {user_query}"
            )

        sql_query = extract_clean_sql(response.text)

        if "-- ERROR" in sql_query.upper() or "SELECT" not in sql_query.upper():
            print("⚠️ Governance Guardrail Triggered: Requested attribute not found in certified schemas.")
            return sql_query

        # Step 1: Zero-Cost BigQuery Dry-Run
        with TerminalSpinner(f"Executing BigQuery Dry-Run syntax validation..."):
            is_valid, error_msg, bytes_scanned = validate_sql_dry_run(sql_query)

        if not is_valid:
            print(f"❌ Dry-run syntax error: {error_msg}")
            feedback_context = f"SQL SYNTAX ERROR: {error_msg}"
            continue

        scanned_mb = bytes_scanned / (1024 ** 2)
        print(f"✅ Dry-run syntax passed! Estimated scanned bytes: {scanned_mb:.2f} MB")

        # Step 2: Evaluate LLM Confidence Score
        with TerminalSpinner("Auditing query semantic confidence..."):
            confidence_score = evaluate_sql_confidence(user_query, sql_query)
        print(f"✅ Semantic confidence score: {confidence_score:.2f}")

        # Step 3: Check Governance Escalation Triggers
        escalation_reasons = []
        if scanned_mb > MAX_COST_MB:
            escalation_reasons.append(
                f"Data Scan Exceeds Limit: Estimated {scanned_mb:.2f} MB exceeds max threshold of {MAX_COST_MB:.2f} MB."
            )
        if confidence_score < MIN_CONFIDENCE_SCORE:
            escalation_reasons.append(
                f"Low Confidence Score: Score {confidence_score:.2f} is below required threshold of {MIN_CONFIDENCE_SCORE:.2f}."
            )

        # Step 4: Execute Normal Path or Trigger HITL
        if not escalation_reasons:
            return sql_query

        # HITL Escalation Block
        decision, user_feedback = trigger_hitl_escalation(
            user_query=user_query,
            generated_sql=sql_query,
            scanned_mb=scanned_mb,
            confidence_score=confidence_score,
            escalation_reasons=escalation_reasons
        )

        if decision == 'APPROVE':
            return sql_query
        elif decision == 'DECLINE':
            return None
        elif decision == 'FEEDBACK':
            feedback_context = f"HUMAN FEEDBACK INSTRUCTION: {user_feedback}"
            print(f"\n🔄 Injecting feedback into self-healing loop for Attempt {attempt + 2}...")

    print("❌ Reached maximum retry/feedback limit without an approved query.")
    return None


# =====================================================================
# 4. MAIN EXECUTION LOOP
# =====================================================================
if __name__ == "__main__":
    print("=" * 69)
    print(" 🤖 APEX Activewear - Governed Text-to-SQL RAG CLI (HITL Enabled) ")
    print(f" Config: MAX_COST_MB = {MAX_COST_MB} MB | MIN_CONFIDENCE = {MIN_CONFIDENCE_SCORE}")
    print(" Type 'exit', 'quit', or 'q' to stop the session.")
    print("=" * 69)

    while True:
        try:
            user_question = input("\nDear APEXer, please enter your query:\n> ").strip()

            if user_question.lower() in ['exit', 'quit', 'q']:
                print("\nShutting down Governed AI session. Goodbye!")
                break

            if not user_question:
                continue

            print(f"\n🔍 Processing Question: '{user_question}'")
            final_sql = generate_governed_sql(user_question)

            if final_sql:
                print("\n================ FINAL APPROVED SQL QUERY ================")
                print(final_sql)
                print("=" * 58)
            else:
                print("\n⚠️ Query generation process ended without executable SQL.")

        except KeyboardInterrupt:
            print("\n\nSession interrupted by user. Exiting...")
            break
        except Exception as e:
            print(f"\n❌ Error processing query: {e}")