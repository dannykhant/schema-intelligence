"""Stage 4 tool definitions and dispatch (OpenAI function-calling format).

The four tools wrap the Stage 2 database functions and the Stage 3
knowledge-base retrieval. execute_tool never raises: bad names, bad arguments,
and backend errors are returned as JSON error objects so one bad call cannot
crash the agent loop.
"""

import json

from db_tools import find_relationships, get_table_schema, validate_sql

TABLE_ENUM = [
    "customers",
    "orders",
    "order_items",
    "products",
    "categories",
    "payments",
]


def build_tool_definitions():
    return [
        {
            "type": "function",
            "function": {
                "name": "get_table_schema",
                "description": (
                    "Get column names, data types, primary keys, foreign keys, "
                    "and unique constraints for one or more allowed tables. "
                    "Prefer a single call listing every table you need over "
                    "one call per table."
                ),
                "parameters": {
                    "type": "object",
                    "properties": {
                        "table_names": {
                            "type": "array",
                            "items": {"type": "string", "enum": TABLE_ENUM},
                            "minItems": 1,
                            "description": "Tables to inspect, e.g. [\"orders\", \"payments\"].",
                        }
                    },
                    "required": ["table_names"],
                    "additionalProperties": False,
                },
            },
        },
        {
            "type": "function",
            "function": {
                "name": "find_relationships",
                "description": (
                    "Find the shortest foreign-key join path between two allowed "
                    "tables, including intermediate tables and join columns."
                ),
                "parameters": {
                    "type": "object",
                    "properties": {
                        "source_table": {"type": "string", "enum": TABLE_ENUM},
                        "target_table": {"type": "string", "enum": TABLE_ENUM},
                    },
                    "required": ["source_table", "target_table"],
                    "additionalProperties": False,
                },
            },
        },
        {
            "type": "function",
            "function": {
                "name": "search_schema_docs",
                "description": (
                    "Search business definitions, data semantics, business rules, "
                    "database conventions, and SQL query guidance."
                ),
                "parameters": {
                    "type": "object",
                    "properties": {"query": {"type": "string"}},
                    "required": ["query"],
                    "additionalProperties": False,
                },
            },
        },
        {
            "type": "function",
            "function": {
                "name": "validate_sql",
                "description": (
                    "Validate a read-only SELECT or WITH query by asking PostgreSQL "
                    "to EXPLAIN it. Does not execute the query."
                ),
                "parameters": {
                    "type": "object",
                    "properties": {"sql": {"type": "string"}},
                    "required": ["sql"],
                    "additionalProperties": False,
                },
            },
        },
    ]


def execute_tool(name, arguments, knowledge_base):
    """Execute one tool call and return its result as a JSON string.

    No error handling: an unknown tool or bad arguments raise, and the agent
    loop stops. Failures are meant to be visible in the log, not papered over.
    """
    args = json.loads(arguments) if isinstance(arguments, str) else dict(arguments)

    if name == "get_table_schema":
        result = get_table_schema(**args)
    elif name == "find_relationships":
        result = find_relationships(**args)
    elif name == "search_schema_docs":
        result = knowledge_base.search_schema_docs(**args)
    elif name == "validate_sql":
        result = validate_sql(**args)
    else:
        raise ValueError(f"unknown tool: {name}")

    return json.dumps(result, default=str)
