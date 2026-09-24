"""
PostgreSQL SQL Generator for ERP Sales AI Agent.

Converts VALIDATED query plans from scripts/query_planner.py into safe,
read-only PostgreSQL SELECT queries with parameterized inputs.

THIS MODULE DOES NOT EXECUTE SQL AND DOES NOT CONNECT TO POSTGRESQL.
"""

from typing import Dict, Any, List, Tuple
import re

from scripts.schema_context import get_sales_schema_context
from scripts.query_planner import validate_query_plan

SCHEMA_CONTEXT = get_sales_schema_context()

FORBIDDEN_SQL_STATEMENTS = [
    "INSERT ", "UPDATE ", "DELETE ", "DROP ", "ALTER ", "TRUNCATE ", "CREATE ",
    "GRANT ", "REVOKE ", "COMMENT ", "VACUUM ", "CALL ", "DO "
]


def generate_sql(query_plan: Dict[str, Any]) -> Dict[str, Any]:
    """
    Converts a validated query plan into safe, read-only PostgreSQL SQL.
    Returns dictionary with keys: 'sql', 'params', 'read_only', 'tables', 'joins'.
    """
    if not isinstance(query_plan, dict):
        raise ValueError("Query plan must be a dictionary.")

    # Validate plan via query planner validator
    validated_plan = validate_query_plan(query_plan)
    if validated_plan.get("status") != "valid":
        reason = validated_plan.get("reason") or "Invalid or unsupported query plan."
        raise ValueError(f"Cannot generate SQL for invalid query plan: {reason}")

    module = validated_plan.get("module")
    if module != "sales":
        raise ValueError(f"Unsupported module '{module}'. Only 'sales' module is supported.")

    op = validated_plan.get("operation", "aggregate")
    metric = validated_plan.get("metric", {"field": "amount", "aggregation": "SUM"})
    filters = validated_plan.get("filters", [])
    group_by = validated_plan.get("group_by", [])
    order_by = validated_plan.get("order_by", [])
    limit = validated_plan.get("limit")

    tran_filters: List[str] = []
    vehicle_filters: List[str] = []
    params: List[Any] = []

    used_tables = set(["public.transection"])
    used_joins = []

    # Map logical filter fields to physical columns
    for flt in filters:
        f_field = flt["field"]
        f_op = flt["operator"]
        f_val = flt["value"]

        if f_field in ["date", "doc_date"]:
            clause, p = _build_filter_clause("t.doc_date", f_op, f_val)
            tran_filters.append(clause)
            params.extend(p)
        elif f_field in ["series"]:
            clause, p = _build_filter_clause("t.series", f_op, f_val)
            tran_filters.append(clause)
            params.extend(p)
        elif f_field in ["ev"]:
            clause, p = _build_filter_clause("t.ev", f_op, f_val)
            tran_filters.append(clause)
            params.extend(p)
        elif f_field in ["financial_year", "co_year"]:
            clause, p = _build_filter_clause("t.co_year", f_op, f_val)
            tran_filters.append(clause)
            params.extend(p)
        elif f_field in ["gl_account", "ac_code"]:
            clause, p = _build_filter_clause("t.ac_code", f_op, f_val)
            tran_filters.append(clause)
            params.extend(p)
        elif f_field in ["amount"]:
            clause, p = _build_filter_clause("(CASE WHEN t.cr_dr = 'D' THEN t.amount ELSE 0 END)", f_op, f_val)
            tran_filters.append(clause)
            params.extend(p)
        elif f_field in ["invoice", "inv_no"]:
            clause, p = _build_filter_clause("t.inv_no", f_op, f_val)
            tran_filters.append(clause)
            params.extend(p)
        elif f_field in ["product", "product_code", "product_name"]:
            clause, p = _build_filter_clause("h.product_code", f_op, f_val)
            vehicle_filters.append(clause)
            params.extend(p)
            used_tables.update(["public.trn_jobcard", "public.mst_history"])
            used_joins.extend([
                "transection (inv_type='VSALE') -> trn_jobcard.inv_no",
                "trn_jobcard.hist_code -> mst_history.hist_code"
            ])
        elif f_field in ["customer", "cust_code", "customer_name"]:
            clause, p = _build_filter_clause("h.cust_code", f_op, f_val)
            vehicle_filters.append(clause)
            params.extend(p)
            used_tables.update(["public.trn_jobcard", "public.mst_history"])
            used_joins.extend([
                "transection (inv_type='VSALE') -> trn_jobcard.inv_no",
                "trn_jobcard.hist_code -> mst_history.hist_code"
            ])
        else:
            raise ValueError(f"Unknown or unsupported filter field: {f_field}")

    # Generate SQL based on operation
    if op in ["aggregate", "count"] and not group_by:
        where_clauses = ["t.inv_type = 'VSALE'"]
        where_clauses.extend(tran_filters)

        if vehicle_filters:
            subquery_where = " AND ".join(vehicle_filters)
            where_clauses.append(f"""t.inv_no IN (
        SELECT TRIM(CAST(j.inv_no AS TEXT))
        FROM public.trn_jobcard j
        JOIN public.mst_history h ON j.hist_code = h.hist_code
        WHERE {subquery_where}
    )""")

        where_sql = "\n  AND ".join(where_clauses)
        agg_func = metric.get("aggregation", "SUM").upper()

        if op == "count":
            select_expr = "COUNT(DISTINCT t.inv_no) AS total_count"
        else:
            if agg_func == "SUM":
                select_expr = "COALESCE(SUM(CASE WHEN t.cr_dr = 'D' THEN t.amount ELSE 0 END), 0) AS total_amount"
            elif agg_func == "AVG":
                select_expr = "COALESCE(AVG(CASE WHEN t.cr_dr = 'D' THEN t.amount ELSE 0 END), 0) AS avg_amount"
            elif agg_func == "MIN":
                select_expr = "COALESCE(MIN(CASE WHEN t.cr_dr = 'D' THEN t.amount ELSE 0 END), 0) AS min_amount"
            elif agg_func == "MAX":
                select_expr = "COALESCE(MAX(CASE WHEN t.cr_dr = 'D' THEN t.amount ELSE 0 END), 0) AS max_amount"
            else:
                select_expr = "COUNT(*) AS total_count"

        sql = f"SELECT {select_expr}\nFROM public.transection t\nWHERE {where_sql};"

    elif op in ["grouped_aggregate", "ranking"] or group_by:
        where_clauses = ["t.inv_type = 'VSALE'"]
        where_clauses.extend(tran_filters)
        where_sql = "\n      AND ".join(where_clauses)

        subquery_where = ("WHERE " + " AND ".join(vehicle_filters)) if vehicle_filters else ""

        grp_col = group_by[0] if group_by else "product"
        if grp_col in ["product", "product_code"]:
            grp_expr = "h.product_code"
            grp_name_expr = "COALESCE(p.product_name, h.product_code) AS product_name"
            used_tables.update(["public.trn_jobcard", "public.mst_history", "public.mst_product"])
            used_joins.extend([
                "transection (inv_type='VSALE') -> trn_jobcard.inv_no",
                "trn_jobcard.hist_code -> mst_history.hist_code",
                "mst_history.product_code -> mst_product.product_code"
            ])
        elif grp_col in ["customer", "cust_code"]:
            grp_expr = "h.cust_code"
            grp_name_expr = "COALESCE(h.customer_name, h.cust_code) AS customer_name"
            used_tables.update(["public.trn_jobcard", "public.mst_history"])
            used_joins.extend([
                "transection (inv_type='VSALE') -> trn_jobcard.inv_no",
                "trn_jobcard.hist_code -> mst_history.hist_code"
            ])
        elif grp_col in ["series"]:
            grp_expr = "t_agg.series"
            grp_name_expr = "t_agg.series AS series_code"
        elif grp_col in ["co_year", "financial_year"]:
            grp_expr = "t_agg.co_year"
            grp_name_expr = "t_agg.co_year AS financial_year"
        else:
            grp_expr = "h.product_code"
            grp_name_expr = "h.product_code AS entity_name"

        order_sql = ""
        if order_by:
            ob_dir = order_by[0].get("direction", "DESC").upper()
            order_sql = f"\nORDER BY total_amount {ob_dir}"
        else:
            order_sql = "\nORDER BY total_amount DESC"

        limit_sql = f"\nLIMIT {int(limit)}" if limit is not None else ""

        sql = f"""WITH tran_agg AS (
    SELECT 
        TRIM(CAST(inv_no AS TEXT)) AS inv_no,
        series,
        co_year,
        COALESCE(SUM(CASE WHEN cr_dr = 'D' THEN amount ELSE 0 END), 0) AS invoice_total
    FROM public.transection t
    WHERE {where_sql}
    GROUP BY TRIM(CAST(inv_no AS TEXT)), series, co_year
)
SELECT 
    {grp_expr} AS entity_code,
    {grp_name_expr},
    COALESCE(SUM(t_agg.invoice_total), 0) AS total_amount
FROM tran_agg t_agg
JOIN public.trn_jobcard j ON t_agg.inv_no = TRIM(CAST(j.inv_no AS TEXT))
JOIN public.mst_history h ON j.hist_code = h.hist_code
LEFT JOIN public.mst_product p ON h.product_code = p.product_code
{subquery_where}
GROUP BY {grp_expr}, p.product_name{order_sql}{limit_sql};"""

    elif op == "detail":
        where_clauses = ["t.inv_type = 'VSALE'"]
        where_clauses.extend(tran_filters)

        if vehicle_filters:
            subquery_where = " AND ".join(vehicle_filters)
            where_clauses.append(f"""t.inv_no IN (
        SELECT TRIM(CAST(j.inv_no AS TEXT))
        FROM public.trn_jobcard j
        JOIN public.mst_history h ON j.hist_code = h.hist_code
        WHERE {subquery_where}
    )""")

        where_sql = "\n  AND ".join(where_clauses)
        limit_sql = f"\nLIMIT {int(limit)}" if limit is not None else ""

        sql = f"""SELECT 
    TRIM(CAST(t.inv_no AS TEXT)) AS invoice_no,
    TRIM(CAST(t.doc_date AS TEXT)) AS doc_date,
    t.series,
    t.co_year,
    t.ac_code,
    COALESCE(SUM(CASE WHEN t.cr_dr = 'D' THEN t.amount ELSE 0 END), 0) AS invoice_total_amount
FROM public.transection t
WHERE {where_sql}
GROUP BY TRIM(CAST(t.inv_no AS TEXT)), t.doc_date, t.series, t.co_year, t.ac_code
ORDER BY invoice_no{limit_sql};"""

    else:
        raise ValueError(f"Unsupported query planner operation: {op}")

    # Verify SQL safety
    _verify_sql_safety(sql)

    return {
        "sql": sql,
        "params": params,
        "read_only": True,
        "tables": sorted(list(used_tables)),
        "joins": sorted(list(set(used_joins)))
    }


def _build_filter_clause(column_expr: str, operator: str, value: Any) -> Tuple[str, List[Any]]:
    """
    Constructs parameterized WHERE clause fragments.
    """
    op = str(operator).strip().upper()

    if op == "=":
        return f"{column_expr} = %s", [value]
    elif op == "!=":
        return f"{column_expr} != %s", [value]
    elif op == ">":
        return f"{column_expr} > %s", [value]
    elif op == ">=":
        return f"{column_expr} >= %s", [value]
    elif op == "<":
        return f"{column_expr} < %s", [value]
    elif op == "<=":
        return f"{column_expr} <= %s", [value]
    elif op == "LIKE":
        return f"{column_expr} LIKE %s", [value]
    elif op == "ILIKE":
        return f"{column_expr} ILIKE %s", [value]
    elif op == "BETWEEN":
        if isinstance(value, (list, tuple)) and len(value) == 2:
            return f"{column_expr} BETWEEN %s AND %s", [value[0], value[1]]
        else:
            return f"{column_expr} = %s", [value]
    elif op == "IN":
        if isinstance(value, (list, tuple)):
            placeholders = ", ".join(["%s"] * len(value))
            return f"{column_expr} IN ({placeholders})", list(value)
        else:
            return f"{column_expr} = %s", [value]
    elif op == "NOT IN":
        if isinstance(value, (list, tuple)):
            placeholders = ", ".join(["%s"] * len(value))
            return f"{column_expr} NOT IN ({placeholders})", list(value)
        else:
            return f"{column_expr} != %s", [value]
    else:
        return f"{column_expr} = %s", [value]


def _verify_sql_safety(sql: str) -> None:
    """
    Enforces strict read-only guarantees on generated SQL string.
    """
    cleaned = sql.strip().upper()

    if not (cleaned.startswith("SELECT") or cleaned.startswith("WITH")):
        raise ValueError("Security violation: Generated SQL must start with SELECT or WITH.")

    for stmt in FORBIDDEN_SQL_STATEMENTS:
        if stmt in cleaned:
            raise ValueError(f"Security violation: Unsafe SQL statement detected ({stmt.strip()}).")

    stripped_sql = sql.strip()
    if stripped_sql.endswith(";"):
        stripped_sql = stripped_sql[:-1]
    if ";" in stripped_sql:
        raise ValueError("Security violation: Multiple SQL statements separated by semicolons are forbidden.")
