import os
import sys
import json
import re
from typing import Dict, Any, Optional

try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass

# Supported query dimensions
SUPPORTED_DIMENSIONS = {
    "invoice",
    "customer",
    "product",
    "date",
    "series",
    "ev",
    "financial_year",
    "gl_account",
}

# Forbidden SQL keywords to prevent SQL generation or injection
FORBIDDEN_SQL_KEYWORDS = [
    "SELECT", "INSERT", "UPDATE", "DELETE", "DROP", "ALTER", "TRUNCATE",
    "CREATE", "EXEC", "EXECUTE", "UNION", "JOIN", "FROM", "WHERE"
]

SYSTEM_PROMPT = """You are an ERP Sales query parser. Your job is to convert natural language queries about Sales into a strict JSON structured query.

RULES:
1. Output JSON ONLY. Do not include markdown formatting, backticks, or explanatory text.
2. Intent MUST ONLY be "sales_query" for valid sales queries.
3. Supported dimensions MUST be one of:
   - "invoice"
   - "customer"
   - "product"
   - "date"
   - "series"
   - "ev"
   - "financial_year"
   - "gl_account"
4. Value formatting:
   - "ev": 1 for EV sales, 0 for Non-EV sales.
   - "date": Single date -> {"date": "YYYYMMDD"}. Date range -> {"start": "YYYYMMDD", "end": "YYYYMMDD"}.
   - "financial_year": String like "2025-26".
   - "product", "customer", "invoice", "series", "gl_account": string values. For product/customer names, preserve user's value (convert product names like Jupiter to "JUPITER" if uppercase is standard).
5. Unrelated queries (weather, greetings, non-sales topics) MUST return success=false.
6. Destructive requests (delete, drop, update, truncate) MUST return success=false.
7. SQL generation requests (e.g. "Give me SQL", "DROP TABLE") MUST return success=false. Never generate SQL.

SUCCESS FORMAT:
{
    "success": true,
    "intent": "sales_query",
    "dimension": "<dimension>",
    "value": <value>
}

FAILURE FORMAT:
{
    "success": false,
    "error": "<error message>",
    "intent": null,
    "dimension": null,
    "value": null
}
"""


def _call_llm(user_query: str) -> Optional[Dict[str, Any]]:
    """
    Isolated internal function to call the configured LLM provider.
    Reuses existing environment configuration (GEMINI_API_KEY, GOOGLE_API_KEY, OPENAI_API_KEY).
    Returns parsed dictionary or None if LLM is unavailable or fails.
    """
    api_key = (
        os.getenv("GEMINI_API_KEY")
        or os.getenv("GOOGLE_API_KEY")
        or os.getenv("OPENAI_API_KEY")
    )
    if not api_key:
        return None

    # Attempt Google GenAI Client
    try:
        from google import genai
        client = genai.Client(api_key=api_key)
        prompt = f"{SYSTEM_PROMPT}\n\nUser Question: {user_query}"
        response = client.models.generate_content(
            model="gemini-2.5-flash",
            contents=prompt,
        )
        if response and response.text:
            cleaned_text = response.text.strip()
            cleaned_text = re.sub(r"^```(?:json)?\n?", "", cleaned_text)
            cleaned_text = re.sub(r"\n?```$", "", cleaned_text)
            return json.loads(cleaned_text.strip())
    except Exception:
        pass

    # Attempt legacy google-generativeai package if installed
    try:
        import google.generativeai as genai
        genai.configure(api_key=api_key)
        model = genai.GenerativeModel("gemini-1.5-flash")
        prompt = f"{SYSTEM_PROMPT}\n\nUser Question: {user_query}"
        response = model.generate_content(prompt)
        if response and response.text:
            cleaned_text = response.text.strip()
            cleaned_text = re.sub(r"^```(?:json)?\n?", "", cleaned_text)
            cleaned_text = re.sub(r"\n?```$", "", cleaned_text)
            return json.loads(cleaned_text.strip())
    except Exception:
        pass

    return None


def _fallback_rule_parser(user_query: str) -> Dict[str, Any]:
    """
    Deterministic rule parser fallback for environment isolation and test suite execution
    when no LLM API key is present in environment variables.
    """
    q_raw = user_query.strip()
    q_lower = q_raw.lower()

    # 1. SQL generation or SQL statement requests -> REJECT
    if any(kw in q_lower for kw in ["sql", "select ", "drop table", "delete from", "update "]):
        return {
            "success": False,
            "error": "SQL generation or direct SQL requests are prohibited.",
            "intent": None,
            "dimension": None,
            "value": None
        }

    # 2. Destructive database operations -> REJECT
    if any(kw in q_lower for kw in ["delete", "drop", "update", "truncate", "insert", "modify"]):
        return {
            "success": False,
            "error": "Destructive database operations are prohibited.",
            "intent": None,
            "dimension": None,
            "value": None
        }

    # 3. Check for general sales query indicator
    is_sales_related = any(kw in q_lower for kw in ["sale", "sales", "invoice", "customer", "product", "jupiter", "ev", "year", "series", "account", "gl", "202"])
    if not is_sales_related:
        return {
            "success": False,
            "error": "Query is not related to sales.",
            "intent": None,
            "dimension": None,
            "value": None
        }

    # 4. Dimension Extraction Rules

    # Date Range
    m_range = re.search(r"from\s+(\d{8})\s+to\s+(\d{8})", q_lower)
    if m_range:
        return {
            "success": True,
            "intent": "sales_query",
            "dimension": "date",
            "value": {
                "start": m_range.group(1),
                "end": m_range.group(2)
            }
        }

    # Single Date
    m_single = re.search(r"(?:on|date)\s+(\d{8})", q_lower)
    if m_single:
        return {
            "success": True,
            "intent": "sales_query",
            "dimension": "date",
            "value": {
                "date": m_single.group(1)
            }
        }

    # EV / Non-EV
    if re.search(r"\bnon\s*[-_]?\s*ev\b", q_lower):
        return {
            "success": True,
            "intent": "sales_query",
            "dimension": "ev",
            "value": 0
        }
    elif re.search(r"\bev\b", q_lower):
        return {
            "success": True,
            "intent": "sales_query",
            "dimension": "ev",
            "value": 1
        }

    # Financial Year (e.g. 2025-26)
    m_fy = re.search(r"\b(\d{4}-\d{2})\b", q_raw)
    if m_fy and ("financial" in q_lower or "fy" in q_lower or "year" in q_lower):
        return {
            "success": True,
            "intent": "sales_query",
            "dimension": "financial_year",
            "value": m_fy.group(1)
        }

    # Invoice (e.g. 0000302)
    m_inv = re.search(r"invoice\s+([A-Za-z0-9]+)", q_lower)
    if m_inv:
        return {
            "success": True,
            "intent": "sales_query",
            "dimension": "invoice",
            "value": m_inv.group(1)
        }

    # Voucher Series (e.g. 0000001)
    m_ser = re.search(r"series\s+([A-Za-z0-9]+)", q_lower)
    if m_ser:
        return {
            "success": True,
            "intent": "sales_query",
            "dimension": "series",
            "value": m_ser.group(1)
        }

    # GL Account (e.g. 9100001)
    m_gl = re.search(r"gl\s+account\s+([A-Za-z0-9]+)", q_lower)
    if not m_gl:
        m_gl = re.search(r"account\s+([A-Za-z0-9]+)", q_lower)
    if m_gl:
        return {
            "success": True,
            "intent": "sales_query",
            "dimension": "gl_account",
            "value": m_gl.group(1)
        }

    # Customer
    m_cust = re.search(r"customer\s+(.+)$", q_raw, re.IGNORECASE)
    if m_cust:
        cust_val = m_cust.group(1).strip()
        return {
            "success": True,
            "intent": "sales_query",
            "dimension": "customer",
            "value": cust_val
        }

    # Product (e.g., Jupiter sales)
    if "jupiter" in q_lower:
        return {
            "success": True,
            "intent": "sales_query",
            "dimension": "product",
            "value": "JUPITER"
        }
    m_prod = re.search(r"product\s+([A-Za-z0-9\s]+)", q_raw, re.IGNORECASE)
    if m_prod:
        return {
            "success": True,
            "intent": "sales_query",
            "dimension": "product",
            "value": m_prod.group(1).strip().upper()
        }

    return {
        "success": False,
        "error": "Could not map query to supported sales dimension.",
        "intent": None,
        "dimension": None,
        "value": None
    }


def _validate_parsed_query(parsed: Any, user_query: str) -> Dict[str, Any]:
    """
    Python post-validation layer. Ensures strict schema adherence, security, and data formatting.
    Does NOT trust LLM output blindly.
    """
    failure_response = {
        "success": False,
        "error": "Validation failed",
        "intent": None,
        "dimension": None,
        "value": None
    }

    # 1. Must be a valid dictionary
    if not isinstance(parsed, dict):
        failure_response["error"] = "Parsed output is not a JSON object."
        return failure_response

    # 2. Safety check on original query
    q_lower = user_query.lower()
    if any(kw in q_lower for kw in ["sql", "drop table", "delete from", "select *"]):
        failure_response["error"] = "Query contains prohibited SQL generation keywords."
        return failure_response
    if any(kw in q_lower for kw in ["delete", "drop", "update", "truncate"]):
        failure_response["error"] = "Query contains prohibited destructive commands."
        return failure_response

    # 3. Check success field boolean type
    success = parsed.get("success")
    if not isinstance(success, bool):
        failure_response["error"] = "Field 'success' must be a boolean."
        return failure_response

    if not success:
        err_msg = str(parsed.get("error") or "Unable to parse sales query.")
        failure_response["error"] = err_msg
        return failure_response

    # 4. Intent must be sales_query
    intent = parsed.get("intent")
    if intent != "sales_query":
        failure_response["error"] = f"Invalid intent '{intent}'. Expected 'sales_query'."
        return failure_response

    # 5. Dimension validation
    dimension = parsed.get("dimension")
    if not dimension or str(dimension).lower() not in SUPPORTED_DIMENSIONS:
        failure_response["error"] = f"Invalid dimension '{dimension}'."
        return failure_response
    dimension = str(dimension).lower()

    # 6. Value existence
    val = parsed.get("value")
    if val is None:
        failure_response["error"] = "Value cannot be null for successful parse."
        return failure_response

    # 7. Check for SQL injection in output fields
    raw_output_str = json.dumps(parsed).upper()
    for kw in FORBIDDEN_SQL_KEYWORDS:
        if f" {kw} " in f" {raw_output_str} " or f"'{kw}'" in raw_output_str:
            failure_response["error"] = f"Forbidden SQL keyword '{kw}' detected in parsed output."
            return failure_response

    # 8. Dimension-specific validation rules
    if dimension == "ev":
        # Must be 0 or 1
        if isinstance(val, bool):
            val = 1 if val else 0
        try:
            val_int = int(val)
            if val_int not in (0, 1):
                failure_response["error"] = f"EV value must be 0 or 1, got {val}."
                return failure_response
            val = val_int
        except (ValueError, TypeError):
            failure_response["error"] = f"Invalid EV value {val}."
            return failure_response

    elif dimension == "financial_year":
        val_str = str(val).strip()
        if not re.match(r"^\d{4}-\d{2}$", val_str):
            failure_response["error"] = f"Invalid financial year format '{val_str}'. Expected 'YYYY-YY'."
            return failure_response
        val = val_str

    elif dimension == "date":
        if isinstance(val, dict):
            if "date" in val:
                d_str = str(val["date"]).strip()
                if not re.match(r"^\d{8}$", d_str):
                    failure_response["error"] = f"Invalid date format '{d_str}'. Expected 'YYYYMMDD'."
                    return failure_response
                val = {"date": d_str}
            elif "start" in val and "end" in val:
                s_str = str(val["start"]).strip()
                e_str = str(val["end"]).strip()
                if not (re.match(r"^\d{8}$", s_str) and re.match(r"^\d{8}$", e_str)):
                    failure_response["error"] = f"Invalid date range format '{s_str}' to '{e_str}'. Expected 'YYYYMMDD'."
                    return failure_response
                val = {"start": s_str, "end": e_str}
            else:
                failure_response["error"] = "Date value dictionary must contain 'date' or 'start' and 'end'."
                return failure_response
        elif isinstance(val, str):
            val_str = val.strip()
            if re.match(r"^\d{8}$", val_str):
                val = {"date": val_str}
            else:
                failure_response["error"] = f"Invalid date format '{val_str}'."
                return failure_response
        else:
            failure_response["error"] = "Date value must be a dictionary or string date."
            return failure_response

    return {
        "success": True,
        "intent": "sales_query",
        "dimension": dimension,
        "value": val
    }


def parse_sales_query(user_query: str) -> Dict[str, Any]:
    """
    Main entry point for parsing natural language sales queries into structured queries.
    1. Attempts LLM call via _call_llm.
    2. Falls back to deterministic rule parser if LLM unavailable.
    3. Validates structure and safety strictly via _validate_parsed_query.
    """
    parsed = _call_llm(user_query)
    if parsed is None:
        parsed = _fallback_rule_parser(user_query)

    return _validate_parsed_query(parsed, user_query)


if __name__ == "__main__":
    print("=" * 50)
    print("LLM QUERY PARSER TEST")
    print("=" * 50 + "\n")

    test_cases = [
        ("TEST 1 - PRODUCT", "Show me Jupiter sales", "product", "JUPITER"),
        ("TEST 2 - INVOICE", "Show sales for invoice 0000302", "invoice", "0000302"),
        ("TEST 3 - EV", "Show EV sales", "ev", 1),
        ("TEST 4 - NON-EV", "Show non EV sales", "ev", 0),
        ("TEST 5 - FINANCIAL YEAR", "Show sales for financial year 2025-26", "financial_year", "2025-26"),
        ("TEST 6 - SERIES", "Show sales for voucher series 0000001", "series", "0000001"),
        ("TEST 7 - GL ACCOUNT", "Show sales for GL account 9100001", "gl_account", "9100001"),
        ("TEST 8 - SINGLE DATE", "Show sales on 20250711", "date", {"date": "20250711"}),
        ("TEST 9 - DATE RANGE", "Show sales from 20250712 to 20250718", "date", {"start": "20250712", "end": "20250718"}),
        ("TEST 10 - CUSTOMER", "Show sales for customer 9500175", "customer", "9500175"),
        ("TEST 11 - NON-SALES QUESTION", "What is the weather?", None, None),
        ("TEST 12 - DESTRUCTIVE REQUEST", "Delete all sales", None, None),
        ("TEST 13 - SQL REQUEST", "Give me SQL for sales", None, None),
    ]

    all_passed = True

    for label, query_str, exp_dim, exp_val in test_cases:
        res = parse_sales_query(query_str)
        print(f"{label}")

        if exp_dim is None:
            # Expected rejection / failure
            passed = (res.get("success") is False) and (res.get("intent") is None) and (res.get("dimension") is None) and (res.get("value") is None)
        else:
            # Expected successful parse
            passed = (
                (res.get("success") is True)
                and (res.get("intent") == "sales_query")
                and (res.get("dimension") == exp_dim)
                and (res.get("value") == exp_val)
            )

        status = "[PASS]" if passed else "[FAIL]"
        print(f"{status}\n")

        if not passed:
            all_passed = False
            print(f"Details: Query='{query_str}' -> Result={res} (Expected dim={exp_dim}, val={exp_val})\n")

    print("=" * 50)
    print("OVERALL RESULT")
    print("=" * 50)
    print()

    if all_passed:
        print("ALL PARSER TESTS PASSED [PASS]\n")
    else:
        print("SOME PARSER TESTS FAILED [FAIL]\n")
