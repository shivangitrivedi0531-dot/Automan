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

from scripts.llm_query_parser import parse_sales_query
from scripts.entity_resolver import resolve_entity
from scripts.query_router import route_sales_query
from scripts.sales_response_generator import generate_sales_response, PROHIBITED_STRINGS


def run_agent(user_question: str) -> Dict[str, Any]:
    """
    Top-Level Sales AI Agent Orchestrator with Entity Resolution.

    Architecture Pipeline:
        User Question
             ↓
        LLM Query Parser (llm_query_parser.py)
             ↓
        Entity Resolver (entity_resolver.py)
             ↓
        Query Router (query_router.py)
             ↓
        Deterministic Database Query Functions (PostgreSQL)
             ↓
        Sales Response Generator (sales_response_generator.py)
             ↓
        Final Natural-Language Answer
    """
    # 1. Input Validation
    if not isinstance(user_question, str) or not user_question.strip():
        err_msg = "User question must be a non-empty string."
        err_dict = {
            "success": False,
            "question": user_question if isinstance(user_question, str) else str(user_question),
            "stage": "input_validation",
            "error": err_msg
        }
        answer_text = generate_sales_response(err_dict)
        return {
            "success": False,
            "question": err_dict["question"],
            "answer": answer_text,
            "stage": "input_validation",
            "error": err_msg
        }

    q_text = user_question.strip()

    # 2. Stage 1 — LLM Query Parser
    parser_res = parse_sales_query(q_text)
    if not isinstance(parser_res, dict) or not parser_res.get("success"):
        err_msg = parser_res.get("error") if isinstance(parser_res, dict) else "Unknown parser error."
        err_dict = {
            "success": False,
            "question": q_text,
            "stage": "parser",
            "error": err_msg
        }
        answer_text = generate_sales_response(err_dict)
        return {
            "success": False,
            "question": q_text,
            "answer": answer_text,
            "stage": "parser",
            "error": err_msg
        }

    # Extract initial parsed query structure
    raw_parsed_query = {
        "intent": parser_res.get("intent", "sales_query"),
        "dimension": parser_res.get("dimension"),
        "value": parser_res.get("value")
    }

    # 3. Stage 2 — Entity Resolver
    resolver_res = resolve_entity(raw_parsed_query)
    if not isinstance(resolver_res, dict) or not resolver_res.get("success"):
        err_msg = resolver_res.get("error") if isinstance(resolver_res, dict) else "Entity resolution error."
        err_dict = {
            "success": False,
            "question": q_text,
            "parsed_query": raw_parsed_query,
            "stage": "entity_resolver",
            "error": err_msg,
            "candidates": resolver_res.get("candidates") if isinstance(resolver_res, dict) else None
        }
        answer_text = generate_sales_response(err_dict)
        res_out = {
            "success": False,
            "question": q_text,
            "answer": answer_text,
            "stage": "entity_resolver",
            "error": err_msg
        }
        if isinstance(resolver_res, dict) and "candidates" in resolver_res:
            res_out["candidates"] = resolver_res["candidates"]
        return res_out

    # Resolved query object containing both resolved value and original input
    resolved_query = {
        "intent": resolver_res.get("intent", "sales_query"),
        "dimension": resolver_res.get("dimension"),
        "value": resolver_res.get("value"),
        "original_value": resolver_res.get("original_value")
    }

    # 4. Stage 3 — Query Router
    router_input = {
        "dimension": resolved_query["dimension"],
        "value": resolved_query["value"]
    }
    router_res = route_sales_query(router_input)
    if not isinstance(router_res, dict) or not router_res.get("success"):
        err_msg = router_res.get("error") if isinstance(router_res, dict) else "Query router execution error."
        err_dict = {
            "success": False,
            "question": q_text,
            "parsed_query": resolved_query,
            "stage": "router",
            "error": err_msg
        }
        answer_text = generate_sales_response(err_dict)
        return {
            "success": False,
            "question": q_text,
            "answer": answer_text,
            "stage": "router",
            "error": err_msg
        }

    # 5. Stage 4 — Sales Response Generator & Final Agent Output
    agent_result_payload = {
        "success": True,
        "question": q_text,
        "parsed_query": resolved_query,
        "result": router_res.get("result")
    }
    answer_text = generate_sales_response(agent_result_payload)

    return {
        "success": True,
        "question": q_text,
        "answer": answer_text,
        "parsed_query": resolved_query,
        "result": router_res.get("result")
    }


def _verify_security(res_obj: Dict[str, Any]) -> bool:
    """Security verification helper ensuring no SQL or credentials are leaked in response."""
    answer_text = str(res_obj.get("answer") or "")
    if not answer_text.strip():
        return False

    resp_upper = answer_text.upper()
    for kw in PROHIBITED_STRINGS:
        if kw in resp_upper:
            return False

    return True


if __name__ == "__main__":
    print("=" * 50)
    print("AGENT + ENTITY RESOLUTION INTEGRATION")
    print("=" * 50 + "\n")

    test_cases = [
        ("TEST 1 - JUPITER NAME → CODE → SALES", "Show me Jupiter sales", True),
        ("TEST 2 - CASE-INSENSITIVE PRODUCT", "Show me jupiter sales", True),
        ("TEST 3 - INVOICE", "Show sales for invoice 0000302", True),
        ("TEST 4 - EV", "Show EV sales", True),
        ("TEST 5 - NON-EV", "Show non EV sales", True),
        ("TEST 6 - FINANCIAL YEAR", "Show sales for financial year 2025-26", True),
        ("TEST 7 - VOUCHER SERIES", "Show sales for voucher series 0000001", True),
        ("TEST 8 - GL ACCOUNT", "Show sales for GL account 9100001", True),
        ("TEST 9 - SINGLE DATE", "Show sales on 20250711", True),
        ("TEST 10 - DATE RANGE", "Show sales from 20250712 to 20250718", True),
        ("TEST 11 - CUSTOMER", "Show sales for customer 9500175", True),
        ("TEST 12 - UNKNOWN PRODUCT", "Show me XYZ_UNKNOWN_PRODUCT sales", False),
        ("TEST 13 - AMBIGUOUS ENTITY", "Show sales for product APACHE", False),
        ("TEST 14 - NON-SALES QUESTION", "What is the weather?", False),
        ("TEST 15 - DESTRUCTIVE REQUEST", "Delete all sales", False),
        ("TEST 16 - SQL REQUEST", "Give me SQL for sales", False),
    ]

    all_tests_passed = True

    for label, query_str, exp_success in test_cases:
        res = run_agent(query_str)
        print(f"{label}")

        sec_ok = _verify_security(res)

        if exp_success:
            passed = (
                (res.get("success") is True)
                and isinstance(res.get("answer"), str)
                and (len(res["answer"].strip()) > 0)
                and isinstance(res.get("parsed_query"), dict)
                and isinstance(res.get("result"), dict)
                and sec_ok
            )
        else:
            passed = (
                (res.get("success") is False)
                and isinstance(res.get("answer"), str)
                and (len(res["answer"].strip()) > 0)
                and ("stage" in res)
                and ("error" in res)
                and sec_ok
            )

        status = "[PASS]" if passed else "[FAIL]"
        print(f"{status}\n")

        if not passed:
            all_tests_passed = False
            print(f"Details: Query='{query_str}' -> Result={res}\n")

    # CRITICAL REGRESSION TEST SECTION
    print("=" * 50)
    print("CRITICAL REGRESSION")
    print("=" * 50 + "\n")

    regression_diagram = """"Show me Jupiter sales"

LLM Parser
    ↓
JUPITER
    ↓
Entity Resolver
    ↓
0000026
    ↓
Query Router
    ↓
get_sale_by_product()
    ↓
Actual Jupiter sales"""

    print(regression_diagram)
    print()

    jup_res = run_agent("Show me Jupiter sales")
    reg_passed = (
        jup_res.get("success") is True
        and jup_res.get("parsed_query", {}).get("original_value") == "JUPITER"
        and jup_res.get("parsed_query", {}).get("value") == "0000026"
        and jup_res.get("result", {}).get("exists") is True
        and jup_res.get("result", {}).get("number_of_invoices") == 282
        and "Product code JUPITER not found" not in jup_res.get("answer", "")
    )

    reg_status = "[PASS]" if reg_passed else "[FAIL]"
    print(f"{reg_status}\n")

    if not reg_passed:
        all_tests_passed = False
        print(f"Regression Details: {jup_res}\n")

    print("=" * 50)
    print("OVERALL RESULT")
    print("=" * 50 + "\n")

    if all_tests_passed:
        print("ALL AGENT + ENTITY RESOLUTION TESTS PASSED [PASS]\n")
    else:
        print("SOME TESTS FAILED [FAIL]\n")
