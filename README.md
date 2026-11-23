# Schema Intelligence Agent

A tool-calling agent that answers backend questions about a PostgreSQL schema: it inspects
tables, traces foreign-key paths, retrieves business definitions from a small knowledge base,
and validates generated SQL with `EXPLAIN` — without ever executing a query.

Model: Mango 1.5-9B via the Orion API. No agent framework, no ReAct, no retries, no error
handling. The failures are the point.

**Submission write-up:** [`schema_intelligence_naive_agent.md`](schema_intelligence_naive_agent.md)

## Components

| Piece | What it is |
|---|---|
| `database/` | PostgreSQL 17 schema + seed: 6 tables, 5 FKs (8 customers, 12 orders, 17 order_items, 12 payments) |
| `knowledge_base/` | 18 Markdown docs in 5 categories (definitions, semantics, rules, conventions, query guidance) |
| `src/db_tools.py` | `get_table_schema` (batch columns/PK/FK/UNIQUE), `find_relationships` (BFS join path), `validate_sql` (`EXPLAIN`, read-only) |
| `src/rag.py` | MiniLM-L6-v2 embeddings, in-memory NumPy cosine index, top-3 retrieval |
| `src/tools.py` | 4 JSON tool schemas + dispatch |
| `src/agent.py` | `run_agent()` — `tool_choice: auto` loop, max 5 steps |
| `notebooks/naive_agent.ipynb` | End-to-end demo: tools, RAG, agent, 8 live queries, computed grading |
| `evaluation/` | Ground truth (generated), transcripts, grader |

Tools are read-only: schema metadata, embeddings, and `EXPLAIN`. The agent can look at the
database but cannot change or execute against it. Tools raise on misuse rather than returning
error objects.

## Quick start

```bash
cp -n .env.example .env          # set POSTGRES_PORT if 5432 is taken; add ORION_API_KEY + ORION_BASE_URL
docker compose up -d             # seeds the database on first start

uv sync && uv sync --group dev
.venv/bin/python -m ipykernel install --user --name schema-intel --display-name "schema-intel (.venv)"
```

Open `notebooks/naive_agent.ipynb` with the `schema-intel` kernel and run all cells.
Sections 1–10 build the components; 11 runs the queries live; 12 grades them.

Regenerate ground truth after re-seeding (seed dates are relative to container init):

```bash
.venv/bin/python evaluation/build_ground_truth.py
```

## Evaluation

8 backend-style questions in 3 sets: schema/constraints, writing queries, debugging/performance.
Grading is computed, not hand-written:

- **SQL answers** — the agent's own query is executed read-only and compared row-by-row to
  `evaluation/ground_truth.json`.
- **Prose answers** — required/forbidden keyword groups.
- **Cosine similarity** to a reference answer — reported as a flag, never decisive.

Latest run (Mango 1.5-9B): **5 correct / 3 incorrect**.

| Failure | Cause |
|---|---|
| A1 — constraints | Used only `get_table_schema`, asserted the DB has no CHECK constraint (it does), never searched the docs |
| A2 — delete-order | No tool exposes FK delete rules; invented `DROP CONSTRAINT ... CASCADE` and `SET order_id = NULL` on a `NOT NULL` column |
| B3 — pagination | `>` with `ORDER BY DESC` returns the newer page — valid SQL, wrong rows |

B3 is the instructive one: `EXPLAIN` accepted it, so only executing the query against known data
caught it. Details in the submission write-up.

## Limitations

- `validate_sql` proves a query plans, not that it is semantically correct.
- `get_table_schema` exposes no CHECK constraints, indexes, or FK delete rules — three questions
  probe information the tools cannot see.
- Runs are nondeterministic; the same question can take a different tool path next time.
- Single `schema_admin` role; a read-only role would be better hardening.
