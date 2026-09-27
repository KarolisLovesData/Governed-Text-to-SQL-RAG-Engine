# Governed Text-to-SQL Agent for APEX Activewear

![Python](https://img.shields.io/badge/Python-3.11+-blue.svg?logo=python&logoColor=white)
![Google Cloud](https://img.shields.io/badge/GCP-Cloud_Infrastructure-4285F4.svg?logo=googlecloud&logoColor=white)
![BigQuery](https://img.shields.io/badge/BigQuery-Data_Warehouse-669DF6.svg?logo=googlebigquery&logoColor=white)
![BigQuery Vector Search](https://img.shields.io/badge/Vector_Search-Hybrid_RAG-336791.svg?logo=googlebigquery&logoColor=white)
![Dataform](https://img.shields.io/badge/Dataform-Governance_Guardrails-4285F4.svg?logo=googlecloud&logoColor=white)
![Gemini AI](https://img.shields.io/badge/AI-Gemini_3.7_Flash-8E75B2.svg?logo=google-gemini&logoColor=white)

## ⚠️ Context & Business Problem: Hallucinated Analytics

**APEX Activewear** processes 436K+ transactions totaling **$48.85M** in order volume. While the underlying BigQuery warehouse is robust, pointing standard Large Language Models (LLMs) directly at raw enterprise schemas introduces severe operational and financial risks.

Out-of-the-box LLMs create a dangerous illusion of success. They generate syntactically flawless SQL, but fail catastrophically on two critical fronts:
* **Silent Financial Errors:** The AI confidently writes code that executes without syntax errors, but miscalculates metrics by ignoring unwritten transformation logic—such as blindly aggregating gross sales without filtering out a **24% return rate** or misinterpreting **"Ghost Revenue"** assertions.
* **The Business Translation Gap:** Standard models fail to map ambiguous, plain-English stakeholder terminology (e.g., "serial returners" or "product drag") to certified gold-layer table structures.

To eliminate these risks, the business required an architecture capable of translating plain-English intent into SQL while strictly enforcing live Dataform governance rules—guaranteeing **CFO-level accuracy** before any query is executed.

## 💡 The Solution: A "Zero-Hallucination" Semantic Layer

I engineered a custom **Retrieval-Augmented Generation (RAG) Governance Agent** that intercepts natural-language intent and safely translates it into production-grade **BigQuery SQL**. This **Python CLI backend** serves as the foundational governance engine for future stakeholder-facing interfaces (e.g., **Streamlit** or Slackbots), enforcing **CFO-level accuracy** at scale.

<img src="visuals/Hybrid_Search_Architecture.jpeg" alt="RAG CLI Demo" width="800">

**Key Technical Implementations:**
* **Dynamic Dataform & Schema Ingestion:** The indexing pipeline programmatically parses JSON **Golden Few-Shot Queries**, CSV governance rules, and BigQuery `INFORMATION_SCHEMA` to construct and maintain a dynamically updating semantic vector index.
* **Native BigQuery Hybrid Search:** Pushed the search workload directly into the warehouse using BigQuery `VECTOR_SEARCH` (dense semantic intent) and BigQuery Text Indexes (sparse keyword matching). I engineered custom **Reciprocal Rank Fusion (RRF)** scoring natively in **Python** to mathematically merge these dataframes, optimizing context retrieval without relying on bloated external frameworks.
* **Agentic Self-Healing AI Loop:** Operates as a dynamic balancing feedback mechanism driven by a **$0 BigQuery dry-run API**. If a `GoogleCloudError` (syntax error or schema mismatch) triggers, the system explicitly catches the exception and injects the exact error trace back into the LLM context for automated correction prior to final execution.
* **Strict Governance Guardrails:** By restricting the AI exclusively to certified `gold_layer` and select `silver_layer` tables, the architecture creates a hard security boundary. This isolation prevents unauthorized cross-domain joins and unintended data exposure, ensuring stakeholders can query the warehouse with mathematical certainty that the generated SQL perfectly matches certified business definitions.


## 🏗️ Data Architecture & Scale

The AI engine successfully navigates a production-grade **Dataform Medallion architecture**, seamlessly joining interconnected entity domains (**users**, **distribution centers**, **products**, and **online events**). 

The underlying topology consists of:
* **Raw Ingestion Layer:** 6 foundational source declarations managing event and transactional data.
* **Silver Staging & Quality:** Standardized views protected by automated logic, including **logistical timeline validations** and **revenue status assertions**.
* **Gold Analytical Marts:** 10+ certified dimensional models powering aggregations like **RFM segmentation**, **cohort retention**, and **global fulfillment tracking**.

To prevent join hallucinations, the AI is restricted from reading raw schemas; instead, it routes user intent strictly through the validated transformation paths mapped in the **dependency graph** below: 

<img src="visuals/Dataform Medallion Architecture DAG.png" alt="Dataform Medallion Architecture DAG" width="900">
## 📊 Quantitative Benchmark: Baseline vs. Governed RAG Agent

The system is evaluated against a test suite of **23 complex business queries** (spanning strict financial logic, windowed growth calculations, and ambiguous business jargon) to prove the governance layer's impact on enterprise reliability.

| Evaluation Metric (n=23) | Baseline (Schema-Only) | Champion (Governed RAG) | Business Impact / Trade-off |
| :--- | :--- | :--- | :--- |
| **Dry-Run Syntax Accuracy** | 100.0% | **100.0%** | Zero syntactic crashes across both models |
| **Schema Precision** | 91.3% | **95.7%** | **+4.4%** in resolving ambiguous business terminology |
| **Semantic Logic Match** *(LLM Judge)*¹ | 78.3% *(18/23)* | **91.3% *(21/23)*** | **+13.0%** elimination of unwritten financial logic errors |
| **Average Latency** | ~9.45s | **~11.24s** | +1.79s tradeoff for multi-agent validation and hybrid search |

> **¹ Evaluation Methodology (LLM-as-a-Judge):** Semantic accuracy was programmatically evaluated using **Gemini 3.7 Flash** as an automated judge. Generated SQL queries were compared against Ground Truth [eval_queries.json](data/eval_queries.json) queries to verify semantic logic, CTE calculations, and business metric alignment beyond strict syntax.
### 🧠 Failure Mode Analysis & Resolution

1. **The Translation Gap (Schema Precision):** Standard LLM prompting failed to map non-technical jargon (e.g., "serial returners") to raw table names, yielding a 91.3% schema precision. Hybrid Vector Search mathematically bridges this gap, routing queries directly to certified analytical marts at **95.7% precision**.
2. **Silent Financial Errors (Logic Match):** While the baseline produced syntactically valid SQL, it missed unwritten business rules (such as omitting canceled orders from revenue calculations). Injecting governed Dataform assertions dynamically closed the **13.0% logic gap**.

### 🏗️ Architectural Decision Records (ADR)

* **LLM-as-a-Judge vs. Deterministic Testing:** Deterministic assertions (e.g., Pandas `.equals()`) penalize models for intelligently structuring derived metrics. A multi-agent semantic evaluation framework grades logical equivalence, allowing flexible, correct outputs without failing CI/CD checks.
* **RAG vs. Fine-Tuning:** Fine-tuning locks in static table structures that break as warehouse schemas evolve. Hybrid Search RAG with dynamic `INFORMATION_SCHEMA` indexing ensures strict adherence to live data contracts at zero retraining cost.
## 🔍 System in Action: Live CLI Demos

Visual proof is critical. The following terminal executions demonstrate the engine's ability to ingest complex business intent, navigate the Medallion architecture, and output cost-validated, production-ready SQL.

### 🛡️ Sample 1: Proactive Cost Control & Pre-Execution Validation
LLM-generated SQL poses severe financial risks if it blindly queries unoptimized datasets. To mitigate this, the engine intercepts the generated query and executes a **$0 BigQuery API dry-run**. 

*Notice in the terminal execution below how the agent validates syntax and explicitly estimates compute costs (MBs scanned) **before** final output.*

**User Prompt:**
> *List the country, total spend, and average order value for customers in the High churn risk tier who placed more than 3 orders in 2024.*

<img src="visuals/app_in_action_01.png" alt="CLI Execution for Churn Risk Metrics" width="900">

<details>
<summary><b>🔍 View Validated Governed SQL</b></summary>

```sql
WITH user_order_stats AS (
  SELECT
    oi.user_id,
    u.country,
    COUNT(DISTINCT oi.order_id) AS total_orders_2024,
    SUM(CAST(oi.sale_price AS NUMERIC)) AS total_spend_2024,
    SUM(CAST(oi.sale_price AS NUMERIC)) / NULLIF(COUNT(DISTINCT oi.order_id), 0) AS average_order_value_2024
  FROM `apex-activewear.silver_layer.stg_order_items` AS oi
  JOIN `apex-activewear.silver_layer.stg_users` AS u ON oi.user_id = u.user_id
  WHERE EXTRACT(YEAR FROM oi.created_at) = 2024
    AND oi.status NOT IN ('Returned', 'Cancelled')
  GROUP BY oi.user_id, u.country
  HAVING COUNT(DISTINCT oi.order_id) > 3
),
churn_filtered_users AS (
  SELECT user_id
  FROM `apex-activewear.silver_layer.user_churn_data`
  WHERE churn_risk_tier = 'High'
)
SELECT
  uos.country,
  SUM(uos.total_spend_2024) AS total_spend,
  AVG(uos.average_order_value_2024) AS average_order_value
FROM user_order_stats uos
JOIN churn_filtered_users cfu ON uos.user_id = cfu.user_id
GROUP BY uos.country
ORDER BY total_spend DESC;
```

</details>

 ### 📈 Sample 2: Advanced Metric Derivation (Window Functions)
Standard LLMs struggle with multi-step period-over-period calculations. This agent successfully translates raw business requests into advanced LAG() **window math** and dynamic Common Table Expressions (CTEs), enforcing analytical rigor without requiring explicit prompt engineering.

**User Prompt:**
> *What is the month-over-month revenue growth rate and total distinct buyer count for top product categories in 2023, excluding returned items?*

<img src="visuals/app_in_action_02.png" alt="CLI Execution for MoM Growth" width="900">

<details>
<summary><b>🔍 View Governed SQL with Window Math</b></summary>

```sql
WITH monthly_metrics AS (
  SELECT
    p.category,
    EXTRACT(MONTH FROM oi.created_at) AS order_month,
    COUNT(DISTINCT oi.user_id) AS distinct_buyer_count,
    SUM(CAST(oi.sale_price AS NUMERIC)) AS total_revenue
  FROM `apex-activewear.silver_layer.stg_order_items` oi
  JOIN `apex-activewear.silver_layer.stg_products` p ON oi.product_id = p.product_id
  WHERE EXTRACT(YEAR FROM oi.created_at) = 2023
    AND oi.status NOT IN ('Returned', 'Cancelled')
  GROUP BY p.category, order_month
),
mom_calculations AS (
  SELECT
    category,
    order_month,
    distinct_buyer_count,
    total_revenue,
    LAG(total_revenue) OVER (PARTITION BY category ORDER BY order_month) AS prev_month_revenue,
    LAG(distinct_buyer_count) OVER (PARTITION BY category ORDER BY order_month) AS prev_month_buyers
  FROM monthly_metrics
)
SELECT
  category,
  order_month,
  total_revenue,
  distinct_buyer_count,
  ROUND(SAFE_DIVIDE(total_revenue - prev_month_revenue, prev_month_revenue) * 100, 2) AS revenue_growth_rate_pct,
  ROUND(SAFE_DIVIDE(distinct_buyer_count - prev_month_buyers, prev_month_buyers) * 100, 2) AS buyer_growth_rate_pct
FROM mom_calculations
ORDER BY category, order_month;
```

</details>

## ⚙️ Repository Structure & Quickstart

This engine is split into three primary automated modules that map directly to the Medallion architecture workflow:

* **`1_build_bq_hybrid_index.py` (The Governance Indexer):** The ingestion pipeline. It reads schemas, queries, and business assertions from the Silver and Gold layers, generates embeddings via `gemini-embedding-001`, and overwrites the active `ai_governance_index` table in BigQuery.
* **`text_to_sql_engine.py` (The RAG Execution Agent):** The user-facing operational layer. It takes user input, performs the hybrid search against the index, prompts `gemini-3.7-flash`, executes the self-healing dry-run loop, and outputs the final governed SQL strictly routed through certified Dataform models.
* **`3_run_evals.py` (The CI/CD Validator):** The LLM-as-a-Judge evaluation suite. It programmatically tests the generated SQL against a golden dataset to guarantee semantic logic matches and schema precision prior to deployment, ensuring the pipeline's analytical rigor remains intact.
