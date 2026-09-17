# Governed-Text-to-SQL-Agent-for-APEX-Activewear

### <a id="ai-governance"></a>III. AI-Powered Semantic Layer & BI Governance

**Target:** Stakeholder Self-Service & Metric Standardization 

* **The Bottleneck:** Out-of-the-box LLMs inherently hallucinate business logic. Without guardrails, they blindly query raw tables, missing critical context like "Ghost Revenue" filters or our 24% return rate.
* **The Architecture:** Engineered a custom **Retrieval-Augmented Generation (RAG) Governance CLI** that intercepts stakeholder natural-language questions and binds the AI strictly to our validated Dataform pipeline logic.
* **Technical Execution:** Built a Python engine to dynamically parse BigQuery schemas and `Dataform Assertions` into a structured JSON dictionary. The LLM is prompt-restricted exclusively to the `gold_layer`, ensuring it outputs clean, compliant BigQuery Standard SQL.
* **Business Impact:** **"Zero-Hallucination" self-serve analytics.** Stakeholders can now query the warehouse in plain English with mathematical certainty that the generated SQL perfectly matches the CFO's definition of realized revenue.
#### *A sample governed query:*

<img src="./Visuals/rag_cli_demo.gif" alt="RAG CLI Demo" width="800">

#### *Ground Truth Verification: Executing the Governed Query in BigQuery*

<img src="Visuals/bigquery_governance_validation.png" alt="BigQuery Execution Verification" width="800">

---
