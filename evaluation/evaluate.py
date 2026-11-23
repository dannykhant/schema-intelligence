"""Programmatic evaluation of agent answers against pre-registered ground truth.

Two signals per question, no LLM judge:

1. SQL result match — the agent's own generated SQL is executed read-only and
   compared row-by-row to ground_truth.json. Decisive whenever the answer
   contains a SELECT.
2. Keyword check  — `require` / `forbid` phrase groups declared in ground truth.
   Decisive for prose answers (schema facts, index usage), where there is no
   query to execute.

Cosine similarity to a generated reference answer is reported alongside as a
confidence signal, never as a verdict.

Usage (standalone, against a transcripts file written by the notebook):

    .venv/bin/python evaluation/evaluate.py [evaluation/transcripts.json]

Writes evaluation/results.json.
"""

import json
import os
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from dotenv import load_dotenv  # noqa: E402

load_dotenv(ROOT / ".env")

import psycopg  # noqa: E402
from psycopg.rows import dict_row  # noqa: E402

GT_PATH = Path(__file__).resolve().parent / "ground_truth.json"
RESULTS_PATH = Path(__file__).resolve().parent / "results.json"
TRANSCRIPTS_PATH = Path(__file__).resolve().parent / "transcripts.json"

STATEMENT_TIMEOUT_MS = 5000
COSINE_SIMILAR_MIN = 0.45  # reported as a signal, not used as a gate

_MODEL = None


# --------------------------------------------------------------------------- #
# ground truth + transcripts
# --------------------------------------------------------------------------- #
def load_ground_truth(path=GT_PATH):
    return json.loads(Path(path).read_text())


def load_transcripts(path=TRANSCRIPTS_PATH):
    return json.loads(Path(path).read_text())


# --------------------------------------------------------------------------- #
# signal 1: execute the agent's SQL and compare rows to ground truth
# --------------------------------------------------------------------------- #
_SQL_FENCE = re.compile(r"```sql(.*?)```", re.S | re.I)


def extract_sql_blocks(answer):
    if not isinstance(answer, str):
        return []
    return [b.strip() for b in _SQL_FENCE.findall(answer) if b.strip()]


def _connect():
    return psycopg.connect(
        host=os.getenv("POSTGRES_HOST", "localhost"),
        port=os.getenv("POSTGRES_PORT", "5432"),
        dbname=os.getenv("POSTGRES_DB", "schema_intelligence"),
        user=os.getenv("POSTGRES_USER", "schema_admin"),
        password=os.getenv("POSTGRES_PASSWORD", "change_me_local"),
        row_factory=dict_row,
    )


def run_sql_readonly(sql, timeout_ms=STATEMENT_TIMEOUT_MS):
    """Execute one read-only SELECT/WITH for evaluation purposes only.

    The agent never executes SQL; this is the grader, so it may run the generated
    query. Guards: single statement, SELECT/WITH only, read-only transaction,
    statement timeout.
    """
    statement = sql.strip().rstrip(";").strip()
    if not re.match(r"^\s*(select|with)\b", statement, re.I):
        return {"ok": False, "error": "not a SELECT/WITH statement"}
    if ";" in statement:
        return {"ok": False, "error": "multiple statements"}

    try:
        with _connect() as conn:
            conn.execute("SET default_transaction_read_only = on")
            conn.execute(f"SET statement_timeout = {int(timeout_ms)}")
            rows = [dict(r) for r in conn.execute(statement).fetchall()]
        return {"ok": True, "rows": rows}
    except psycopg.Error as exc:
        return {"ok": False, "error": str(exc).splitlines()[0][:200]}


def _norm(value):
    """Normalise a cell value for comparison.

    Timestamps are compared at date precision on both sides: rows read from the
    database are datetime objects, while ground truth read back from JSON is an
    ISO string like '2026-09-17T14:12:13.822596'. Without truncating both, a
    correct answer would fail on formatting alone.
    """
    from decimal import Decimal

    if isinstance(value, Decimal):
        return round(float(value), 2)
    if isinstance(value, float):
        return round(value, 2)
    if isinstance(value, str) and re.match(r"^\d{4}-\d{2}-\d{2}T", value):
        return value[:10]
    if hasattr(value, "isoformat"):
        return value.isoformat()[:10]
    return value


def _project(rows, keys):
    return [tuple(_norm(r.get(k)) for k in keys) for r in rows]


def _match_rows(actual, expected, keys, ordered=False):
    a, e = _project(actual, keys), _project(expected, keys)
    if not ordered:
        a, e = sorted(a), sorted(e)
    return a == e, {"actual": a[:20], "expected": e[:20]}


# Per-question result comparison. Only questions whose answer is a query get a
# SQL check; the rest fall through to the keyword check.
SQL_CHECKS = {
    "B1": lambda rows, gt: _match_rows(
        rows, gt["expected"]["rows"], ["order_id", "total_item_value"]
    ),
    "B2": lambda rows, gt: _match_rows(
        rows, gt["expected"]["rows"], ["customer_id", "full_name", "email"]
    ),
    "B3": lambda rows, gt: _match_rows(
        rows, gt["expected"]["rows"], ["order_id", "order_date"], ordered=True
    ),
    "C1": lambda rows, gt: _match_rows(
        rows, gt["expected"]["fixed_rows"], ["order_id", "amount"]
    ),
}


def check_sql(question_id, answer, gt):
    """Return the SQL signal for one answer, or None when no SQL is expected."""
    if question_id not in SQL_CHECKS:
        return None

    blocks = extract_sql_blocks(answer)
    if not blocks:
        return {"available": True, "passed": False, "reason": "no ```sql block in the answer"}

    attempts = []
    for block in blocks:
        result = run_sql_readonly(block)
        if not result["ok"]:
            attempts.append({"sql": block[:300], "error": result["error"]})
            continue
        matched, detail = SQL_CHECKS[question_id](result["rows"], gt)
        attempts.append({
            "sql": block[:300],
            "row_count": len(result["rows"]),
            "matched": matched,
            "detail": detail,
        })
        if matched:
            return {
                "available": True,
                "passed": True,
                "reason": "result rows match ground truth",
                "attempts": attempts,
            }

    return {
        "available": True,
        "passed": False,
        "reason": "no SQL block produced the expected rows",
        "attempts": attempts,
    }


# --------------------------------------------------------------------------- #
# signal 2: keyword groups
# --------------------------------------------------------------------------- #
def _any_of(alternatives, text):
    """True when any alternative phrase appears in the text."""
    return any(alt.lower() in text for alt in alternatives)


def check_keywords(answer, gt):
    """Keyword groups declared in ground_truth.json:
    keyword_groups = {"require": [[alt, ...], ...], "forbid": [[alt, ...], ...]}

    Each require entry is a list of acceptable phrasings; every entry must match.
    Each forbid entry is likewise a list; matching any is a violation.
    """
    groups = gt.get("keyword_groups") or {}
    # Strip markdown emphasis/backticks before matching: models write
    # "`amount` is defined as `NOT NULL`", which is the same claim as
    # "amount is defined as not null".
    text = re.sub(r"[`*]+", "", (answer or "").lower())
    missing = [" / ".join(a) for a in groups.get("require", []) if not _any_of(a, text)]
    violated = [" / ".join(a) for a in groups.get("forbid", []) if _any_of(a, text)]
    return {
        "available": bool(groups),
        "passed": not missing and not violated,
        "missing": missing,
        "violated": violated,
    }


# --------------------------------------------------------------------------- #
# signal 3: cosine similarity to the reference answer (reported, not decisive)
# --------------------------------------------------------------------------- #
def _model():
    global _MODEL
    if _MODEL is None:
        from sentence_transformers import SentenceTransformer

        _MODEL = SentenceTransformer("sentence-transformers/all-MiniLM-L6-v2")
    return _MODEL


def cosine_similarity(text_a, text_b):
    import numpy as np

    if not text_a or not text_b:
        return 0.0
    vecs = _model().encode([text_a, text_b], normalize_embeddings=True)
    return float(np.dot(vecs[0], vecs[1]))


# --------------------------------------------------------------------------- #
# combine
# --------------------------------------------------------------------------- #
def combine(sql_signal, keywords, cosine, answer=""):
    """SQL result evidence decides when available; otherwise the keyword groups do.

    Cosine is reported as a confidence flag and never changes the verdict.
    """
    flags = []
    answered = bool((answer or "").strip()) and "Step limit reached" not in (answer or "")

    if sql_signal and sql_signal.get("available"):
        verdict = "correct" if sql_signal["passed"] else "incorrect"
        basis = "sql result comparison"
    elif not answered:
        verdict = "incorrect"
        basis = "no answer"
    elif keywords.get("available"):
        verdict = "correct" if keywords["passed"] else "incorrect"
        basis = "keyword check"
    else:
        verdict = "ungraded"
        basis = "no decisive signal"

    if answered and not keywords.get("passed", True):
        if keywords.get("missing"):
            flags.append("missing: " + "; ".join(keywords["missing"])[:120])
        if keywords.get("violated"):
            flags.append("violates: " + "; ".join(keywords["violated"])[:120])
    if cosine < COSINE_SIMILAR_MIN:
        flags.append(f"low cosine similarity ({cosine:.2f})")

    return {"verdict": verdict, "basis": basis, "flags": flags}


def evaluate_one(name, entry, gt):
    answer = entry.get("answer") or ""
    sql_signal = check_sql(name, answer, gt)
    keywords = check_keywords(answer, gt)
    cosine = cosine_similarity(answer, gt.get("reference_answer", ""))
    combined = combine(sql_signal, keywords, cosine, answer)

    return {
        "question": name,
        "calls": len(entry.get("tools", [])),
        "answer": (answer or "")[:4000],
        "verdict": combined["verdict"],
        "basis": combined["basis"],
        "flags": combined["flags"],
        "cosine": round(cosine, 3),
        "sql_check": sql_signal,
        "keywords": keywords,
    }


def evaluate(transcripts, ground_truth=None):
    gt_all = (ground_truth or load_ground_truth())["questions"]
    return [
        evaluate_one(entry["id"], entry, gt_all[entry["id"]])
        for entry in transcripts
        if entry.get("id") in gt_all
    ]


# --------------------------------------------------------------------------- #
# reporting
# --------------------------------------------------------------------------- #
def evidence_summary(r):
    """One-line description of the decisive evidence for a result."""
    sc = r.get("sql_check")
    if sc and sc.get("available"):
        if sc.get("passed"):
            n = next((a.get("row_count") for a in sc.get("attempts", []) if a.get("matched")), None)
            return f"SQL rows match ({n})" if n is not None else "SQL rows match"
        attempts = sc.get("attempts") or []
        if attempts and "detail" in attempts[-1]:
            d = attempts[-1]["detail"]
            return f"SQL mismatch ({len(d['actual'])} vs {len(d['expected'])} rows)"
        if attempts and attempts[-1].get("error"):
            return "SQL error: " + attempts[-1]["error"][:45]
        return "SQL mismatch"

    answer = r.get("answer") or ""
    if not answer.strip():
        return "empty answer"
    if "Step limit reached" in answer:
        return "no answer (step limit)"
    kw = r.get("keywords") or {}
    if kw.get("passed"):
        return "keywords pass"
    if kw.get("violated"):
        return "keywords violate: " + kw["violated"][0][:38]
    if kw.get("missing"):
        return "keywords missing: " + kw["missing"][0][:38]
    return "\u2014"


def to_markdown(results):
    """Render the analysis table: one column per signal."""
    lines = [
        "| Q | calls | evidence | cos | verdict | summary |",
        "|---|---|---|---|---|---|",
    ]
    for r in results:
        summary = r.get("basis", "")
        if r.get("flags"):
            summary += " \u00b7 " + "; ".join(r["flags"])
        cells = [
            r["question"],
            str(r["calls"]),
            evidence_summary(r),
            f"{r['cosine']:.2f}",
            f"**{r['verdict']}**",
            summary,
        ]
        lines.append("| " + " | ".join(c.replace("|", "/").replace("\n", " ")[:120] for c in cells) + " |")
    return "\n".join(lines)


def summarise(results):
    counts = {}
    for r in results:
        counts[r["verdict"]] = counts.get(r["verdict"], 0) + 1
    return counts


def main(argv):
    path = Path(argv[1]) if len(argv) > 1 else TRANSCRIPTS_PATH
    results = evaluate(load_transcripts(path))
    RESULTS_PATH.write_text(json.dumps({
        "transcripts": str(path),
        "cosine_min": COSINE_SIMILAR_MIN,
        "summary": summarise(results),
        "results": results,
    }, indent=2, default=str))

    print(to_markdown(results))
    print("\nsummary:", summarise(results))
    print(f"wrote {RESULTS_PATH}")


if __name__ == "__main__":
    main(sys.argv)
