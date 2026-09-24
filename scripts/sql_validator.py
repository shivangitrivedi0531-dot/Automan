"""
PostgreSQL SQL Security & Correctness Validator for ERP Sales AI Agent.

This module acts as the final gate before database execution, verifying that
generated SQL queries adhere to strict read-only guarantees, parameterization,
trusted table/column references, and validated relationship rules.

THIS MODULE DOES NOT EXECUTE SQL AND DOES NOT CONNECT TO POSTGRESQL.
"""

from typing import Dict, Any, List, Optional
import re

from scripts.schema_context import get_sales_schema_context

# Load trusted schema context
SCHEMA_CONTEXT = get_sales_schema_context()

FORBIDDEN_SQL_STATEMENTS = [
    "INSERT", "UPDATE", "DELETE", "DROP", "ALTER", "TRUNCATE", "CREATE",
    "GRANT", "REVOKE", "COMMENT", "VACUUM", "CALL", "DO", "MERGE", "COPY"
]

ALLOWED_TABLES = {
    "TRANSECTION", "PUBLIC.TRANSECTION",
    "MST_HISTORY", "PUBLIC.MST_HISTORY",
    "TRN_JOBCARD", "PUBLIC.TRN_JOBCARD",
    "TRN_LABOUR_ISSUE", "PUBLIC.TRN_LABOUR_ISSUE",
    "TRN_INSU_DETAIL", "PUBLIC.TRN_INSU_DETAIL",
    "MST_PRODUCT", "PUBLIC.MST_PRODUCT",
    "MST_AC_DETAIL", "PUBLIC.MST_AC_DETAIL",
    "MST_SERIES", "PUBLIC.MST_SERIES"
}

UNVALIDATED_TABLES = [
    "MST_SALESMAN", "PUBLIC.MST_SALESMAN",
    "MST_FINANCER", "PUBLIC.MST_FINANCER",
    "MST_SALE_TYPE", "PUBLIC.MST_SALE_TYPE",
    "MST_CUSTOMER_PROFILE", "PUBLIC.MST_CUSTOMER_PROFILE"
]

SQL_KEYWORDS = {
    "SELECT", "FROM", "WHERE", "JOIN", "ON", "LEFT", "RIGHT", "INNER", "OUTER",
    "GROUP", "BY", "ORDER", "HAVING", "IN", "NOT", "BETWEEN", "AND", "OR", "IS",
    "NULL", "AS", "WITH", "LIMIT", "CASE", "WHEN", "THEN", "ELSE", "END", "ANY",
    "CAST", "TRIM", "COALESCE", "UPPER", "LOWER", "ASC", "DESC", "TEXT", "SUM",
    "COUNT", "AVG", "MIN", "MAX", "DISTINCT", "PUBLIC", "VSALE", "TRANSECTION",
    "MST_HISTORY", "TRN_JOBCARD", "MST_PRODUCT", "MST_AC_DETAIL", "TRN_LABOUR_ISSUE",
    "TRN_INSU_DETAIL", "MST_SERIES", "TRAN_AGG", "T", "H", "J", "P", "A", "S", "T_AGG"
}

ALLOWED_COLUMNS = {
    "INV_NO", "DOC_NO", "FROM_DOC_NO", "DOC_DATE", "SERIES", "EV", "CO_YEAR",
    "AC_CODE", "DEBIT", "CREDIT", "AMOUNT", "CR_DR", "VDATE", "USER_ID", "AUTO_ID", "INV_TYPE",
    "HIST_CODE", "CHASSIS_NO", "ENGINE_NO", "REG_NO", "PRODUCT_CODE", "SUB_PRD_CODE",
    "SALE_DATE", "CUSTOMER_NAME", "CUST_CODE", "MODEL",
    "JOB_NO", "JOB_DATE", "INV_DT", "SERVICE_NO",
    "PRODUCT_ID", "CO_PRD_CODE", "PRODUCT_NAME", "SHORT_NAME", "CLASS_CODE",
    "AC_NAME", "AC_TYPE", "GROUP_CODE", "HEAD_CODE",
    "TOTAL_AMOUNT", "TOTAL_COUNT", "INVOICE_TOTAL", "INVOICE_TOTAL_AMOUNT", "INVOICE_NO",
    "AVG_AMOUNT", "MIN_AMOUNT", "MAX_AMOUNT", "ENTITY_CODE", "ENTITY_NAME",
    "SERIES_CODE", "FINANCIAL_YEAR", "SERIES_NAME", "SER_CODE", "NAME", "LABOUR_ISSUE_ID",
    "INSU_DETAIL_ID", "TOT_AMT", "INSU_AMT"
}


def validate_sql(sql: str, params: Optional[Any] = None) -> Dict[str, Any]:
    """
    Validates generated SQL string and parameters for security, syntax, and schema correctness.
    Returns structured dictionary with keys: 'valid', 'sql', 'params', 'errors', 'warnings'.
    """
    errors: List[str] = []
    warnings: List[str] = []

    if not isinstance(sql, str) or not sql.strip():
        return {
            "valid": False,
            "sql": sql,
            "params": params,
            "errors": ["SQL query must be a non-empty string."],
            "warnings": []
        }

    raw_sql = sql.strip()
    uppercase_sql = raw_sql.upper()

    # 1. READ-ONLY GUARANTEE
    if not (uppercase_sql.startswith("SELECT") or uppercase_sql.startswith("WITH")):
        errors.append("SQL query must start with read-only SELECT or WITH statement.")

    for kw in FORBIDDEN_SQL_STATEMENTS:
        if re.search(r'\b' + kw + r'\b', uppercase_sql):
            errors.append(f"Forbidden destructive SQL command detected: '{kw}'.")

    # 2. SQL COMMENTS & MULTIPLE STATEMENTS
    if "--" in raw_sql or "/*" in raw_sql:
        errors.append("SQL comments ('--' or '/*') are forbidden for security reasons.")

    stripped = raw_sql.strip()
    if stripped.endswith(";"):
        stripped = stripped[:-1].strip()
    if ";" in stripped:
        errors.append("Multiple SQL statements separated by semicolons are forbidden.")

    # 3. VSALE REQUIREMENT CHECK
    if "TRANSECTION" in uppercase_sql and "VSALE" not in uppercase_sql:
        errors.append("Sales queries on 'transection' must enforce the VSALE condition (inv_type = 'VSALE').")

    # 4. CANDIDATE-ONLY & UNVALIDATED JOINS CHECK
    if re.search(r'CUST_CODE\s*=\s*(\w+\.)?AC_CODE|AC_CODE\s*=\s*(\w+\.)?CUST_CODE', uppercase_sql):
        errors.append("Forbidden candidate-only join detected (mst_history.cust_code -> transection.ac_code is not a validated relationship).")

    for ut in UNVALIDATED_TABLES:
        if re.search(r'\b' + ut + r'\b', uppercase_sql):
            errors.append(f"Forbidden join to unvalidated table detected: '{ut.lower()}'.")

    # 5. TRUSTED TABLES CHECK
    table_matches = re.findall(r'(?:FROM|JOIN)\s+([a-zA-Z0-9_\.]+)', uppercase_sql)
    for tm in table_matches:
        tbl = tm.strip().upper()
        if tbl not in ALLOWED_TABLES and tbl not in ["TRAN_AGG"]:  # CTE alias allowed
            errors.append(f"Forbidden or unknown table referenced: '{tm}'.")

    # 6. UNKNOWN COLUMNS CHECK
    clean_sql = re.sub(r"'[^']*'", "", raw_sql)
    clean_sql = re.sub(r'\b[a-zA-Z0-9_]+\.', '', clean_sql)
    tokens = re.findall(r'\b[a-zA-Z_][a-zA-Z0-9_]*\b', clean_sql)
    for tok in tokens:
        u = tok.upper()
        if u not in SQL_KEYWORDS and u not in ALLOWED_COLUMNS:
            errors.append(f"Forbidden or unknown column referenced: '{tok}'.")

    # 7. ACCOUNTING MULTIPLICATION CHECK
    if "SUM(" in uppercase_sql and "FROM PUBLIC.TRANSECTION" in uppercase_sql and ("JOIN PUBLIC.TRN_JOBCARD" in uppercase_sql or "JOIN PUBLIC.MST_HISTORY" in uppercase_sql):
        if "IN (" not in uppercase_sql and "TRAN_AGG" not in uppercase_sql:
            errors.append("Unsafe accounting multiplication pattern detected: Direct JOIN between 'transection' and one-to-many history/jobcard rows with SUM aggregation.")

    # 8. PARAMETER SAFETY CHECK
    if re.search(r"WHERE\s+.*\b(PRODUCT_CODE|PRODUCT_NAME|CUST_CODE|CUSTOMER_NAME|SERIES|AC_CODE)\s*=\s*'[^']+'", uppercase_sql):
        errors.append("Unsafe query construction: Raw literal string value embedded directly in WHERE clause instead of using parameter placeholder '%s'.")

    return {
        "valid": len(errors) == 0,
        "sql": sql,
        "params": params,
        "errors": errors,
        "warnings": warnings
    }
