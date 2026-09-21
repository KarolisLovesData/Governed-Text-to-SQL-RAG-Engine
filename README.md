# Governed Text-to-SQL Agent for APEX Activewear

![Python](https://img.shields.io/badge/Python-3.11+-blue.svg?logo=python&logoColor=white)
![Google Cloud](https://img.shields.io/badge/GCP-Cloud_Infrastructure-4285F4.svg?logo=googlecloud&logoColor=white)
![BigQuery](https://img.shields.io/badge/BigQuery-Data_Warehouse-669DF6.svg?logo=googlebigquery&logoColor=white)
![BigQuery Vector Search](https://img.shields.io/badge/Vector_Search-Hybrid_RAG-336791.svg?logo=googlebigquery&logoColor=white)
![Dataform](https://img.shields.io/badge/Dataform-Governance_Guardrails-4285F4.svg?logo=googlecloud&logoColor=white)
![Gemini AI](https://img.shields.io/badge/AI-Gemini_3.7_Flash-8E75B2.svg?logo=google-gemini&logoColor=white)

## ⚠️ Context & Business Problem: Hallucinated Analytics

**APEX Activewear** processes 436K+ transactions and **$48.85M** in total volume. While the underlying data infrastructure is robust, non-technical stakeholders faced a critical bottleneck: actionable insights required the data team to write custom SQL.

Pointing out-of-the-box LLMs directly at the warehouse created severe financial risk. Raw models confidently hallucinated business logic—blindly querying uncertified staging tables and ignoring complex financial definitions, such as filtering out a **24% return rate** or applying **"Ghost Revenue"** rules.

The business required an **AI semantic layer** capable of enabling plain-English querying while strictly enforcing **CFO-level accuracy**. This repository contains the **Python CLI backend agent** engineered to safely execute these translations, serving as the foundational governance engine for future stakeholder-facing interfaces (e.g., **Streamlit** or Slackbots).

## 🏗️ Data Architecture & Scale

Translating natural language to SQL is highly complex within a **production-grade relational warehouse**. The AI engine is engineered to successfully navigate a comprehensive **Dataform Medallion architecture**, seamlessly joining interconnected entity domains (**users**, **distribution centers**, **products**, and **online events**). 

The underlying topology consists of:

* **Raw Ingestion Layer:** 6 foundational source declarations managing continuous event and transactional data.
* **Silver Staging & Quality:** Standardized views protected by strict automated logic, including **logistical timeline validations** and **revenue status assertions**.
* **Gold Analytical Marts:** 10+ certified dimensional models powering complex downstream aggregations, such as **RFM segmentation**, **cohort retention**, and **global fulfillment tracking**.

To prevent join hallucinations across this scale, an AI cannot simply read raw schema; to safely route user intent through validated transformation paths it must be constrained by the exact **dependency graph** shown below: 

<img src="visuals/Dataform Medallion Architecture DAG.png" alt="Dataform Medallion Architecture DAG" width="900">

## 💡 The Solution: A "Zero-Hallucination" Semantic Layer

I engineered a custom **Retrieval-Augmented Generation (RAG) Governance Agent** that intercepts natural-language questions and safely translates them into production-grade **BigQuery SQL**.

<img src="visuals/Hybrid_Search_Architecture.jpeg" alt="RAG CLI Demo" width="800">

**Key Technical Implementations:**
* **Dynamic Dataform & Schema Ingestion:** The indexing pipeline programmatically parses JSON **Golden Few-Shot Queries**, CSV governance rules, and BigQuery `INFORMATION_SCHEMA` to dynamically construct and update the semantic vector index.
* **Native BigQuery Hybrid Search with Custom RRF:** Pushed the search workload directly into the warehouse using BigQuery `VECTOR_SEARCH` (dense semantic intent) and BigQuery Text Indexes (sparse keyword matching). I engineered custom **Reciprocal Rank Fusion (RRF)** scoring logic in **Python** to mathematically merge these dataframes, optimizing context retrieval without relying on black-box external frameworks.
* **Agentic Self-Healing AI Loop:** Integrates a **$0 BigQuery dry-run API** validation step to virtually execute the generated query. If a `GoogleCloudError` (syntax error or schema mismatch) occurs, the agent explicitly catches the exception and feeds the exact error message back into the LLM context for automated correction before outputting the final SQL.
* **Strict Governance Guardrails:** By restricting the AI exclusively to certified `gold_layer` and select `silver_layer` tables, stakeholders can query the warehouse with mathematical certainty that the generated SQL perfectly matches certified business definitions.


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

This engine is split into two primary automated modules:

* **`1_build_bq_hybrid_index.py`**: The ingestion pipeline. It reads schemas, queries, and business assertions, generates embeddings via `gemini-embedding-001`, and overwrites the active `ai_governance_index` table in BigQuery.
* **`2_text_to_sql_engine.py`**: The RAG CLI execution agent. It takes user input, performs the hybrid search, prompts `gemini-3.7-flash`, executes the self-healing dry-run loop, and outputs the final governed SQL.
---
