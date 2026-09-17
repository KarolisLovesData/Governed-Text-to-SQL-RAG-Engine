# Governed Text-to-SQL Agent for APEX Activewear

![Python](https://img.shields.io/badge/Python-3.11+-blue.svg?logo=python&logoColor=white)
![Google Cloud](https://img.shields.io/badge/GCP-Cloud_Infrastructure-4285F4.svg?logo=googlecloud&logoColor=white)
![BigQuery](https://img.shields.io/badge/BigQuery-Data_Warehouse-669DF6.svg?logo=googlebigquery&logoColor=white)
![BigQuery Vector Search](https://img.shields.io/badge/Vector_Search-Hybrid_RAG-336791.svg?logo=googlebigquery&logoColor=white)
![Dataform](https://img.shields.io/badge/Dataform-Governance_Guardrails-4285F4.svg?logo=googlecloud&logoColor=white)
![Gemini AI](https://img.shields.io/badge/AI-Gemini_3.7_Flash-8E75B2.svg?logo=google-gemini&logoColor=white)

## 📊 Executive Summary
**APEX Activewear** is a simulated $48.85M e-commerce dataset powered by a BigQuery and Cloud Dataform Medallion architecture. While the pipeline successfully processes over 436K+ orders, non-technical stakeholders faced a critical bottleneck: extracting actionable insights required waiting on the data team to write custom SQL.

## ⚠️ The Business Problem: Hallucinated Analytics
To enable self-service, stakeholders attempted to use out-of-the-box LLMs to query the data warehouse. However, raw models inherently **hallucinate business logic**. They blindly queried uncertified staging tables, ignored complex financial definitions (like filtering out our 24% return rate), and missed critical "Ghost Revenue" filters, resulting in mathematically incorrect metrics.

## 💡 The Solution: A "Zero-Hallucination" Semantic Layer
I engineered a custom **Retrieval-Augmented Generation (RAG) Governance Agent** that intercepts natural-language questions and safely translates them into production-grade BigQuery SQL. 

**Key Technical Implementations:**
* **Native BigQuery Hybrid Search:** Pushed the search workload directly into the warehouse, utilizing BigQuery `VECTOR_SEARCH` (dense semantic intent) and BigQuery Text Indexes (sparse keyword matching) fused via Reciprocal Rank Fusion (RRF).
* **Strict Governance Guardrails:** Dynamically parses BigQuery `INFORMATION_SCHEMA` and Dataform assertions, restricting the AI exclusively to certified `gold_layer` tables.
* **Self-Healing AI Loop:** Integrates a BigQuery dry-run API validation step that catches syntax/schema errors and forces the Gemini 3.7 Flash model to auto-correct before outputting the final query.

**Business Impact:** Stakeholders can now query the warehouse in plain English with mathematical certainty that the generated SQL perfectly matches the CFO's definition of realized revenue.

---

### 🔍 System Action
#### *A sample governed query:*

<img src="visuals/rag_cli_demo.gif" alt="RAG CLI Demo" width="800">

#### *Ground Truth Verification: Executing the Governed Query in BigQuery*

<img src="visuals/bigquery_governance_validation.png" alt="BigQuery Execution Verification" width="800">
