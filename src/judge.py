"""
judge.py - ONE shared LLM judge used by BOTH baseline_evals.py and 3_run_evals.py.

Why it exists
-------------
* Independent judge: Gemini generates the SQL, Claude grades it (different model family).
* Fair comparison: Baseline and Champion are graded with the identical prompt and rubric.
* Reproducible: pinned model, temperature 0, prompt version stored with every verdict.
* Honest errors: an API/parsing problem is reported as ERROR, never silently counted as FAIL.
* Cheap: verdicts are cached on disk, and a hard call limit protects the credits.

Usage
-----
    from judge import judge_sql, exact_table_match, usage_summary
    v = judge_sql(question, golden_sql, generated_sql)            # default: claude-sonnet-5-5
    v = judge_sql(question, golden_sql, generated_sql, model="claude-opus-5-5")   # audit run
    v["verdict"]  -> "PASS" | "FAIL" | "ERROR"
"""
import hashlib
import json
import os
import re
from pathlib import Path

import anthropic
from dotenv import load_dotenv

HERE = Path(__file__).resolve().parent
load_dotenv(HERE / ".env")

DEFAULT_JUDGE_MODEL = "claude-sonnet-5-5"
PROMPT_VERSION = "v1"
MAX_OUTPUT_TOKENS = 2000   # headroom: some models spend part of the budget on internal thinking blocks
MAX_CALLS = int(os.getenv("JUDGE_MAX_CALLS", "400"))          # hard stop to protect credits
CACHE_PATH = Path(os.getenv("JUDGE_CACHE_PATH", HERE.parent / "results" / "judge_cache.json"))

FAILURE_TYPES = [
    "wrong_table",            # answers from a table with different meaning / wrong source
    "missing_business_rule",  # e.g. does not exclude Returned/Cancelled from revenue
    "wrong_filter",           # wrong year, department, threshold, status, etc.
    "wrong_grain",            # wrong GROUP BY level / wrong aggregation level
    "wrong_metric",           # wrong measure or formula
    "no_sql",                 # nothing usable was generated
    "other",
]

SYSTEM_PROMPT = """You are a strict senior analytics engineer grading Text-to-SQL output for a BigQuery warehouse.
You are given a business question, a GROUND TRUTH query written by a human expert, and a GENERATED query.
Decide whether the GENERATED query would correctly answer the business question.

PASS when the generated query:
- uses a source table that gives the same business meaning as the ground truth (a different but equivalent table is fine),
- returns the core metrics and dimensions the question asks for, at the same grain,
- applies the same business-rule filters as the ground truth (for example excluding Returned and Cancelled items from revenue, the same year, department or threshold),
- may differ in aliases, CTE vs subquery structure, ordering, extra helpful columns or rounding.

FAIL when the generated query:
- reads a table with a different meaning, or a table the question does not point to,
- misses or changes a business-rule filter, a time filter or a threshold,
- aggregates at the wrong grain or computes the wrong metric,
- answers a different question than the one asked.

Judge only from the question, the ground truth and the generated SQL. Do not give credit for effort.
Reply with a single JSON object and nothing else:
{"verdict": "PASS" or "FAIL", "reason": "<one sentence>", "failure_type": null if PASS, otherwise one of: wrong_table, missing_business_rule, wrong_filter, wrong_grain, wrong_metric, other}"""

_client = None
_usage = {"calls": 0, "cache_hits": 0, "input_tokens": 0, "output_tokens": 0}
_cache = None


# ----------------------------------------------------------------- client / cache
def _get_client():
    global _client
    if _client is None:
        key = os.getenv("CLAUDE_API_KEY")
        if not key:
            raise RuntimeError("CLAUDE_API_KEY not found. Put it in src/.env (no quotes, no spaces around '=').")
        _client = anthropic.Anthropic(api_key=key, timeout=90.0, max_retries=2)
    return _client


def _load_cache():
    global _cache
    if _cache is None:
        try:
            _cache = json.loads(CACHE_PATH.read_text(encoding="utf-8"))
        except (FileNotFoundError, json.JSONDecodeError):
            _cache = {}
    return _cache


def _save_cache():
    try:
        CACHE_PATH.parent.mkdir(parents=True, exist_ok=True)
        CACHE_PATH.write_text(json.dumps(_cache, indent=1), encoding="utf-8")
    except OSError:
        pass  # caching is a convenience, never a reason to fail


def _cache_key(model, question, golden_sql, generated_sql):
    raw = json.dumps([PROMPT_VERSION, model, question, golden_sql, generated_sql], sort_keys=True)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


# ------------------------------------------------------------------- core call
_send_temperature = True


def _call_model(model, user_prompt):
    global _usage
    if _usage["calls"] >= MAX_CALLS:
        raise RuntimeError(f"Judge call limit reached ({MAX_CALLS}). Raise JUDGE_MAX_CALLS if this is intended.")
    client = _get_client()
    kwargs = dict(model=model, max_tokens=MAX_OUTPUT_TOKENS, system=SYSTEM_PROMPT,
                  messages=[{"role": "user", "content": user_prompt}])
    global _send_temperature
    resp = None
    if _send_temperature:
        try:
            resp = client.messages.create(temperature=0, **kwargs)
        except TypeError:                         # this SDK / model combination takes no temperature argument
            _send_temperature = False
        except anthropic.BadRequestError as e:
            if "temperature" in str(e).lower():   # some models fix their own sampling settings
                _send_temperature = False
            else:
                raise
    if resp is None:
        resp = client.messages.create(**kwargs)
    _usage["calls"] += 1
    _usage["input_tokens"] += getattr(resp.usage, "input_tokens", 0) or 0
    _usage["output_tokens"] += getattr(resp.usage, "output_tokens", 0) or 0
    # The reply may start with a "thinking" block that has no .text: keep only the text blocks.
    return "".join(getattr(b, "text", "") or "" for b in resp.content if getattr(b, "type", "text") == "text")


def _parse_verdict(text):
    m = re.search(r"\{.*\}", text or "", re.DOTALL)
    if not m:
        return None
    try:
        obj = json.loads(m.group(0))
    except json.JSONDecodeError:
        return None
    verdict = str(obj.get("verdict", "")).strip().upper()
    if verdict not in ("PASS", "FAIL"):
        return None
    ftype = obj.get("failure_type")
    if verdict == "PASS":
        ftype = None
    elif ftype not in FAILURE_TYPES:
        ftype = "other"
    return {"verdict": verdict, "reason": str(obj.get("reason", ""))[:300], "failure_type": ftype}


def judge_sql(question, golden_sql, generated_sql, model=None, use_cache=True):
    """Grade one generated query. Always returns a dict with verdict PASS / FAIL / ERROR."""
    model = model or DEFAULT_JUDGE_MODEL
    base = {"judge_model": model, "prompt_version": PROMPT_VERSION}

    if not generated_sql or not str(generated_sql).strip():
        return {**base, "verdict": "FAIL", "reason": "No SQL was generated.", "failure_type": "no_sql", "cached": False}

    key = _cache_key(model, question, golden_sql, generated_sql)
    cache = _load_cache()
    if use_cache and key in cache:
        _usage["cache_hits"] += 1
        return {**base, **cache[key], "cached": True}

    user_prompt = (
        f"BUSINESS QUESTION:\n{question}\n\n"
        f"GROUND TRUTH SQL:\n```sql\n{golden_sql}\n```\n\n"
        f"GENERATED SQL:\n```sql\n{generated_sql}\n```"
    )
    parsed, last_err = None, ""
    for _attempt in range(2):                     # one retry if the reply is not valid JSON
        try:
            text = _call_model(model, user_prompt)
        except (anthropic.AuthenticationError, anthropic.PermissionDeniedError, anthropic.NotFoundError):
            raise                                  # wrong key / no access / bad model name: stop immediately
        except anthropic.APIError as e:
            last_err = f"API error: {str(e)[:150]}"
            continue
        except RuntimeError:
            raise                                  # call limit reached: stop the run
        except Exception as e:                     # unexpected reply shape: record an ERROR, never crash the run
            last_err = f"Unexpected judge error: {type(e).__name__}: {str(e)[:150]}"
            continue
        parsed = _parse_verdict(text)
        if parsed:
            break
        last_err = "Judge reply was not valid JSON: " + repr((text or "")[:240])

    if not parsed:
        return {**base, "verdict": "ERROR", "reason": last_err, "failure_type": None, "cached": False}

    cache[key] = parsed
    _save_cache()
    return {**base, **parsed, "cached": False}


# ------------------------------------------------------------ deterministic check
# The project prefix is optional: `gold_layer.t` and `apex-activewear.gold_layer.t` are the same table.
_TABLE_RE = re.compile(r"(?<![a-z0-9_])(?:gold_layer|silver_layer)`?\.`?([a-z0-9_]+)", re.IGNORECASE)


def tables_in(sql):
    return {t.lower() for t in _TABLE_RE.findall(sql or "")}


def exact_table_match(expected_tables, generated_sql):
    """True only if every expected table is referenced by its exact name.
    (The old substring check let 'user_churn_data' match 'user_churn_data_current'.)"""
    return {t.lower() for t in expected_tables} <= tables_in(generated_sql)


def usage_summary():
    return dict(_usage)
