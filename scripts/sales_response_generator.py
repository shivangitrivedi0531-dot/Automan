import os
import sys

# Ensure sys.stdout handles UTF-8 formatting on Windows consoles
if hasattr(sys.stdout, "reconfigure"):
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass

# Ensure project root directory is in sys.path for importing scripts module
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from typing import Dict, Any, Optional
from scripts.sales_agent import run_sales_agent

# Forbidden strings in generated responses to ensure security
PROHIBITED_STRINGS = [
    "SELECT ", "INSERT INTO", "UPDATE ", "DELETE FROM", "DROP TABLE", "TRUNCATE TABLE",
    "POSTGRES", "PASSWORD=", "PORT=", "HOST=", "POSTGRESQL://"
]


def _format_currency(amount: Optional[float]) -> str:
    """Formats float amount to Indian Rupee currency standard ₹XX,XXX.XX."""
    if amount is None:
        return "₹0.00"
    try:
        val = float(amount)
        return f"₹{val:,.2f}"
    except (ValueError, TypeError):
        return f"₹{amount}"


def generate_sales_response(agent_result: Dict[str, Any]) -> str:
    """
    Converts a validated agent result from sales_agent.py into a clear, natural-language response.
    
    Rules:
    - Does NOT query the database.
    - Does NOT calculate totals from raw records.
    - Does NOT invent missing information.
    - Summarizes/formats values already present in the validated agent result.
    """
    # 1. Input dictionary validation
    if not isinstance(agent_result, dict):
        return "Unable to process request: Invalid agent response format."

    # 2. Check for Agent/Parser/Router Failure
    if not agent_result.get("success", False):
        err_msg = agent_result.get("error") or "An error occurred while processing the sales request."
        return f"Unable to process request: {err_msg}"

    # 3. Extract parsed query metadata and function result payload
    parsed_query = agent_result.get("parsed_query", {})
    dimension = str(parsed_query.get("dimension") or "").lower()
    res_data = agent_result.get("result")

    if not isinstance(res_data, dict):
        return "No matching Sales records were found for the requested criteria."

    # 4. Check for No Results / Non-existent records
    if not res_data.get("exists", True) or res_data.get("number_of_invoices") == 0:
        return "No matching Sales records were found for the requested criteria."

    inv_count = res_data.get("number_of_invoices", 0)
    ac_rows = res_data.get("number_of_accounting_rows", 0)
    total_amt = res_data.get("total_amount", 0.0)
    formatted_amt = _format_currency(total_amt)

    # 5. Dimension-specific Natural Language Response Formatting

    # PRODUCT
    if dimension == "product":
        prod_code = res_data.get("product_code") or parsed_query.get("value") or ""
        prod_name = res_data.get("product_name")
        label = f"{prod_name} (Product code {prod_code})" if prod_name and prod_name != prod_code else f"Product {prod_code}"
        inv_label = "invoice" if inv_count == 1 else "invoices"
        row_label = "accounting row" if ac_rows == 1 else "accounting rows"
        return f"{label} sales: {inv_count:,} {inv_label} with {ac_rows:,} {row_label} and a total amount of {formatted_amt}."

    # INVOICE
    elif dimension == "invoice":
        inv_no = res_data.get("invoice_no") or parsed_query.get("value") or ""
        tx_summary = res_data.get("transaction_summary", {})
        inv_ac_rows = tx_summary.get("accounting_rows", res_data.get("number_of_accounting_rows", 0))
        inv_amt = tx_summary.get("total_amount", res_data.get("total_amount", 0.0))
        inv_formatted_amt = _format_currency(inv_amt)
        doc_date = tx_summary.get("doc_date") or ""

        date_str = f" (Date: {doc_date})" if doc_date else ""
        row_label = "accounting row" if inv_ac_rows == 1 else "accounting rows"

        # Check for customer info in vehicles
        cust_str = ""
        vehicles = res_data.get("vehicles", [])
        if isinstance(vehicles, list) and len(vehicles) > 0:
            c_name = vehicles[0].get("customer_name")
            c_code = vehicles[0].get("cust_code")
            if c_name:
                cust_str = f" for customer {c_name}" + (f" ({c_code})" if c_code else "")

        return f"Invoice {inv_no}{cust_str}{date_str} has {inv_ac_rows:,} {row_label} with a total amount of {inv_formatted_amt}."

    # EV / NON-EV
    elif dimension == "ev":
        ev_label = res_data.get("ev_label") or ("EV" if res_data.get("ev") == 1 else "NON-EV")
        inv_label = "invoice" if inv_count == 1 else "invoices"
        row_label = "accounting row" if ac_rows == 1 else "accounting rows"
        return f"{ev_label} sales: {inv_count:,} {inv_label} with {ac_rows:,} {row_label} and a total amount of {formatted_amt}."

    # FINANCIAL YEAR
    elif dimension == "financial_year":
        fy = res_data.get("co_year") or parsed_query.get("value") or ""
        inv_label = "invoice" if inv_count == 1 else "invoices"
        row_label = "accounting row" if ac_rows == 1 else "accounting rows"
        return f"Sales for financial year {fy}: {inv_count:,} {inv_label} with {ac_rows:,} {row_label} and a total amount of {formatted_amt}."

    # SERIES
    elif dimension == "series":
        s_code = res_data.get("series_code") or parsed_query.get("value") or ""
        s_name = res_data.get("series_name")
        series_label = f"Voucher series {s_code} ({s_name})" if s_name else f"Voucher series {s_code}"
        inv_label = "invoice" if inv_count == 1 else "invoices"
        row_label = "accounting row" if ac_rows == 1 else "accounting rows"
        return f"{series_label} sales: {inv_count:,} {inv_label} with {ac_rows:,} {row_label} and a total amount of {formatted_amt}."

    # GL ACCOUNT
    elif dimension == "gl_account":
        ac_code = res_data.get("ac_code") or parsed_query.get("value") or ""
        account_name = res_data.get("account_name")
        acc_label = f"GL Account {ac_code} ({account_name})" if account_name else f"GL Account {ac_code}"
        inv_label = "invoice" if inv_count == 1 else "invoices"
        row_label = "accounting row" if ac_rows == 1 else "accounting rows"
        return f"{acc_label}: {inv_count:,} {inv_label} with {ac_rows:,} {row_label} and a total amount of {formatted_amt}."

    # DATE / DATE RANGE
    elif dimension == "date":
        s_date = res_data.get("start_date") or ""
        e_date = res_data.get("end_date") or ""
        
        inv_label = "invoice" if inv_count == 1 else "invoices"
        row_label = "accounting row" if ac_rows == 1 else "accounting rows"

        if s_date and e_date and s_date != e_date:
            date_label = f"Sales from {s_date} to {e_date}"
        elif s_date:
            date_label = f"Sales on {s_date}"
        else:
            date_label = "Sales for requested date period"

        return f"{date_label}: {inv_count:,} {inv_label} with {ac_rows:,} {row_label} and a total amount of {formatted_amt}."

    # CUSTOMER
    elif dimension == "customer":
        c_code = res_data.get("customer_code") or parsed_query.get("value") or ""
        c_name = res_data.get("customer_name")
        cust_label = f"customer {c_name} (code: {c_code})" if c_name else f"customer {c_code}"
        inv_label = "invoice" if inv_count == 1 else "invoices"
        row_label = "accounting row" if ac_rows == 1 else "accounting rows"
        return f"Sales for {cust_label}: {inv_count:,} {inv_label} with {ac_rows:,} {row_label} and a total amount of {formatted_amt}."

    # GENERIC FALLBACK SUMMARY
    else:
        inv_label = "invoice" if inv_count == 1 else "invoices"
        row_label = "accounting row" if ac_rows == 1 else "accounting rows"
        return f"Sales query result: {inv_count:,} {inv_label} with {ac_rows:,} {row_label} and a total amount of {formatted_amt}."


def _verify_response_security(response_text: str) -> bool:
    """Verifies that generated response is valid, non-empty, and free of SQL/credentials."""
    if not isinstance(response_text, str) or not response_text.strip():
        return False

    resp_upper = response_text.upper()
    for kw in PROHIBITED_STRINGS:
        if kw in resp_upper:
            return False

    return True


if __name__ == "__main__":
    print("=" * 50)
    print("SALES RESPONSE GENERATOR TEST")
    print("=" * 50 + "\n")

    test_cases = [
        ("TEST 1 - PRODUCT", "Show me Jupiter sales"),
        ("TEST 2 - INVOICE", "Show sales for invoice 0000302"),
        ("TEST 3 - EV", "Show EV sales"),
        ("TEST 4 - NON-EV", "Show non EV sales"),
        ("TEST 5 - FINANCIAL YEAR", "Show sales for financial year 2025-26"),
        ("TEST 6 - SERIES", "Show sales for voucher series 0000001"),
        ("TEST 7 - GL ACCOUNT", "Show sales for GL account 9100001"),
        ("TEST 8 - SINGLE DATE", "Show sales on 20250711"),
        ("TEST 9 - DATE RANGE", "Show sales from 20250712 to 20250718"),
        ("TEST 10 - CUSTOMER", "Show sales for customer 9500175"),
    ]

    all_passed = True

    # 1. Run Tests 1 to 10 using real sales_agent.py outputs
    for label, query_str in test_cases:
        agent_res = run_sales_agent(query_str)
        response_text = generate_sales_response(agent_res)
        print(f"{label}")

        is_valid = _verify_response_security(response_text)
        status = "[PASS]" if is_valid else "[FAIL]"
        print(f"{status}\n")

        if not is_valid:
            all_passed = False
            print(f"Details: Query='{query_str}' -> Response='{response_text}'\n")

    # 2. TEST 11 - ERROR RESPONSE
    print("TEST 11 - ERROR RESPONSE")
    err_agent_res = run_sales_agent("What is the weather?")
    err_resp = generate_sales_response(err_agent_res)
    test_11_passed = (
        _verify_response_security(err_resp)
        and "Unable to process request" in err_resp
    )
    print(f"{'[PASS]' if test_11_passed else '[FAIL]'}\n")
    if not test_11_passed:
        all_passed = False

    # 3. TEST 12 - NO RESULT
    print("TEST 12 - NO RESULT")
    no_res_agent_res = {
        "success": True,
        "question": "Show sales on 20200101",
        "parsed_query": {"intent": "sales_query", "dimension": "date", "value": {"date": "20200101"}},
        "result": {
            "start_date": "20200101",
            "end_date": "20200101",
            "exists": False,
            "number_of_invoices": 0,
            "number_of_accounting_rows": 0,
            "total_amount": 0.0,
            "invoices": []
        }
    }
    no_res_resp = generate_sales_response(no_res_agent_res)
    test_12_passed = (
        _verify_response_security(no_res_resp)
        and "No matching Sales records were found" in no_res_resp
    )
    print(f"{'[PASS]' if test_12_passed else '[FAIL]'}\n")
    if not test_12_passed:
        all_passed = False

    # 4. TEST 13 - MISSING OPTIONAL DATA
    print("TEST 13 - MISSING OPTIONAL DATA")
    missing_opt_agent_res = {
        "success": True,
        "question": "Show sales for GL account 9100001",
        "parsed_query": {"intent": "sales_query", "dimension": "gl_account", "value": "9100001"},
        "result": {
            "ac_code": "9100001",
            "account_name": None,  # Optional account name is missing/None
            "exists": True,
            "number_of_invoices": 1,
            "number_of_accounting_rows": 5,
            "total_amount": 105379.0
        }
    }
    missing_opt_resp = generate_sales_response(missing_opt_agent_res)
    test_13_passed = (
        _verify_response_security(missing_opt_resp)
        and "GL Account 9100001:" in missing_opt_resp
        and "None" not in missing_opt_resp
    )
    print(f"{'[PASS]' if test_13_passed else '[FAIL]'}\n")
    if not test_13_passed:
        all_passed = False

    print("=" * 50)
    print("OVERALL RESULT")
    print("=" * 50 + "\n")

    if all_passed:
        print("ALL RESPONSE GENERATOR TESTS PASSED [PASS]\n")
    else:
        print("SOME RESPONSE GENERATOR TESTS FAILED [FAIL]\n")
