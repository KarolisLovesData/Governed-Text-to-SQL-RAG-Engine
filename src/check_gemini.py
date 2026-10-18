"""Quick check that the Gemini API works for the Text-to-SQL engine. Run from the src folder: python check_gemini.py"""
import time

from text_to_sql_engine import EMBEDDING_MODEL, LLM_MODEL, ai_client   # same key (.env) and models as the engine


def test(label, call):
    start = time.time()
    try:
        call()
        print(f"OK    {label} ({time.time() - start:.1f}s)")
    except Exception as e:
        print(f"FAIL  {label}: {str(e)[:160]}")


test(f"{LLM_MODEL} (SQL generation)",
     lambda: ai_client.models.generate_content(model=LLM_MODEL, contents="Reply with the word OK"))
test(f"{EMBEDDING_MODEL} (hybrid search)",
     lambda: ai_client.models.embed_content(model=f"models/{EMBEDDING_MODEL}", contents=["test"]))
