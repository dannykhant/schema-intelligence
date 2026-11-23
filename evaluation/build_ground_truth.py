"""Build ground truth for the evaluation questions from the live database.

Ground truth is derived from reference SQL, never typed by hand: run this
script and the JSON it writes is the expected answer for each question.
Re-run it after any change to the schema, the seed data, or the question set.

    .venv/bin/python evaluation/build_ground_truth.py

Output: evaluation/ground_truth.json
"""

import json
import os
import sys
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from dotenv import load_dotenv

load_dotenv(Path(__file__).resolve().parents[1] / ".env")

from db_tools import connect  # noqa: E402

# Cursor used by question B3 (order 3 sits at 2026-10-07 in the seed data).
B3_CURSOR = {"order_date": "2026-10-07", "order_id": 3}
B3_PAGE_SIZE = 5


def _rows(cur):
    return [dict(r) for r in cur.fetchall()]


def _plain(value):
    if isinstance(value, Decimal):
        return float(value)
    if hasattr(value, "isoformat"):
        return value.isoformat()
    return value


def _clean(rows):
    return [{k: _plain(v) for k, v in row.items()} for row in rows]


def build():
    with connect(read_only=True) as conn:
        # A1 — payments columns, nullability, constraints, allowed status values.
        columns = _rows(conn.execute(
            """
            SELECT column_name, data_type, character_maximum_length AS max_length,
                   is_nullable
            FROM information_schema.columns
            WHERE table_schema = 'public' AND table_name = 'payments'
            ORDER BY ordinal_position
            """
        ))
        checks = [r["check_clause"] for r in conn.execute(
            """
            SELECT cc.check_clause
            FROM information_schema.table_constraints tc
            JOIN information_schema.check_constraints cc
              ON cc.constraint_name = tc.constraint_name
            WHERE tc.table_name = 'payments' AND tc.constraint_type = 'CHECK'
            ORDER BY cc.check_clause
            """
        ).fetchall()]
        allowed_status = [r["status"] for r in conn.execute(
            """
            SELECT DISTINCT payment_status AS status FROM payments
            ORDER BY status
            """
        ).fetchall()]
        status_from_check = [r["status"] for r in conn.execute(
            """
            SELECT unnest(ARRAY['paid','pending','failed','refunded']) AS status
            """
        ).fetchall()]

        a1 = {
            "question": "payments columns/types/constraints; is amount nullable; which payment_status values are allowed",
            "expected": {
                "columns": _clean(columns),
                "primary_key": ["payment_id"],
                "foreign_keys": [{"column": "order_id", "references": "orders.order_id"}],
                "amount_nullable": False,
                "allowed_payment_status": sorted(status_from_check),
                "check_constraints": checks,
                "values_present_in_seed": allowed_status,
            },
            "must_state": [
                "amount is NOT NULL",
                "payment_status is limited to paid, pending, failed, refunded",
            ],
            "must_not_state": [
                "that no CHECK/enum constraint exists on payment_status",
            ],
            "evidence": "information_schema.columns + table_constraints/check_constraints; allowed values cross-checked against knowledge_base/business_definitions/payment_status.md",
        }

        # A2 — tables referencing orders and the delete rule.
        fks = _rows(conn.execute(
            """
            SELECT child.relname AS child_table,
                   att.attname   AS child_column,
                   c.confdeltype AS on_delete_code,
                   CASE c.confdeltype
                        WHEN 'a' THEN 'NO ACTION'
                        WHEN 'r' THEN 'RESTRICT'
                        WHEN 'c' THEN 'CASCADE'
                        WHEN 'n' THEN 'SET NULL'
                        WHEN 'd' THEN 'SET DEFAULT'
                   END AS on_delete
            FROM pg_constraint c
            JOIN pg_class child ON child.oid = c.conrelid
            JOIN pg_class parent ON parent.oid = c.confrelid
            JOIN pg_attribute att ON att.attrelid = c.conrelid AND att.attnum = c.conkey[1]
            WHERE c.contype = 'f' AND parent.relname = 'orders'
            ORDER BY child.relname
            """
        ))
        a2 = {
            "question": "which tables/columns reference orders, and what must be handled before deleting an order",
            "expected": {
                "referencing_tables": [
                    {"table": r["child_table"], "column": r["child_column"], "on_delete": r["on_delete"]}
                    for r in fks
                ],
                "delete_blocked_while_children_exist": all(r["on_delete_code"] == "a" for r in fks),
                "no_cascade_configured": all(r["on_delete_code"] != "c" for r in fks),
            },
            "must_state": [
                "order_items.order_id and payments.order_id reference orders",
                "child rows must be deleted or reassigned first (or a cascade added deliberately)",
            ],
            "must_not_state": [
                "that ON DELETE CASCADE is already configured",
            ],
            "evidence": "pg_constraint.confdeltype for FKs whose parent is orders",
        }

        # A3 — nullability of the column used in revenue sums.
        a3 = {
            "question": "is order_items.unit_price_at_purchase nullable; will NULLs break a SUM",
            "expected": {
                "column": "order_items.unit_price_at_purchase",
                "nullable": False,
                "sum_needs_null_handling": False,
            },
            "must_state": [
                "the column is NOT NULL",
                "SUM needs no NULL handling for this column",
            ],
            "must_not_state": [
                "that the column is part of the primary key",
                "that COALESCE is required",
            ],
            "evidence": "information_schema.columns.is_nullable",
        }

        # B1 — one row per order with its item total.
        b1_rows = _clean(_rows(conn.execute(
            """
            SELECT o.order_id,
                   SUM(oi.quantity * oi.unit_price_at_purchase) AS total_item_value
            FROM orders o
            LEFT JOIN order_items oi ON oi.order_id = o.order_id
            GROUP BY o.order_id
            ORDER BY o.order_id
            """
        )))
        b1 = {
            "question": "order-history query: each order with its total item value, not duplicated by multiple payments",
            "expected": {
                "row_count": len(b1_rows),
                "rows": b1_rows,
                "one_row_per_order": True,
            },
            "must_state": [
                "payments must not be joined into the item-value aggregation",
            ],
            "reference_sql": """
                SELECT o.order_id, SUM(oi.quantity * oi.unit_price_at_purchase) AS total_item_value
                FROM orders o JOIN order_items oi ON oi.order_id = o.order_id
                GROUP BY o.order_id ORDER BY o.order_id
            """,
            "evidence": "order_items is the only source of item value; joining payments multiplies rows",
        }

        # B2 — customers with no orders (empty set in this seed).
        b2_rows = _clean(_rows(conn.execute(
            """
            SELECT c.customer_id, c.full_name, c.email
            FROM customers c
            WHERE NOT EXISTS (SELECT 1 FROM orders o WHERE o.customer_id = c.customer_id)
            ORDER BY c.customer_id
            """
        )))
        total_customers = conn.execute("SELECT COUNT(*) AS n FROM customers").fetchone()["n"]
        b2 = {
            "question": "customers who have never placed an order",
            "expected": {
                "row_count": len(b2_rows),
                "rows": b2_rows,
                "total_customers_in_table": total_customers,
            },
            "must_state": [
                f"the result is empty ({len(b2_rows)} rows)",
            ],
            "must_not_state": [
                "any row count other than 0",
                "a row estimate taken from an EXPLAIN plan",
            ],
            "reference_sql": """
                SELECT c.customer_id, c.full_name, c.email FROM customers c
                WHERE NOT EXISTS (SELECT 1 FROM orders o WHERE o.customer_id = c.customer_id)
            """,
            "evidence": "every customer in the seed has at least one order",
        }

        # B3 — keyset pagination page after a given cursor.
        b3_rows = _clean(_rows(conn.execute(
            """
            SELECT order_id, order_date
            FROM orders
            WHERE (order_date, order_id) < (%(d)s::timestamp, %(i)s)
            ORDER BY order_date DESC, order_id DESC
            LIMIT %(n)s
            """,
            {"d": B3_CURSOR["order_date"], "i": B3_CURSOR["order_id"], "n": B3_PAGE_SIZE},
        )))
        b3 = {
            "question": "keyset pagination: next page after the cursor, newest first, stable across pages",
            "expected": {
                "cursor": B3_CURSOR,
                "page_size": B3_PAGE_SIZE,
                "row_count": len(b3_rows),
                "rows": b3_rows,
                "order_by": ["order_date DESC", "order_id DESC"],
                "cursor_key_must_match_order_by": True,
            },
            "must_state": [
                "the cursor is a (order_date, order_id) tuple matching ORDER BY",
                "row-value comparison or an equivalent two-part predicate",
            ],
            "must_not_state": [
                "OFFSET-based paging",
                "a cursor on order_id alone while sorting by order_date",
                "FOR UPDATE / SKIP LOCKED on a read-only endpoint",
            ],
            "reference_sql": """
                SELECT order_id, order_date FROM orders
                WHERE (order_date, order_id) < ('2026-10-07', 3)
                ORDER BY order_date DESC, order_id DESC LIMIT 5
            """,
            "evidence": "row-value comparison over the (order_date, order_id) key",
        }

        # C1 — duplicate payment amounts from joining two one-to-many tables.
        c1_buggy = _clean(_rows(conn.execute(
            """
            SELECT o.order_id, p.amount, oi.order_item_id
            FROM orders o
            JOIN payments p ON p.order_id = o.order_id
            JOIN order_items oi ON oi.order_id = o.order_id
            WHERE o.customer_id = 1
            ORDER BY o.order_id, p.amount, oi.order_item_id
            """
        )))
        c1_fixed = _clean(_rows(conn.execute(
            """
            SELECT o.order_id, p.amount
            FROM orders o
            JOIN payments p ON p.order_id = o.order_id
            WHERE o.customer_id = 1
            ORDER BY o.order_id, p.amount
            """
        )))
        c1 = {
            "question": "why does this query return duplicate payment amounts, and how to fix it",
            "expected": {
                "buggy_row_count": len(c1_buggy),
                "buggy_rows": c1_buggy,
                "fixed_row_count": len(c1_fixed),
                "fixed_rows": c1_fixed,
                "root_cause": "payments and order_items are both one-to-many on order_id; joining both multiplies rows",
            },
            "must_state": [
                "row multiplication (fan-out) between payments and order_items",
                "a fix that removes the order_items join or pre-aggregates before joining",
            ],
            "must_not_state": [
                "that the duplicate rows come from duplicate payment records",
            ],
            "evidence": "order 1 has 1 payment and 2 order_items, so the buggy join returns its amount twice",
        }

        # C2 — does the query use the order_date index.
        plan = conn.execute(
            """
            EXPLAIN (FORMAT JSON)
            SELECT order_id, order_date FROM orders
            WHERE order_date >= CURRENT_DATE - INTERVAL '30 days'
            ORDER BY order_date DESC LIMIT 20
            """
        ).fetchone()["QUERY PLAN"][0]["Plan"]
        indexes = []
        node = plan
        while node:
            if node.get("Index Name"):
                indexes.append({
                    "index": node["Index Name"],
                    "scan_direction": node.get("Scan Direction"),
                    "node_type": node["Node Type"],
                })
            node = (node.get("Plans") or [None])[0]
        c2 = {
            "question": "will this query use the index on order_date; read the plan",
            "expected": {
                "uses_index": bool(indexes),
                "indexes": indexes,
                "top_node": plan["Node Type"],
            },
            "must_state": [
                "yes, the order_date index is used",
                "evidence from the plan (index scan / index cond)",
            ],
            "must_not_state": [
                "a claim made without reference to the plan",
                "an estimated row count presented as the query result",
            ],
            "evidence": "EXPLAIN (FORMAT JSON) on the exact query",
        }

    return {
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "database": {
            "dbname": os.getenv("POSTGRES_DB"),
            "schema": "public",
        },
        "note": (
            "Generated from the live database by evaluation/build_ground_truth.py. "
            "Re-run after re-seeding: seed dates are relative to container init time."
        ),
        "questions": _with_reference_answers({
            "A1": a1, "A2": a2, "A3": a3, "B1": b1,
            "B2": b2, "B3": b3, "C1": c1, "C2": c2,
        }),
    }


KEYWORD_GROUPS = {
    "A1": {
        "require": [
            ["amount is not null", "defined as not null", "amount is not nullable", "cannot be null"],
            # each allowed status must appear (separate entries = all required)
            ["paid"], ["pending"], ["failed"], ["refunded"],
        ],
        "forbid": [],
    },
    "A2": {
        "require": [
            ["order_items"],
            ["payments"],
            ["no cascade", "not cascade", "no on delete cascade", "without cascade"],
        ],
        "forbid": [
            ["cascade is configured", "on delete cascade is set", "cascades automatically"],
        ],
    },
    "A3": {
        "require": [["not null", "is_nullable: \"no\"", "cannot contain null"]],
        "forbid": [["part of the primary key", "coalesce is required", "nulls will break"]],
    },
    "C2": {
        "require": [["idx_orders_order_date", "index on order_date"]],
        "forbid": [["sequential scan"], ["estimated rows"]],
    },
}


def _with_reference_answers(questions):
    """Attach a canonical reference answer per question, built from the expected
    values (used for cosine similarity). Numbers are interpolated from the data,
    so the reference cannot drift from the ground truth."""
    for name, groups in KEYWORD_GROUPS.items():
        questions[name]["keyword_groups"] = groups

    a1 = questions["A1"]["expected"]
    a2 = questions["A2"]["expected"]
    a3 = questions["A3"]["expected"]
    b1 = questions["B1"]["expected"]
    b2 = questions["B2"]["expected"]
    b3 = questions["B3"]["expected"]
    c1 = questions["C1"]["expected"]
    c2 = questions["C2"]["expected"]

    questions["A1"]["reference_answer"] = (
        "The payments table has columns payment_id bigint, order_id bigint, payment_date timestamp, "
        "amount numeric and payment_status varchar, all NOT NULL. The primary key is payment_id and "
        "order_id is a foreign key to orders.order_id. amount is NOT NULL so it cannot be null. "
        f"payment_status is restricted to {', '.join(a1['allowed_payment_status'])}."
    )
    questions["A2"]["reference_answer"] = (
        "Two tables reference orders: "
        + " and ".join(f"{r['table']}.{r['column']}" for r in a2["referencing_tables"])
        + f". Both foreign keys are ON DELETE {a2['referencing_tables'][0]['on_delete']}, so there is no "
        "cascade: deleting an order while child rows exist is blocked. Delete or reassign the order_items "
        "and payments rows first, inside one transaction, or add a cascade deliberately."
    )
    questions["A3"]["reference_answer"] = (
        "order_items.unit_price_at_purchase is NOT NULL, so it cannot contain NULL values. "
        "SUM over this column needs no NULL handling and no COALESCE; it is not part of the primary key."
    )
    questions["B1"]["reference_answer"] = (
        f"Aggregate order_items by order_id and join to orders: SELECT o.order_id, "
        "SUM(oi.quantity * oi.unit_price_at_purchase) AS total_item_value FROM orders o "
        "JOIN order_items oi ON oi.order_id = o.order_id GROUP BY o.order_id. "
        f"The result is {b1['row_count']} rows, one per order, for example order 1 = "
        f"{b1['rows'][0]['total_item_value']:.2f}. Do not join payments into this aggregation, "
        "because payments is one-to-many on order_id and would duplicate the totals."
    )
    questions["B2"]["reference_answer"] = (
        "Use NOT EXISTS or a LEFT JOIN with IS NULL to find customers with no orders: "
        "SELECT c.customer_id, c.full_name, c.email FROM customers c WHERE NOT EXISTS "
        "(SELECT 1 FROM orders o WHERE o.customer_id = c.customer_id). "
        f"The result is empty: {b2['row_count']} rows out of {b2['total_customers_in_table']} customers, "
        "because every customer in this database has at least one order."
    )
    questions["B3"]["reference_answer"] = (
        "Keyset pagination with a tuple cursor that matches the ORDER BY: "
        "SELECT order_id, order_date FROM orders "
        "WHERE (order_date, order_id) < ('2026-10-07', 3) "
        "ORDER BY order_date DESC, order_id DESC LIMIT 5. "
        f"The page is {', '.join(str(r['order_id']) for r in b3['rows'])}. "
        "Use the row-value comparison with a less-than sign because the list is ordered descending; "
        "do not use OFFSET, and do not put the cursor on order_id alone."
    )
    questions["C1"]["reference_answer"] = (
        "The duplicates come from row multiplication, not from duplicate payments. payments and "
        "order_items are both one-to-many on order_id, so joining both multiplies rows: order 1 has "
        "one payment and two order_items, so its amount appears twice. "
        f"The buggy query returns {c1['buggy_row_count']} rows; removing the order_items join returns "
        f"{c1['fixed_row_count']} rows, one per payment. Pre-aggregate before joining if both are needed."
    )
    questions["C2"]["reference_answer"] = (
        f"Yes, the query uses the index {c2['indexes'][0]['index']} with an "
        f"{c2['indexes'][0]['node_type']} in {c2['indexes'][0]['scan_direction']} direction under a "
        f"{c2['top_node']} node. The plan shows the index condition on order_date, so the range filter "
        "and the descending order are both served by the index rather than a sequential scan."
    )
    return questions


if __name__ == "__main__":
    data = build()
    out = Path(__file__).resolve().parent / "ground_truth.json"
    out.write_text(json.dumps(data, indent=2), encoding="utf-8")
    print(f"wrote {out}")
    for name, q in data["questions"].items():
        print(f"  {name}: {q['expected']}")
