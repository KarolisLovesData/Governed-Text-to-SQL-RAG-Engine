"""
APEX Activewear - Governance Index Builder

1. Ingests Golden Few-Shot Queries from golden_queries.json.
2. Ingests Dataform Governance Rules from CSV.
3. Ingests BigQuery table schemas across Gold and Silver layers.
4. Generates dense embeddings using gemini-embedding-001.
5. Overwrites the ai_governance_index table in BigQuery.
"""

import json
import os
import pandas as pd
from google import genai
from google.cloud import bigquery
from dotenv import load_dotenv

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
ENV_PATH = os.path.join(BASE_DIR, ".env")
load_dotenv(dotenv_path=ENV_PATH)

PROJECT_ID = "apex-activewear"
DATASET_ID = "gold_layer"
INDEX_TABLE_NAME = "ai_governance_index"
FULL_INDEX_TABLE = f"{PROJECT_ID}.{DATASET_ID}.{INDEX_TABLE_NAME}"
DATASETS_TO_INDEX = ["gold_layer", "silver_layer"]

EMBEDDING_MODEL = "gemini-embedding-001"
LOCATION = "US"

api_key = os.getenv("GEMINI_API_KEY")
if not api_key:
    raise ValueError(f"GEMINI_API_KEY not found in environment or {ENV_PATH}")

bq_client = bigquery.Client(project=PROJECT_ID, location=LOCATION)
ai_client = genai.Client(api_key=api_key)


def generate_embedding(text: str):
    """Generates a dense vector using gemini-embedding-001."""
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


def build_and_upload_index():
    records = []

    # 1. Process Golden Few-Shot Queries
    golden_path = os.path.join(BASE_DIR, "golden_queries.json")
    if os.path.exists(golden_path):
        print("📌 Processing Golden Few-Shot Queries...")
        with open(golden_path, "r", encoding="utf-8") as f:
            golden_list = json.load(f)
        for g in golden_list:
            chunk_text = f"GOLDEN FEW-SHOT EXAMPLE:\nQuestion: '{g['question']}'\nTarget SQL:\n{g['sql']}"
            print(f"  └─ Indexing golden query: {g['id']}")
            records.append({
                "id": g['id'],
                "type": "golden_query",
                "content_chunk": chunk_text,
                "embedding": generate_embedding(g['question'])
            })
    else:
        print("⚠️ golden_queries.json not found. Skipping golden queries.")

    # 2. Process Governance CSV / Assertions if present
    csv_path = os.path.join(BASE_DIR, "Apex Governance Layer.csv")
    if os.path.exists(csv_path):
        print("📌 Processing Governance CSV / Assertions...")
        gov_df = pd.read_csv(csv_path)
        for idx, row in gov_df.iterrows():
            asset_name = row.get("asset_name", f"rule_{idx}")
            logic = row.get("governance_logic", "")
            chunk_text = f"DATAFORM GOVERNANCE ASSERTION ({asset_name}): {logic}"
            print(f"  └─ Indexing assertion: {asset_name}")
            records.append({
                "id": f"assertion_{idx}",
                "type": "assertion",
                "content_chunk": chunk_text,
                "embedding": generate_embedding(chunk_text)
            })

    # 3. Process Table Schemas from BigQuery INFORMATION_SCHEMA
    print("📌 Processing BigQuery Table Schemas...")
    for dataset_id in DATASETS_TO_INDEX:
        query = f"""
        SELECT table_name, column_name, data_type
        FROM `{PROJECT_ID}.{dataset_id}.INFORMATION_SCHEMA.COLUMNS`
        ORDER BY table_name, ordinal_position
        """
        try:
            schema_df = bq_client.query(query).to_dataframe()
            grouped = schema_df.groupby('table_name')
            for table_name, group in grouped:
                cols_str = ", ".join([f"{row['column_name']} ({row['data_type']})" for _, row in group.iterrows()])
                chunk_text = f"TABLE SCHEMA: `{PROJECT_ID}.{dataset_id}.{table_name}`\nCOLUMNS: {cols_str}"
                print(f"  └─ Indexing schema: {dataset_id}.{table_name}")
                records.append({
                    "id": f"schema_{dataset_id}_{table_name}",
                    "type": "table_schema",
                    "content_chunk": chunk_text,
                    "embedding": generate_embedding(chunk_text)
                })
        except Exception as e:
            print(f"  └─ ⚠️ Failed to fetch schema for {dataset_id}: {e}")

    df = pd.DataFrame(records)
    print(f"\nTotal governance chunks prepared: {len(df)}")

    # 4. Overwrite Index Table in BigQuery
    print(f"Uploading index to `{FULL_INDEX_TABLE}`...")
    job_config = bigquery.LoadJobConfig(
        write_disposition=bigquery.WriteDisposition.WRITE_TRUNCATE
    )
    job = bq_client.load_table_from_dataframe(df, FULL_INDEX_TABLE, job_config=job_config)
    job.result()
    print("✅ Index successfully rebuilt and loaded into BigQuery!")


if __name__ == "__main__":
    build_and_upload_index()