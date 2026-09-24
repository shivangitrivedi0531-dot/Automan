"""
ERP Sales Query Planner.

Converts structured natural-language query representations into validated, 
declarative Sales query plans.

This module DOES NOT generate SQL, DOES NOT execute SQL, and DOES NOT access 
PostgreSQL directly. It acts as the trusted declarative planning layer using 
metadata from scripts/schema_context.py.
"""

from typing import Dict, Any, List, Optional
from scripts.schema_context import get_sales_schema_context

# Load trusted schema context
SCHEMA_CONTEXT = get_sales_schema_context()

SUPPORTED_OPERATIONS = {
    "detail",
    "count",
    "aggregate",
    "grouped_aggregate",
    "comparison",
    "ranking"
}

SUPPORTED_AGGREGATIONS = {"SUM", "COUNT", "AVG", "MIN", "MAX"}

SUPPORTED_OPERATORS = {
    "=", "!=", ">", ">=", "<", "<=", "IN", "NOT IN", "BETWEEN", "LIKE", "ILIKE"
}

VALID_FIELDS_MAP = {
    "product": "mst_history.product_code",
    "product_code": "mst_history.product_code",
    "product_name": "mst_product.product_name",
    "customer": "mst_history.cust_code",
    "cust_code": "mst_history.cust_code",
    "customer_name": "mst_history.customer_name",
    "invoice": "transection.inv_no",
    "inv_no": "transection.inv_no",
    "doc_no": "transection.doc_no",
    "doc_date": "transection.doc_date",
    "date": "transection.doc_date",
    "month": "transection.doc_date",
    "year": "transection.doc_date",
    "series": "transection.series",
    "ev": "transection.ev",
    "financial_year": "transection.co_year",
    "co_year": "transection.co_year",
    "gl_account": "transection.ac_code",
    "ac_code": "transection.ac_code",
    "ac_name": "mst_ac_detail.ac_name",
    "amount": "transection.amount",
    "debit": "transection.debit",
    "credit": "transection.credit",
    "chassis_no": "mst_history.chassis_no",
    "engine_no": "mst_history.engine_no",
    "reg_no": "mst_history.reg_no",
    "hist_code": "mst_history.hist_code"
}

UNVALIDATED_DIMENSIONS = {
    "salesman",
    "salesman_code",
    "financer",
    "financer_code",
    "sale_type",
    "sale_type_code",
    "customer_profile"
}


def build_query_plan(parsed_query: Dict[str, Any]) -> Dict[str, Any]:
    """
    Convert a parsed query representation into a validated, structured Sales query plan.
    Supports legacy simple formats (dimension + value) as well as rich structured inputs.
    """
    if not isinstance(parsed_query, dict):
        return {
            "status": "unsupported",
            "reason": "Invalid input: parsed_query must be a dictionary.",
            "module": "sales"
        }

    # Check for failure or unsupported intent from parser
    if parsed_query.get("success") is False:
        return {
            "status": "unsupported",
            "reason": parsed_query.get("error") or "Unrecognized or unsupported sales query.",
            "module": "sales"
        }

    # Extract base attributes
    module = "sales"
    raw_intent = parsed_query.get("intent") or "sales_query"
    raw_dim = parsed_query.get("dimension")
    raw_val = parsed_query.get("value")

    # Reject explicitly unvalidated dimensions early
    if raw_dim in UNVALIDATED_DIMENSIONS:
        return {
            "status": "unsupported",
            "reason": f"No validated Sales relationship exists for requested dimension: {raw_dim}",
            "module": module
        }

    # Initialize plan structure
    plan: Dict[str, Any] = {
        "status": "valid",
        "reason": None,
        "module": module,
        "operation": parsed_query.get("operation") or "aggregate",
        "metric": {
            "field": "amount",
            "aggregation": "SUM"
        },
        "filters": [],
        "group_by": [],
        "order_by": [],
        "limit": parsed_query.get("limit"),  # None if not requested
        "select": [],
        "joins": [],
        "needs_vehicle_details": False,
        "needs_product_details": False,
        "needs_customer_details": False
    }

    # Custom metric extraction
    if "metric" in parsed_query and isinstance(parsed_query["metric"], dict):
        m_field = parsed_query["metric"].get("field", "amount")
        m_agg = str(parsed_query["metric"].get("aggregation", "SUM")).upper()
        plan["metric"] = {"field": m_field, "aggregation": m_agg}

    # 1. Handle Legacy Format (dimension + value)
    if raw_dim and raw_val is not None:
        if raw_dim not in VALID_FIELDS_MAP and raw_dim not in ["invoice", "customer", "product", "date", "series", "ev", "financial_year", "gl_account"]:
            return {
                "status": "unsupported",
                "reason": f"Unknown or unsupported dimension: {raw_dim}",
                "module": module
            }

        # Date filter formatting
        if raw_dim == "date":
            if isinstance(raw_val, dict):
                if "start" in raw_val and "end" in raw_val:
                    plan["filters"].append({
                        "field": "date",
                        "operator": "BETWEEN",
                        "value": [raw_val["start"], raw_val["end"]]
                    })
                elif "date" in raw_val:
                    plan["filters"].append({
                        "field": "date",
                        "operator": "=",
                        "value": raw_val["date"]
                    })
                else:
                    plan["filters"].append({
                        "field": "date",
                        "operator": "=",
                        "value": str(raw_val)
                    })
            else:
                plan["filters"].append({
                    "field": "date",
                    "operator": "=",
                    "value": raw_val
                })
        else:
            plan["filters"].append({
                "field": raw_dim,
                "operator": "=",
                "value": raw_val
            })

    # 2. Handle Rich Filters
    if "filters" in parsed_query and isinstance(parsed_query["filters"], list):
        for f in parsed_query["filters"]:
            if isinstance(f, dict) and "field" in f:
                f_field = f["field"]
                if f_field in UNVALIDATED_DIMENSIONS:
                    return {
                        "status": "unsupported",
                        "reason": f"No validated Sales relationship exists for requested dimension: {f_field}",
                        "module": module
                    }
                plan["filters"].append({
                    "field": f_field,
                    "operator": f.get("operator", "="),
                    "value": f.get("value")
                })

    # 3. Handle Entities Map if present
    if "entities" in parsed_query and isinstance(parsed_query["entities"], dict):
        for ent_k, ent_v in parsed_query["entities"].items():
            if ent_k in UNVALIDATED_DIMENSIONS:
                return {
                    "status": "unsupported",
                    "reason": f"No validated Sales relationship exists for requested dimension: {ent_k}",
                    "module": module
                }
            # Add entity filter if not already present
            if not any(flt["field"] == ent_k for flt in plan["filters"]):
                plan["filters"].append({
                    "field": ent_k,
                    "operator": "=",
                    "value": ent_v
                })

    # 4. Handle Grouping
    if "group_by" in parsed_query and isinstance(parsed_query["group_by"], list):
        plan["group_by"] = parsed_query["group_by"]
        if plan["group_by"] and plan["operation"] == "aggregate":
            plan["operation"] = "grouped_aggregate"

    # 5. Handle Sorting
    if "order_by" in parsed_query and isinstance(parsed_query["order_by"], list):
        for ob in parsed_query["order_by"]:
            if isinstance(ob, dict) and "field" in ob:
                plan["order_by"].append({
                    "field": ob["field"],
                    "direction": str(ob.get("direction", "ASC")).upper()
                })

    # 6. Handle Select Fields
    if "select" in parsed_query and isinstance(parsed_query["select"], list):
        plan["select"] = parsed_query["select"]
        if plan["select"] and plan["operation"] == "aggregate":
            plan["operation"] = "detail"

    # 7. Operation Adjustments based on intent
    if raw_intent == "ranking" or plan["limit"] is not None:
        if plan["group_by"] or any(ob.get("field") == "amount" for ob in plan["order_by"]):
            plan["operation"] = "ranking"

    # Determine required joins & details
    _resolve_joins_and_details(plan)

    # Validate final plan
    return validate_query_plan(plan)


def _resolve_joins_and_details(plan: Dict[str, Any]) -> None:
    """
    Internal helper to analyze plan fields and attach validated schema joins.
    """
    all_fields = set()
    for f in plan["filters"]:
        all_fields.add(f["field"])
    for g in plan["group_by"]:
        all_fields.add(g)
    for s in plan["select"]:
        all_fields.add(s)
    for o in plan["order_by"]:
        all_fields.add(o["field"])

    vehicle_fields = {"product", "product_code", "customer", "cust_code", "customer_name", "chassis_no", "engine_no", "reg_no", "hist_code"}
    product_master_fields = {"product_name", "sub_prd_code", "co_prd_code"}

    joins = []

    # Check if vehicle/history bridge is needed
    if any(f in vehicle_fields for f in all_fields):
        plan["needs_vehicle_details"] = True
        joins.append("transection (inv_type='VSALE') -> trn_jobcard.inv_no")
        joins.append("trn_jobcard.hist_code -> mst_history.hist_code")

    # Check if product master lookup is needed
    if any(f in product_master_fields for f in all_fields) or "product" in all_fields:
        plan["needs_product_details"] = True
        if "transection (inv_type='VSALE') -> trn_jobcard.inv_no" not in joins:
            joins.append("transection (inv_type='VSALE') -> trn_jobcard.inv_no")
            joins.append("trn_jobcard.hist_code -> mst_history.hist_code")
        joins.append("mst_history.product_code -> mst_product.product_code")

    # Check if customer details needed
    if any(f in {"customer", "cust_code", "customer_name"} for f in all_fields):
        plan["needs_customer_details"] = True

    plan["joins"] = joins


def validate_query_plan(plan: Dict[str, Any]) -> Dict[str, Any]:
    """
    Validate that the query plan only uses supported operations, metrics,
    fields, and validated schema relationships.
    """
    if not isinstance(plan, dict):
        return {
            "status": "unsupported",
            "reason": "Plan must be a dictionary.",
            "module": "sales"
        }

    if plan.get("status") != "valid":
        return plan

    # Validate module
    if plan.get("module") != "sales":
        plan["status"] = "unsupported"
        plan["reason"] = f"Unsupported module: {plan.get('module')}"
        return plan

    # Validate operation
    op = plan.get("operation")
    if op not in SUPPORTED_OPERATIONS:
        plan["status"] = "unsupported"
        plan["reason"] = f"Unsupported operation: {op}"
        return plan

    # Validate metric aggregation
    metric = plan.get("metric", {})
    if isinstance(metric, dict) and "aggregation" in metric:
        agg = metric["aggregation"]
        if agg not in SUPPORTED_AGGREGATIONS:
            plan["status"] = "unsupported"
            plan["reason"] = f"Unsupported aggregation function: {agg}"
            return plan

    # Validate filters
    for flt in plan.get("filters", []):
        if not isinstance(flt, dict) or "field" not in flt:
            plan["status"] = "unsupported"
            plan["reason"] = "Invalid filter format."
            return plan

        f_field = flt["field"]
        if f_field in UNVALIDATED_DIMENSIONS:
            plan["status"] = "unsupported"
            plan["reason"] = f"No validated Sales relationship exists for requested dimension: {f_field}"
            return plan

        if f_field not in VALID_FIELDS_MAP and f_field not in ["product", "customer", "invoice", "date", "series", "ev", "financial_year", "gl_account", "amount"]:
            plan["status"] = "unsupported"
            plan["reason"] = f"Unknown or unsupported field: {f_field}"
            return plan

        f_op = flt.get("operator", "=")
        if f_op not in SUPPORTED_OPERATORS:
            plan["status"] = "unsupported"
            plan["reason"] = f"Unsupported filter operator: {f_op}"
            return plan

    # Validate group_by fields
    for g_field in plan.get("group_by", []):
        if g_field in UNVALIDATED_DIMENSIONS:
            plan["status"] = "unsupported"
            plan["reason"] = f"No validated Sales relationship exists for requested dimension: {g_field}"
            return plan
        if g_field not in VALID_FIELDS_MAP and g_field not in ["product", "customer", "invoice", "date", "series", "ev", "financial_year", "gl_account"]:
            plan["status"] = "unsupported"
            plan["reason"] = f"Unknown or unsupported grouping field: {g_field}"
            return plan

    # Validate limit if provided
    limit = plan.get("limit")
    if limit is not None:
        if not isinstance(limit, int) or limit <= 0:
            plan["status"] = "unsupported"
            plan["reason"] = f"Invalid limit value: {limit}"
            return plan

    return plan
