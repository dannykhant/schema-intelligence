"""Stage 4 tool-calling agent (Mango 1.5 9B via the Orion API).

ORION INTEGRATION POINT — verify before running against the real API:
this module assumes the Orion API exposes an OpenAI-compatible
chat-completions endpoint with tool calling (per the starter template).
Confirm ORION_BASE_URL, ORION_API_KEY, ORION_MODEL, and the tool-call message
format against your Week 4 lab / API docs. If the real interface differs,
only get_client() and the message-append format below need to change; the
tool definitions, dispatch, and loop logic stay the same.

Deliberately NOT implemented (per plan): ReAct, multi-agent, automatic
SQL retry loops, persistent memory, SQL execution, DDL/DML tools.
"""

import os
import sys

from dotenv import load_dotenv
from openai import OpenAI

from rag import SchemaKnowledgeBase
from tools import build_tool_definitions, execute_tool

load_dotenv()

MODEL = os.getenv("ORION_MODEL", "Mango 1.5-9B")

SYSTEM_PROMPT = """You are a Schema Intelligence Agent that helps users
understand a PostgreSQL database and generate SQL queries.

You can inspect table schemas, discover relationships,
retrieve business documentation, and validate SQL.

Use database metadata to determine actual table structures
and foreign-key relationships. When you need several tables,
fetch them all in one get_table_schema call.

Use the knowledge base to understand business definitions,
data semantics, and business rules.

When generating SQL:
1. Use only tables and columns confirmed by schema inspection.
2. Follow the retrieved business definitions.
3. Discover relationships when necessary.
4. Generate SQL that answers the user's question.
5. Validate the SQL using the validate_sql tool.

Never execute generated SQL.
Never invent database columns or relationships.
Explain important assumptions when the question is ambiguous.

If validation fails, report the failure rather than
automatically attempting to repair the SQL."""


def get_client():
    """Build the Orion client. Isolated here so only this function changes
    if the real Orion interface differs from the OpenAI-compatible default."""
    api_key = os.getenv("ORION_API_KEY", "")
    base_url = os.getenv("ORION_BASE_URL", "")
    if not api_key or not base_url:
        raise RuntimeError(
            "ORION_API_KEY and ORION_BASE_URL must be set in .env "
            "(see .env.example and your Week 4 API docs)."
        )
    return OpenAI(api_key=api_key, base_url=base_url)


def run_agent(user_message, knowledge_base, client=None, max_steps=5):
    """Basic tool-calling loop. Stops on a final answer or max_steps."""
    if client is None:
        client = get_client()
    messages = [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": user_message},
    ]
    tools = build_tool_definitions()

    for _ in range(max_steps):
        response = client.chat.completions.create(
            model=MODEL,
            messages=messages,
            tools=tools,
            tool_choice="auto",
        )
        assistant_message = response.choices[0].message
        messages.append(assistant_message.model_dump(exclude_none=True))

        if not assistant_message.tool_calls:
            return assistant_message.content

        for tool_call in assistant_message.tool_calls:
            result = execute_tool(
                tool_call.function.name,
                tool_call.function.arguments,
                knowledge_base,
            )
            messages.append(
                {
                    "role": "tool",
                    "tool_call_id": tool_call.id,
                    "content": result,
                }
            )

    return "Step limit reached before the model returned a final answer."


if __name__ == "__main__":
    kb = SchemaKnowledgeBase()
    question = " ".join(sys.argv[1:]) or "What columns exist in the customers table?"
    print(run_agent(question, kb))
