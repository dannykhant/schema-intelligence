"""Stage 2 database inspection tools.

- get_table_schema: inspect columns, types, PK/FK/UNIQUE via information_schema.
- find_relationships: shortest FK join path via BFS over FK graph.
- validate_sql: read-only EXPLAIN validation for single SELECT/WITH, never executes.
"""

import os
import re
from collections import deque

import psycopg
from psycopg.rows import dict_row

ALLOWED_TABLES = {
    "customers", "orders", "order_items",
    "products", "categories", "payments"
}

_READONLY_SQL = re.compile(r"^\s*(select|with)\b", re.IGNORECASE | re.DOTALL)


def connect(read_only=False):
    conn = psycopg.connect(
        host=os.getenv("POSTGRES_HOST", "localhost"),
        port=os.getenv("POSTGRES_PORT", "5432"),
        dbname=os.getenv("POSTGRES_DB", "schema_intelligence"),
        user=os.getenv("POSTGRES_USER", "schema_admin"),
        password=os.getenv("POSTGRES_PASSWORD", "change_me_local"),
        row_factory=dict_row,
    )
    if read_only:
        conn.execute("SET default_transaction_read_only = on")
    return conn


def _fetch_one_table(conn, table_name: str):
    """Fetch columns + PK/FK/UNIQUE constraints for one table using an open connection."""
    columns = conn.execute(
        """
        SELECT column_name, data_type, is_nullable, column_default
        FROM information_schema.columns
        WHERE table_schema = 'public' AND table_name = %s
        ORDER BY ordinal_position
        """,
        (table_name,),
    ).fetchall()

    constraints = conn.execute(
        """
        SELECT tc.constraint_type, kcu.column_name,
               ccu.table_name AS foreign_table_name,
               ccu.column_name AS foreign_column_name
        FROM information_schema.table_constraints tc
        JOIN information_schema.key_column_usage kcu
          ON tc.constraint_name = kcu.constraint_name
         AND tc.table_schema = kcu.table_schema
        LEFT JOIN information_schema.constraint_column_usage ccu
          ON ccu.constraint_name = tc.constraint_name
         AND ccu.table_schema = tc.table_schema
        WHERE tc.table_schema = 'public'
          AND tc.table_name = %s
          AND tc.constraint_type IN ('PRIMARY KEY', 'FOREIGN KEY', 'UNIQUE')
        ORDER BY tc.constraint_type, kcu.ordinal_position
        """,
        (table_name,),
    ).fetchall()
    return {"table": table_name, "columns": columns, "constraints": constraints}


def get_table_schema(table_names=None, table_name=None):
    """Return columns + PK/FK/UNIQUE constraints for one or more allowed tables.

    Batch form: get_table_schema(["orders", "payments"]) ->
        {"tables": {"orders": {...}, "payments": {...}}}.
    A single string (or legacy table_name=...) keeps the old single-table shape:
    {"table": ..., "columns": ..., "constraints": ...}.
    """
    if table_name is not None and table_names is None:
        table_names = table_name
    single = isinstance(table_names, str)
    names = [table_names] if single else list(table_names)
    unknown = [n for n in names if n not in ALLOWED_TABLES]
    if unknown:
        raise ValueError(f"unknown table(s): {unknown}; allowed: {sorted(ALLOWED_TABLES)}")

    with connect(read_only=True) as conn:
        tables = {n: _fetch_one_table(conn, n) for n in dict.fromkeys(names)}

    if single:
        return tables[names[0]]
    return {"tables": tables}


def _foreign_key_graph():
    with connect(read_only=True) as conn:
        rows = conn.execute(
            """
            SELECT
                tc.table_name AS source_table,
                kcu.column_name AS source_column,
                ccu.table_name AS target_table,
                ccu.column_name AS target_column
            FROM information_schema.table_constraints tc
            JOIN information_schema.key_column_usage kcu
              ON tc.constraint_name = kcu.constraint_name
             AND tc.table_schema = kcu.table_schema
            JOIN information_schema.constraint_column_usage ccu
              ON ccu.constraint_name = tc.constraint_name
             AND ccu.table_schema = tc.table_schema
            WHERE tc.constraint_type = 'FOREIGN KEY'
              AND tc.table_schema = 'public'
            """
        ).fetchall()
    return rows


def find_relationships(source_table: str, target_table: str):
    """Find shortest FK join path between two allowed tables (BFS, undirected)."""
    for table in (source_table, target_table):
        if table not in ALLOWED_TABLES:
            raise ValueError(f"unknown table: {table}; allowed: {sorted(ALLOWED_TABLES)}")
    if source_table == target_table:
        return {"source": source_table, "target": target_table, "path": [source_table]}

    fk_rows = _foreign_key_graph()

    graph = {table: [] for table in ALLOWED_TABLES}
    for fk in fk_rows:
        graph[fk["source_table"]].append({
            "table": fk["target_table"],
            "from_column": fk["source_column"],
            "to_column": fk["target_column"],
        })
        graph[fk["target_table"]].append({
            "table": fk["source_table"],
            "from_column": fk["target_column"],
            "to_column": fk["source_column"],
        })

    queue = deque([(source_table, [source_table], [])])
    visited = {source_table}
    while queue:
        current, path, joins = queue.popleft()
        for edge in graph[current]:
            nxt = edge["table"]
            if nxt in visited:
                continue
            next_path = path + [nxt]
            next_joins = joins + [{
                "left_table": current,
                "left_column": edge["from_column"],
                "right_table": nxt,
                "right_column": edge["to_column"],
            }]
            if nxt == target_table:
                return {
                    "source": source_table,
                    "target": target_table,
                    "path": next_path,
                    "joins": next_joins,
                }
            visited.add(nxt)
            queue.append((nxt, next_path, next_joins))

    return {"source": source_table, "target": target_table, "path": None,
            "message": "No foreign-key path found."}


def validate_sql(sql: str):
    """Validate a single read-only SELECT/WITH via EXPLAIN. Never executes."""
    if not sql or not sql.strip():
        return {"valid": False, "message": "Empty SQL statement."}

    statement = sql.strip()
    if statement.endswith(";"):
        statement = statement[:-1].strip()
    if not statement:
        return {"valid": False, "message": "Empty SQL statement."}
    if ";" in statement:
        return {"valid": False, "message": "Multiple SQL statements are not allowed."}
    if not _READONLY_SQL.match(statement):
        return {"valid": False, "message": "Only SELECT or WITH queries are allowed."}

    # Reporting an invalid query IS this tool's job, so the planner error is
    # returned as a result rather than raised.
    try:
        with connect(read_only=True) as conn:
            result = conn.execute("EXPLAIN (FORMAT JSON) " + statement).fetchone()
    except psycopg.Error as exc:
        return {"valid": False, "message": f"SQL validation failed: {exc}"}

    return {"valid": True,
            "message": "PostgreSQL successfully parsed and planned the query.",
            "plan": result}
