"""
General ERP Sales AI Agent Orchestration Module.

Orchestrates the general-purpose natural-language querying pipeline for PostgreSQL ERP Sales:
  User Question
        ↓
  LLM Query Parser (parse_sales_query)
        ↓
  Entity Resolver (resolve_entity)
        ↓
  Query Planner (build_query_plan / validate_query_plan)
        ↓
  SQL Generator (generate_sql)
        ↓
  SQL Validator (validate_sql)
        ↓
  DB Executor (execute_validated_query)
        ↓
  Sales Response Generator (generate_sales_response)
        ↓
  Structured Response Payload
"""

import os
import sys
from typing import Dict, Any, Optional

# Ensure sys.stdout handles UTF-8 formatting on Windows consoles
if hasattr(sys.stdout, "reconfigure"):
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass

from scripts.llm_query_parser import parse_sales_query
from scripts.entity_resolver import resolve_entity
from scripts.schema_context import get_sales_schema_context
from scripts.query_planner import build_query_plan, validate_query_plan
from scripts.sql_generator import generate_sql
from scripts.sql_validator import validate_sql
from scripts.db_executor import execute_validated_query
from scripts.sales_response_generator import generate_sales_response


def run_general_agent(question: str) -> Dict[str, Any]:
    """
    Main entry point for the General ERP Sales AI Agent.
    Orchestrates natural language parsing, entity resolution, declarative query planning,
    SQL generation, security validation, PostgreSQL execution, and response synthesis.
    """
    if not isinstance(question, str) or not question.strip():
        return {
            "success": False,
            "question": str(question),
            "answer": "Please ask a valid sales question.",
            "language": "english",
            "query_plan": None,
            "sql": None,
            "result": None,
            "error": "Empty or invalid question string."
        }

    clean_question = question.strip()

    # 1. LLM Query Parsing
    parsed_q = parse_sales_query(clean_question)
    if not isinstance(parsed_q, dict) or not parsed_q.get("success"):
        err_msg = parsed_q.get("error") if isinstance(parsed_q, dict) else "Failed to parse question."
        return {
            "success": False,
            "question": clean_question,
            "answer": f"Unable to process request: {err_msg}",
            "language": "english",
            "query_plan": None,
            "sql": None,
            "result": None,
            "error": err_msg
        }

    # 2. Entity Resolution (if dimension/value present)
    resolved_q = parsed_q
    if parsed_q.get("dimension") and parsed_q.get("value") is not None:
        entity_res = resolve_entity(parsed_q)
        if not entity_res.get("success"):
            err_msg = entity_res.get("error") or "Entity resolution failed."
            return {
                "success": False,
                "question": clean_question,
                "answer": f"Unable to process request: {err_msg}",
                "language": "english",
                "query_plan": None,
                "sql": None,
                "result": None,
                "error": err_msg
            }
        resolved_q = entity_res

    # 3. Query Planning
    plan = build_query_plan(resolved_q)
    if plan.get("status") != "valid":
        reason = plan.get("reason") or "Unsupported query plan."
        return {
            "success": False,
            "question": clean_question,
            "answer": f"Unable to process request: {reason}",
            "language": "english",
            "query_plan": plan,
            "sql": None,
            "result": None,
            "error": reason
        }

    # 4. SQL Generation
    try:
        sql_info = generate_sql(plan)
    except Exception as e:
        return {
            "success": False,
            "question": clean_question,
            "answer": f"Unable to generate SQL: {str(e)}",
            "language": "english",
            "query_plan": plan,
            "sql": None,
            "result": None,
            "error": str(e)
        }

    sql_str = sql_info.get("sql")
    sql_params = sql_info.get("params", [])

    # 5. SQL Security & Syntax Validation
    val_info = validate_sql(sql_str, sql_params)
    if not val_info.get("valid"):
        val_errors = "; ".join(val_info.get("errors", ["SQL validation failed."]))
        return {
            "success": False,
            "question": clean_question,
            "answer": f"SQL security validation failed: {val_errors}",
            "language": "english",
            "query_plan": plan,
            "sql": sql_str,
            "result": None,
            "error": val_errors
        }

    # 6. Safe Database Execution
    db_res = execute_validated_query(sql_str, sql_params)
    if not db_res.get("success"):
        db_err = db_res.get("error", "Database execution failed.")
        return {
            "success": False,
            "question": clean_question,
            "answer": f"Database execution error: {db_err}",
            "language": "english",
            "query_plan": plan,
            "sql": sql_str,
            "result": None,
            "error": db_err
        }

    # 7. Response Synthesis & Result Formatting
    row_count = db_res.get("row_count", 0)
    rows = db_res.get("rows", [])
    columns = db_res.get("columns", [])

    # Extract overall total amount if available
    total_amount = 0.0
    if rows and len(rows) > 0:
        first_row = rows[0]
        if "total_amount" in first_row and first_row["total_amount"] is not None:
            total_amount = float(first_row["total_amount"])
        elif "invoice_total_amount" in first_row and first_row["invoice_total_amount"] is not None:
            total_amount = sum(float(r.get("invoice_total_amount", 0.0)) for r in rows if r.get("invoice_total_amount") is not None)

    # Format result payload compatible with sales_response_generator
    dim = resolved_q.get("dimension") or "product"
    val = resolved_q.get("value")
    orig_val = resolved_q.get("original_value", val)

    res_payload = {
        "exists": row_count > 0,
        "number_of_invoices": row_count,
        "number_of_accounting_rows": row_count,
        "total_amount": total_amount,
        "product_code": val if dim == "product" else None,
        "product_name": orig_val if dim == "product" else None,
        "customer_code": val if dim == "customer" else None,
        "customer_name": orig_val if dim == "customer" else None,
        "series_code": val if dim == "series" else None,
        "co_year": val if dim == "financial_year" else None,
        "ac_code": val if dim == "gl_account" else None,
        "ev": val if dim == "ev" else None,
        "invoices": rows,
        "rows": rows,
        "columns": columns
    }

    # Generate user-facing natural language answer
    answer_text = generate_sales_response({
        "success": True,
        "parsed_query": resolved_q,
        "result": res_payload
    })

    return {
        "success": True,
        "question": clean_question,
        "answer": answer_text,
        "language": "english",
        "query_plan": plan,
        "sql": sql_str,
        "result": res_payload
    }
