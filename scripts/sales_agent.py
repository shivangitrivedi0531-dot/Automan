import os
import sys
from typing import Dict, Any

# Ensure sys.stdout handles UTF-8 formatting on Windows consoles
if hasattr(sys.stdout, "reconfigure"):
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass

# Ensure project root directory is in sys.path for importing scripts module
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

# Import parser and router components
from scripts.llm_query_parser import parse_sales_query
from scripts.query_router import route_sales_query


def run_sales_agent(user_question: str) -> Dict[str, Any]:
    """
    End-to-End Sales Agent Orchestrator.
    Connects:
        User Question
             ↓
        LLM Query Parser (llm_query_parser.py)
             ↓
        Structured Query
             ↓
        Query Router (query_router.py)
             ↓
        Validated Deterministic Sales Function
             ↓
        PostgreSQL
             ↓
        Result

    This orchestrator contains NO database logic directly.
    It delegates parsing to llm_query_parser and routing to query_router.
    """
    # 1. Input Validation
    if not isinstance(user_question, str) or not user_question.strip():
        return {
            "success": False,
            "question": user_question if isinstance(user_question, str) else str(user_question),
            "stage": "input_validation",
            "error": "User question must be a non-empty string."
        }

    q_text = user_question.strip()

    # 2. Stage 1 — LLM Query Parser
    parser_res = parse_sales_query(q_text)

    if not isinstance(parser_res, dict) or not parser_res.get("success"):
        err_msg = parser_res.get("error") if isinstance(parser_res, dict) else "Unknown parser error."
        return {
            "success": False,
            "question": q_text,
            "stage": "parser",
            "error": err_msg
        }

    # Extract parsed query details
    parsed_query = {
        "intent": parser_res.get("intent"),
        "dimension": parser_res.get("dimension"),
        "value": parser_res.get("value")
    }

    # 3. Stage 2 — Query Router
    # router expects dictionary with dimension and value
    router_input = {
        "dimension": parsed_query["dimension"],
        "value": parsed_query["value"]
    }
    router_res = route_sales_query(router_input)

    if not isinstance(router_res, dict) or not router_res.get("success"):
        err_msg = router_res.get("error") if isinstance(router_res, dict) else "Unknown router error."
        return {
            "success": False,
            "question": q_text,
            "parsed_query": parsed_query,
            "stage": "router",
            "error": err_msg
        }

    # 4. Stage 3 — Successful End-to-End Agent Response
    return {
        "success": True,
        "question": q_text,
        "parsed_query": parsed_query,
        "result": router_res.get("result")
    }


if __name__ == "__main__":
    print("=" * 50)
    print("SALES AGENT END-TO-END TEST")
    print("=" * 50 + "\n")

    test_queries = [
        ("TEST 1 - PRODUCT", "Show me Jupiter sales", True),
        ("TEST 2 - INVOICE", "Show sales for invoice 0000302", True),
        ("TEST 3 - EV", "Show EV sales", True),
        ("TEST 4 - NON-EV", "Show non EV sales", True),
        ("TEST 5 - FINANCIAL YEAR", "Show sales for financial year 2025-26", True),
        ("TEST 6 - SERIES", "Show sales for voucher series 0000001", True),
        ("TEST 7 - GL ACCOUNT", "Show sales for GL account 9100001", True),
        ("TEST 8 - SINGLE DATE", "Show sales on 20250711", True),
        ("TEST 9 - DATE RANGE", "Show sales from 20250712 to 20250718", True),
        ("TEST 10 - CUSTOMER", "Show sales for customer 9500175", True),
        ("TEST 11 - NON-SALES QUESTION", "What is the weather?", False),
        ("TEST 12 - DESTRUCTIVE REQUEST", "Delete all sales", False),
        ("TEST 13 - SQL REQUEST", "Give me SQL for sales", False),
    ]

    all_tests_passed = True
    pipeline_integrity_passed = True

    for label, query_str, exp_success in test_queries:
        res = run_sales_agent(query_str)
        print(f"{label}")

        if exp_success:
            # Expected end-to-end success
            passed = (
                (res.get("success") is True)
                and ("parsed_query" in res)
                and ("result" in res)
                and (res.get("parsed_query", {}).get("intent") == "sales_query")
            )
        else:
            # Expected rejection at parser stage (must not reach router)
            passed = (
                (res.get("success") is False)
                and (res.get("stage") == "parser")
                and ("error" in res)
                and ("parsed_query" not in res)
            )
            # Extra verification: ensure rejected query did NOT create a router parsed_query response
            if "parsed_query" in res:
                passed = False

        status = "[PASS]" if passed else "[FAIL]"
        print(f"{status}\n")

        if not passed:
            all_tests_passed = False
            print(f"Details: Query='{query_str}' -> Result={res}\n")

    print("=" * 50)
    print("PIPELINE")
    print("=" * 50 + "\n")

    # Verify pipeline contract:
    # 1. Successful queries pass Parser -> Router -> Deterministic Query
    # 2. Invalid/unsafe queries are blocked at Parser step and never reach Router
    sample_success = run_sales_agent("Show EV sales")
    sample_blocked = run_sales_agent("Give me SQL for sales")

    pipeline_ok = (
        sample_success.get("success") is True
        and sample_success.get("parsed_query", {}).get("dimension") == "ev"
        and "result" in sample_success
        and sample_blocked.get("success") is False
        and sample_blocked.get("stage") == "parser"
        and "parsed_query" not in sample_blocked
    )

    pipeline_status = "[PASS]" if pipeline_ok else "[FAIL]"
    print("LLM PARSER → QUERY ROUTER → DETERMINISTIC SALES QUERY")
    print(f"{pipeline_status}\n")

    if not pipeline_ok:
        pipeline_integrity_passed = False

    print("=" * 50)
    print("OVERALL RESULT")
    print("=" * 50 + "\n")

    if all_tests_passed and pipeline_integrity_passed:
        print("ALL SALES AGENT TESTS PASSED [PASS]\n")
    else:
        print("SOME SALES AGENT TESTS FAILED [FAIL]\n")
