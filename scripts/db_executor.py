"""
Safe PostgreSQL Execution Layer for ERP Sales AI Agent.

Executes ONLY SQL queries that have been pre-validated by scripts/sql_validator.py.
Enforces read-only sessions, parameterized execution, JSON serialization conversion,
and error credential sanitization.
"""

import os
import sys
import json
import decimal
import datetime
from typing import Dict, Any, List, Optional

try:
    from dotenv import load_dotenv
    env_path = os.path.join(os.getcwd(), ".env")
    if os.path.exists(env_path):
        load_dotenv(dotenv_path=env_path)
    else:
        load_dotenv()
except ImportError:
    pass

try:
    import psycopg2
    from psycopg2.extras import RealDictCursor
except ImportError:
    psycopg2 = None
    RealDictCursor = None

from scripts.sql_validator import validate_sql


def get_db_connection():
    """
    Establishes a PostgreSQL database connection using environment variables.
    Sets connection session to read-only.
    """
    if psycopg2 is None:
        raise RuntimeError("Missing required PostgreSQL driver 'psycopg2'. Please install psycopg2-binary.")

    database_url = os.getenv("DATABASE_URL") or os.getenv("POSTGRES_URL")
    if database_url:
        conn = psycopg2.connect(database_url)
    else:
        host = os.getenv("DB_HOST") or os.getenv("POSTGRES_HOST") or os.getenv("PGHOST", "localhost")
        port = os.getenv("DB_PORT") or os.getenv("POSTGRES_PORT") or os.getenv("PGPORT", "5432")
        dbname = os.getenv("DB_NAME") or os.getenv("POSTGRES_DB") or os.getenv("PGDATABASE", "auto")
        user = os.getenv("DB_USER") or os.getenv("POSTGRES_USER") or os.getenv("PGUSER", "postgres")
        password = os.getenv("DB_PASSWORD") or os.getenv("POSTGRES_PASSWORD") or os.getenv("PGPASSWORD", "")

        conn = psycopg2.connect(
            host=host,
            port=port,
            dbname=dbname,
            user=user,
            password=password
        )

    conn.set_session(readonly=True)
    return conn


def _serialize_value(val: Any) -> Any:
    """
    Helper to convert PostgreSQL data types (Decimal, date, datetime) into JSON-safe types.
    """
    if val is None:
        return None
    elif isinstance(val, decimal.Decimal):
        return float(val)
    elif isinstance(val, (datetime.date, datetime.datetime, datetime.time)):
        return val.isoformat()
    elif isinstance(val, bytes):
        return val.decode("utf-8", errors="replace")
    elif isinstance(val, (list, tuple)):
        return [_serialize_value(v) for v in val]
    elif isinstance(val, dict):
        return {k: _serialize_value(v) for k, v in val.items()}
    return val


def _sanitize_error_message(err_str: str) -> str:
    """
    Sanitizes database errors to prevent credentials / secrets from being exposed in outputs.
    """
    s = str(err_str)
    # Redact common password / URI formats
    s = re.sub(r'password=[\'\"][^\'\"]*[\'\"]', 'password=***', s, flags=re.IGNORECASE)
    s = re.sub(r'://[^:]+:[^@]+@', '://***:***@', s)
    return s


import re


def execute_validated_query(sql: str, params: Optional[Any] = None) -> Dict[str, Any]:
    """
    Validates and executes a read-only PostgreSQL query.
    
    1. Runs sql_validator.validate_sql(sql, params).
    2. If invalid, returns structured error without connecting to PostgreSQL.
    3. If valid, connects to PostgreSQL in read-only session mode.
    4. Executes query with parameterized inputs.
    5. Returns JSON-safe result dictionary with keys: 'success', 'columns', 'rows', 'row_count'.
    """
    # 1. Pre-execution Validation Gate
    val_res = validate_sql(sql, params)
    if not val_res.get("valid"):
        errs = val_res.get("errors", ["Query failed SQL validation checks."])
        return {
            "success": False,
            "columns": [],
            "rows": [],
            "row_count": 0,
            "error": f"SQL validation failed: {'; '.join(errs)}"
        }

    # 2. Database Execution
    conn = None
    cur = None
    try:
        conn = get_db_connection()
        cur = conn.cursor(cursor_factory=RealDictCursor)

        if params:
            cur.execute(sql, params)
        else:
            cur.execute(sql)

        raw_rows = cur.fetchall() if cur.description else []
        columns = [desc[0] for desc in cur.description] if cur.description else []

        # Convert rows into JSON-serializable dictionaries
        serialized_rows = []
        for r in raw_rows:
            dict_row = dict(r)
            clean_row = {k: _serialize_value(v) for k, v in dict_row.items()}
            serialized_rows.append(clean_row)

        return {
            "success": True,
            "columns": columns,
            "rows": serialized_rows,
            "row_count": len(serialized_rows)
        }

    except Exception as e:
        safe_err = _sanitize_error_message(str(e))
        return {
            "success": False,
            "columns": [],
            "rows": [],
            "row_count": 0,
            "error": f"Database execution error: {safe_err}"
        }

    finally:
        if cur:
            try:
                cur.close()
            except Exception:
                pass
        if conn:
            try:
                conn.close()
            except Exception:
                pass
