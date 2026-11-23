# Schema Intelligence: Naive Agent Version

A tool-calling agent that answers backend-developer questions about a PostgreSQL schema: it inspects tables, discovers foreign-key paths, retrieves business definitions from a small knowledge base, and validates generated SQL with `EXPLAIN` — without ever executing a query.

---

## 1. Problem Statement

Backend developers spend a large share of their time not on endpoints or business logic but on understanding the database underneath them: which table holds a value, how two tables are connected, whether a column can be null, which status values the database actually accepts, and why a query returns duplicate rows. That work is slow and error-prone precisely because the answers are scattered — some live in the schema, some in business documentation, some only in an `EXPLAIN` plan. Frontend developers pulled into backend tasks hit the same wall with less context.

A single LLM call cannot solve this. The model does not know this schema, and if it guesses it invents plausible columns and relationships — the most expensive kind of wrong answer, because it looks right. A static pipeline cannot solve it either: which information is needed depends on the question. One question needs only a column list; another needs a three-hop join path; another needs a business definition ("is a completed order the same as a paid order?"); another needs the generated SQL checked before anyone trusts it. The sequence of steps cannot be fixed in advance.

This agent is therefore a loop over four tools, each doing one thing:

| Tool | What it does |
|---|---|
| `get_table_schema` | Columns, types, nullability, primary/foreign keys and unique constraints for one or more tables, read from `information_schema` |
| `find_relationships` | Shortest foreign-key join path between two tables (BFS over the FK graph), with the join columns |
| `search_schema_docs` | Top-3 semantic matches from 18 Markdown documents covering business definitions, data semantics, business rules, conventions and query guidance (MiniLM-L6-v2 embeddings, in-memory cosine index) |
| `validate_sql` | Parses and plans a single `SELECT`/`WITH` via `EXPLAIN (FORMAT JSON)` on a read-only connection; rejects multi-statement SQL |

The model (Mango 1.5-9B via the Orion API) decides which tools to call and in what order, sees each result, and repeats until it answers or hits a five-step limit. Because every tool is read-only — schema metadata, embeddings, and `EXPLAIN` — the agent can look at the database without any ability to change or execute against it. That is what makes it safe to point at a real database, and it is the one thing a general coding assistant cannot do.

Deliberately absent: no agent framework, no ReAct prompting, no retries, no multi-agent coordination, no error recovery. When a tool is misused it raises and the run stops. The failures are the point.

---

## 2. Links

- **GitHub repository:** [github.com/dannykhant/schema-intelligence](https://github.com/dannykhant/schema-intelligence)
- **Notebook:** [`notebooks/naive_agent.ipynb`](https://github.com/dannykhant/schema-intelligence/blob/main/notebooks/naive_agent.ipynb)

---

## 3. Usage Summary

**Data source.** A PostgreSQL 17 database in Docker with six tables — `customers`, `orders`, `order_items`, `products`, `categories`, `payments` — seeded with 8 customers, 12 orders, 17 order items and 12 payments. Five foreign keys connect them. Eighteen Markdown documents form the RAG knowledge base.

**Setup.**

```bash
git clone https://github.com/dannykhant/schema-intelligence
cd schema-intelligence

# 1. Database
cp -n .env.example .env          # set POSTGRES_PORT if 5432 is taken
docker compose up -d             # runs database/schema.sql + seed_data.sql on first start

# 2. Python dependencies
uv sync                          # psycopg, numpy, sentence-transformers, openai, python-dotenv
uv sync --group dev              # notebook tooling
.venv/bin/python -m ipykernel install --user --name schema-intel --display-name "schema-intel (.venv)"

# 3. Credentials — add your Orion key to .env
# ORION_API_KEY=...
# ORION_BASE_URL=https://api.orion.cmkl.ai/v1
```

**Running.** Open `notebooks/naive_agent.ipynb`, select the `schema-intel (.venv)` kernel, and run all cells. Sections 1–10 build and demonstrate the components (connection, each tool, the RAG index, the tool schemas, the loop source); Section 11 runs the evaluation queries live against Mango; Section 12 grades them.

**Regenerating ground truth.** The evaluation compares answers to `evaluation/ground_truth.json`, which is generated from the live database — not written by hand. Because the seed data uses `CURRENT_TIMESTAMP`, recreating the database volume shifts every order date and invalidates the stored expectations:

```bash
.venv/bin/python evaluation/build_ground_truth.py
```

**How correctness is checked.** Grades are computed, not hand-written (`evaluation/evaluate.py`):

- If the answer contains SQL, that SQL is executed read-only and its rows are compared to the ground truth (order-sensitive where pagination order matters).
- Prose answers are checked against required/forbidden keyword groups declared in the ground truth.
- Cosine similarity to a reference answer is reported as a confidence signal but never decides a verdict.

---

## 4. Failure Log and Analysis

Five queries, ordered from one tool call to five, run live against Mango 1.5-9B. Two pass and three fail, with three distinct failure modes. Verdicts below were produced by the programmatic checks and then re-read by hand.

### Query 1 — Index usage (simple, 1 tool call) ✅

> *"Will this query use the index on order_date? Read the execution plan and tell me.*
> `SELECT order_id, order_date FROM orders WHERE order_date >= CURRENT_DATE - INTERVAL '30 days' ORDER BY order_date DESC LIMIT 20;`*"

**Tools called:** `validate_sql` (1)

**Correct?** Yes. It reported `Index Scan`, index `idx_orders_order_date`, scan direction `Backward`, and explained that the backward scan serves `ORDER BY order_date DESC` without a separate sort. All of that matches the actual plan.

**Observation.** The tool does not expose index metadata, so the only way to answer is to read the plan — and the agent did exactly that instead of guessing.

---

### Query 2 — Order-history totals (complex, 3 tools with dependencies) ✅

> *"Write a query for the order-history endpoint: each order with its total item value. An order can have multiple payments, and the totals must not be duplicated."*

**Tools called:** `get_table_schema` → `search_schema_docs` → `validate_sql` (3)

**Correct?** Yes — all 12 rows match the expected per-order totals.

**Observation.** This is the query the knowledge base was written for. The agent retrieved the join-multiplication guidance, then pre-aggregated `order_items` into a CTE *before* joining payments, so the item total is computed once per order and cannot be multiplied by payment rows. It also volunteered a `SUM(p.amount)` column nobody asked for, which is harmless but shows it drifting beyond the request.

---

### Query 3 — Constraints and allowed values (simple, 1 tool call) ❌

> *"What columns, types and constraints does the payments table have? I need to know whether amount is nullable and which payment_status values are allowed."*

**Tools called:** `get_table_schema` (1)

**Correct?** No. It got `amount IS NOT NULL` right, but never answered the second half of the question. It asserted that *"the database doesn't show a CHECK constraint that would limit `payment_status`"* — the database does have one (`payment_status IN ('paid','pending','failed','refunded')`); the tool simply does not return CHECK constraints. It then asked *"Would you like me to search the documentation for business rules about payment statuses?"*

**What went wrong.** Two things at once. First, it reported a limitation of its own tool as a property of the database — a claim a developer would act on by skipping validation in code. Second, it had `search_schema_docs` available, knew the documentation existed, and asked the user for permission to use it instead of calling it. One extra tool call would have produced the correct list of values.

---

### Query 4 — Delete-order dependencies (complex, 5 tools) ❌

> *"I'm writing a delete-order endpoint. Which tables and columns reference orders, and what should I handle before deleting an order row?"*

**Tools called:** `get_table_schema` → `find_relationships` → `find_relationships` → `search_schema_docs` → `search_schema_docs` (5)

**Correct?** No, and this is the most dangerous answer in the set. It correctly identified `order_items.order_id` and `payments.order_id` as the two references. It then recommended `ALTER TABLE ... DROP CONSTRAINT ... CASCADE` as a way to "cascade delete" — which drops the constraint and its dependants, it does not delete child rows — and `UPDATE order_items SET order_id = NULL`, on a column that is `NOT NULL`, so that statement cannot execute at all. It never stated the actual answer: both foreign keys are `ON DELETE NO ACTION`, so deleting an order with children is blocked and the children must be deleted or reassigned first.

**What went wrong.** The schema tool does not expose foreign-key delete rules, and the knowledge base has no document about delete semantics, so the searches returned nothing useful — the agent rephrased the same query twice and then filled the gap with invented DDL. The failure is a missing tool capability papered over by confident advice.

---

### Query 5 — Keyset pagination (2 tool calls) ❌

> *"Write a keyset-pagination query for the orders table: the next 5 orders after the cursor (order_date = 2026-10-07, order_id = 3), newest first, stable across pages."*

**Tools called:** `get_table_schema` → `validate_sql` (2)

**Correct?** No. It produced `WHERE order_date > '2026-10-07' OR (order_date = '2026-10-07' AND order_id > 3)` with `ORDER BY order_date DESC, order_id DESC`. Walking *backwards* through a descending list requires `<`; with `>` it returns the page of **newer** orders. Executed against the database: the agent's query returns `[12, 8, 4, 2, 10]`, the correct page is `[11, 6, 9]`.

**What went wrong.** The SQL is valid — `EXPLAIN` accepted it — and the agent explained its reasoning confidently: *"gets all rows strictly newer than the cursor… since we need desc order, the cursor must be excluded."* The comparison direction is inverted relative to the sort direction. This is the failure that validation cannot catch: a query can parse, plan, and still return the wrong rows. Only executing it against known data revealed the error.

---

### Cross-query analysis

**Three distinct failure modes, which is what makes the set worth logging:**

1. **Tool used, capability over-trusted** (Q3). The model treated "not returned by my tool" as "not present in the database", and declined to use the one tool that could have answered.
2. **Missing capability filled with invention** (Q4). With no tool able to answer the question, the model produced plausible, confident, and unexecutable DDL rather than saying it could not verify.
3. **Validated but semantically wrong** (Q5). `EXPLAIN` proves a query plans; it says nothing about whether it returns the right rows. This is the failure mode the system's own `validate_sql` tool is structurally unable to prevent.

**What the passing queries show.** When the question matches what the tools can see, the loop works well: one tool call for a plan-reading question, and a correct pre-aggregation for the join-multiplication trap that the knowledge base explicitly warns about.

**Limits of the automated grading.** The programmatic checks compare executed rows and required facts, so they catch wrong results and missing claims. They cannot judge the quality of *advice*: Q4's `DROP CONSTRAINT ... CASCADE` and `SET order_id = NULL` passed every keyword rule while being actively harmful. Advice quality was graded by reading the answers, and the markdown log is the record of that reading.

**What would fix these, in order of leverage:**

1. Extend `get_table_schema` to return CHECK constraints, indexes, and foreign-key delete rules. Three of the eight questions probe information the tools cannot see; two are rescued by other routes, Q4 is not.
2. Add a knowledge-base document on delete and cascade semantics so the RAG tool has something to retrieve for Q4.
3. In the system prompt, state that the agent may call `search_schema_docs` freely rather than asking permission — Q3 spent its budget offering to search instead of searching.
4. Nothing in the prompt or the tool descriptions can fix Q5. That one needs the generated SQL executed against known data — which is precisely what the evaluation harness now does, and what a production version of this tool would need to do before a developer trusts its output.

**Scope note.** The agent never executes SQL and has no DDL or DML tools; every result claim in this log was verified independently against the database. Step limit is five iterations. There is no error handling and no retry logic: a misused tool raises and the run stops.
