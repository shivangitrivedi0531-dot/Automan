import os
import sys

# Ensure project root directory is in sys.path for importing scripts module
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

# Import validated deterministic sales query functions
from scripts.test_sale_by_invoice import get_sale_by_invoice
from scripts.test_sale_by_customer import get_sale_by_customer
from scripts.test_sale_by_product import get_sale_by_product
from scripts.test_sale_by_date import get_sale_by_date
from scripts.get_sale_by_series import get_sale_by_series
from scripts.get_sale_by_ev import get_sale_by_ev
from scripts.get_sale_by_financial_year import get_sale_by_financial_year
from scripts.get_sale_by_gl_account import get_sale_by_gl_account


def route_sales_query(query: dict) -> dict:
    """
    Deterministic Query Router for Sales (VSALE) queries.
    Receives a structured query dictionary:
        {
            "dimension": "<dimension_name>",
            "value": "<query_value>"
        }
    Routes the query to the corresponding validated deterministic sales query function.
    """
    # 1. Validate dictionary input
    if not isinstance(query, dict):
        return {
            "success": False,
            "error": "Input query must be a dictionary.",
            "dimension": None,
            "value": None
        }

    raw_dim = query.get("dimension")
    raw_val = query.get("value")

    # 2. Validate dimension existence
    if raw_dim is None or str(raw_dim).strip() == "":
        return {
            "success": False,
            "error": "Missing required field 'dimension' in query.",
            "dimension": None,
            "value": raw_val
        }

    # 3. Validate value existence
    if raw_val is None:
        return {
            "success": False,
            "error": "Missing required field 'value' in query.",
            "dimension": str(raw_dim).strip().lower(),
            "value": None
        }

    # 4. Normalize dimension name safely
    dim_norm = str(raw_dim).strip().lower()

    supported_dimensions = {
        "invoice": "invoice",
        "inv": "invoice",
        "customer": "customer",
        "cust": "customer",
        "product": "product",
        "prd": "product",
        "date": "date",
        "series": "series",
        "ev": "ev",
        "financial_year": "financial_year",
        "fy": "financial_year",
        "gl_account": "gl_account",
        "ac_code": "gl_account",
        "account": "gl_account"
    }

    # 5. Reject unsupported dimensions
    if dim_norm not in supported_dimensions:
        return {
            "success": False,
            "error": f"Unsupported dimension '{dim_norm}'. Supported dimensions: invoice, customer, product, date, series, ev, financial_year, gl_account.",
            "dimension": dim_norm,
            "value": raw_val
        }

    canonical_dim = supported_dimensions[dim_norm]

    # 6. Route to validated deterministic query function
    try:
        if canonical_dim == "invoice":
            result = get_sale_by_invoice(str(raw_val))
        elif canonical_dim == "customer":
            result = get_sale_by_customer(str(raw_val))
        elif canonical_dim == "product":
            result = get_sale_by_product(str(raw_val))
        elif canonical_dim == "date":
            if isinstance(raw_val, dict):
                s_dt = str(raw_val.get("start_date") or raw_val.get("start") or "").strip()
                e_dt = str(raw_val.get("end_date") or raw_val.get("end") or s_dt).strip()
            elif isinstance(raw_val, (list, tuple)) and len(raw_val) >= 2:
                s_dt = str(raw_val[0]).strip()
                e_dt = str(raw_val[1]).strip()
            else:
                val_str = str(raw_val).strip()
                if " to " in val_str:
                    parts = val_str.split(" to ")
                    s_dt, e_dt = parts[0].strip(), parts[1].strip()
                elif "," in val_str:
                    parts = val_str.split(",")
                    s_dt, e_dt = parts[0].strip(), parts[1].strip()
                else:
                    s_dt = val_str
                    e_dt = val_str
            result = get_sale_by_date(s_dt, e_dt)
        elif canonical_dim == "series":
            result = get_sale_by_series(str(raw_val))
        elif canonical_dim == "ev":
            result = get_sale_by_ev(raw_val)
        elif canonical_dim == "financial_year":
            result = get_sale_by_financial_year(str(raw_val))
        elif canonical_dim == "gl_account":
            result = get_sale_by_gl_account(str(raw_val))
        else:
            return {
                "success": False,
                "error": f"Internal routing error for dimension '{canonical_dim}'.",
                "dimension": canonical_dim,
                "value": raw_val
            }

        return {
            "success": True,
            "dimension": canonical_dim,
            "value": raw_val,
            "result": result
        }
    except Exception as e:
        return {
            "success": False,
            "error": f"Execution error in query function for {canonical_dim}: {str(e)}",
            "dimension": canonical_dim,
            "value": raw_val
        }


if __name__ == "__main__":
    print("=" * 50)
    print("SALES QUERY ROUTER TEST")
    print("=" * 50 + "\n")

    tests = [
        ("TEST 1 - PRODUCT", {"dimension": "product", "value": "0000003"}),
        ("TEST 2 - INVOICE", {"dimension": "invoice", "value": "0000001"}),
        ("TEST 3 - DATE", {"dimension": "date", "value": "20250711"}),
        ("TEST 4 - SERIES", {"dimension": "series", "value": "0000001"}),
        ("TEST 5 - EV", {"dimension": "ev", "value": 1}),
        ("TEST 6 - FINANCIAL YEAR", {"dimension": "financial_year", "value": "2025-26"}),
        ("TEST 7 - GL ACCOUNT", {"dimension": "gl_account", "value": "9100579"}),
        ("TEST 8 - CUSTOMER", {"dimension": "customer", "value": "9500001"}),
        ("TEST 9 - INVALID DIMENSION", {"dimension": "unsupported_dim", "value": "123"}),
        ("TEST 10 - MISSING VALUE", {"dimension": "product"}),
    ]

    all_passed = True

    for label, query in tests:
        res = route_sales_query(query)

        if label.startswith("TEST 9") or label.startswith("TEST 10"):
            # Expected error/rejection
            passed = (res.get("success") is False) and ("error" in res)
        else:
            # Expected success
            passed = (res.get("success") is True) and (res.get("result", {}).get("exists") is True)

        status = "[PASS]" if passed else "[FAIL]"
        print(f"{label}\n{status}\n")

        if not passed:
            all_passed = False
            print(f"Details: {res}\n")

    print("=" * 50)
    print("OVERALL RESULT")
    print("=" * 50)

    if all_passed:
        print("\nALL ROUTER TESTS PASSED [PASS]\n")
    else:
        print("\nSOME ROUTER TESTS FAILED [FAIL]\n")
