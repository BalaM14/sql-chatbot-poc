import json
import re
import sqlite3
from pathlib import Path
from typing import Union

import pandas as pd

from config import DB_PATH
from llm import groq_llm


def get_connection(db_path: Union[str, Path] = DB_PATH):
    db_path = Path(db_path)

    if not db_path.exists():
        raise FileNotFoundError(f"Database file not found: {db_path}")

    conn = sqlite3.connect(db_path)
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def clean_llm_output(text):
    text = text.strip()
    text = re.sub(r"```sql", "", text, flags=re.IGNORECASE)
    text = re.sub(r"```", "", text)
    return text.strip()


def get_database_schema(connection):
    cursor = connection.cursor()

    cursor.execute("""
        SELECT name
        FROM sqlite_master
        WHERE type = 'table'
        AND name NOT LIKE 'sqlite_%'
    """)

    tables = cursor.fetchall()
    schema_text = ""

    for table in tables:
        table_name = table[0]
        schema_text += f"\nTable: {table_name}\n"

        columns = cursor.execute(f"PRAGMA table_info({table_name})").fetchall()

        for column in columns:
            column_name = column[1]
            column_type = column[2]
            is_primary_key = column[5]

            pk_text = " PRIMARY KEY" if is_primary_key else ""
            schema_text += f"- {column_name} ({column_type}){pk_text}\n"

    return schema_text.strip()


def get_relationships(connection):
    cursor = connection.cursor()

    cursor.execute("""
        SELECT name
        FROM sqlite_master
        WHERE type = 'table'
        AND name NOT LIKE 'sqlite_%'
    """)

    tables = cursor.fetchall()
    relationship_text = ""

    for table in tables:
        table_name = table[0]

        foreign_keys = cursor.execute(
            f"PRAGMA foreign_key_list({table_name})"
        ).fetchall()

        for fk in foreign_keys:
            referenced_table = fk[2]
            from_column = fk[3]
            to_column = fk[4]

            relationship_text += (
                f"- {table_name}.{from_column} "
                f"references {referenced_table}.{to_column}\n"
            )

    if not relationship_text:
        return "No foreign-key relationships found in database metadata."

    return relationship_text.strip()


def build_intent_prompt(database_schema, relationship_schema):
    return f"""
You are a business analytics intent parser.

Convert the user's natural language question into structured analytics intent.

Rules:
1. Do not generate SQL.
2. Return only valid JSON.
3. Identify metrics, dimensions, filters, date logic, ranking, sorting, and limit.
4. If the user question is vague, infer the most likely business analytics meaning.
5. Use only concepts possible from the provided schema.
6. Do not invent tables or columns.

JSON format:
{{
  "rewritten_request": "...",
  "metrics": [],
  "dimensions": [],
  "filters": [],
  "date_logic": null,
  "ranking": null,
  "sort_order": null,
  "limit": null,
  "requires_aggregation": true,
  "notes": []
}}

Database Schema:
{database_schema}

Relationships:
{relationship_schema}
""".strip()


def parse_user_intent(user_request, database_schema, relationship_schema):
    intent_prompt = build_intent_prompt(database_schema, relationship_schema)

    response = groq_llm(
        system_prompt=intent_prompt,
        user_prompt=user_request,
        temperature=0.1,
        max_tokens=500,
    )

    response = clean_llm_output(response)

    try:
        return json.loads(response)
    except Exception:
        return {
            "rewritten_request": response,
            "metrics": [],
            "dimensions": [],
            "filters": [],
            "date_logic": None,
            "ranking": None,
            "sort_order": None,
            "limit": None,
            "requires_aggregation": None,
            "notes": ["LLM did not return valid JSON. Using rewritten text fallback."],
        }


def build_sql_generator_prompt(database_schema, relationship_schema):
    return f"""
You are an expert SQLite SQL query generator.

Your task:
Generate a correct SQLite SELECT query using the user's structured analytics intent.

Rules:
1. Return only the SQL query.
2. Do not explain.
3. Do not use markdown or code fences.
4. Generate only SELECT statements.
5. Use only tables and columns from the provided schema.
6. Use joins only through the provided relationships.
7. Never invent tables or columns.
8. If aggregation is used, every selected non-aggregated column must be in GROUP BY.
9. Do not return both an aggregated metric and the raw row-level version of the same metric unless explicitly requested.
10. Use aliases clearly.
11. Use LIMIT when the intent asks for top/highest/lowest/first/latest/specific number.
12. If the request cannot be answered from the schema, return:
    SELECT 'Question cannot be answered from available tables' AS message;

Database Schema:
{database_schema}

Relationships:
{relationship_schema}
""".strip()


def generate_sql(intent, database_schema, relationship_schema):
    sql_prompt = build_sql_generator_prompt(database_schema, relationship_schema)

    user_prompt = f"""
Structured analytics intent:
{json.dumps(intent, indent=2)}
""".strip()

    sql = groq_llm(
        system_prompt=sql_prompt,
        user_prompt=user_prompt,
        temperature=0.05,
        max_tokens=700,
    )

    return clean_llm_output(sql)


def build_sql_reviewer_prompt(database_schema, relationship_schema):
    return f"""
You are a SQLite SQL reviewer and corrector.

Your task:
Review the SQL query against the user intent, schema, and relationships.
If the SQL is correct, return the same SQL.
If the SQL has logical, aggregation, join, alias, or column issues, return corrected SQL.

Rules:
1. Return only SQL.
2. Do not explain.
3. Do not use markdown or code fences.
4. Only SELECT queries are allowed.
5. Check that all selected columns exist in the correct table aliases.
6. Check that joins follow the provided relationships.
7. Check GROUP BY correctness.
8. Avoid mixing row-level columns with aggregated metrics incorrectly.
9. Avoid duplicate/redundant columns with the same meaning.
10. Preserve the user's analytics intent.

Database Schema:
{database_schema}

Relationships:
{relationship_schema}
""".strip()


def review_sql(sql_query, intent, database_schema, relationship_schema):
    reviewer_prompt = build_sql_reviewer_prompt(database_schema, relationship_schema)

    user_prompt = f"""
Structured analytics intent:
{json.dumps(intent, indent=2)}

SQL query to review:
{sql_query}
""".strip()

    reviewed_sql = groq_llm(
        system_prompt=reviewer_prompt,
        user_prompt=user_prompt,
        temperature=0.05,
        max_tokens=700,
    )

    return clean_llm_output(reviewed_sql)


def validate_sql_query(sql_query):
    cleaned_query = sql_query.strip().lower()

    blocked_keywords = [
        "insert", "update", "delete", "drop", "alter",
        "create", "truncate", "replace", "attach",
        "detach", "pragma"
    ]

    if not cleaned_query.startswith("select") and not cleaned_query.startswith("with"):
        return False, "Only SELECT queries are allowed."

    for keyword in blocked_keywords:
        if re.search(rf"\b{keyword}\b", cleaned_query):
            return False, f"Blocked unsafe SQL keyword: {keyword}"

    return True, "SQL query is safe."


def execute_sql_query(connection, sql_query):
    try:
        df = pd.read_sql_query(sql_query, connection)
        return True, df

    except Exception as error:
        return False, str(error)


def repair_sql(sql_query, error_message, intent, database_schema, relationship_schema):
    repair_prompt = f"""
You are a SQLite SQL repair assistant.

The previous SQL failed during execution.
Generate a corrected SQLite SELECT query.

Rules:
1. Return only corrected SQL.
2. Do not explain.
3. Do not use markdown.
4. Use only the provided schema and relationships.
5. Fix column alias issues, missing joins, wrong tables, aggregation errors, and syntax errors.
6. Preserve the structured analytics intent.

Database Schema:
{database_schema}

Relationships:
{relationship_schema}
""".strip()

    user_prompt = f"""
Structured analytics intent:
{json.dumps(intent, indent=2)}

Failed SQL:
{sql_query}

Database error:
{error_message}
""".strip()

    repaired_sql = groq_llm(
        system_prompt=repair_prompt,
        user_prompt=user_prompt,
        temperature=0.05,
        max_tokens=700,
    )

    return clean_llm_output(repaired_sql)


def ask_sql_bot(user_request, db_path=DB_PATH, max_retries=3):
    conn = get_connection(db_path)

    try:
        database_schema = get_database_schema(conn)
        relationship_schema = get_relationships(conn)

        intent = parse_user_intent(
            user_request=user_request,
            database_schema=database_schema,
            relationship_schema=relationship_schema,
        )

        generated_sql = generate_sql(
            intent=intent,
            database_schema=database_schema,
            relationship_schema=relationship_schema,
        )

        generated_sql = review_sql(
            sql_query=generated_sql,
            intent=intent,
            database_schema=database_schema,
            relationship_schema=relationship_schema,
        )

        last_error = ""

        for attempt in range(max_retries):
            is_valid, validation_message = validate_sql_query(generated_sql)

            if not is_valid:
                return (
                    None,
                    generated_sql,
                    validation_message,
                    intent.get("rewritten_request", user_request),
                )

            success, result = execute_sql_query(conn, generated_sql)

            if success:
                return (
                    result,
                    generated_sql,
                    "success",
                    intent.get("rewritten_request", user_request),
                )

            last_error = result

            generated_sql = repair_sql(
                sql_query=generated_sql,
                error_message=last_error,
                intent=intent,
                database_schema=database_schema,
                relationship_schema=relationship_schema,
            )

        return (
            None,
            generated_sql,
            f"Failed after {max_retries} retries. Last error: {last_error}",
            intent.get("rewritten_request", user_request),
        )

    finally:
        conn.close()


if __name__ == "__main__":
    df, sql, status, rewritten_question = ask_sql_bot(
        "which product was ordered most & how many quantity it has sold"
    )

    print("Status:", status)
    print("\nInterpreted Question:\n", rewritten_question)
    print("\nGenerated SQL:\n", sql)

    if df is not None:
        print("\nResult:\n", df)