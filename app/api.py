import os
import sys
from typing import Dict, Any

# Ensure project root directory is in sys.path for importing scripts and modules
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from fastapi import FastAPI, HTTPException, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field, field_validator

from scripts.agent import run_agent

# Initialize FastAPI application
app = FastAPI(
    title="ERP Sales AI Agent",
    description="REST API layer for querying ERP Sales data using deterministic logic and LLM natural language parsing.",
    version="1.0.0"
)

# Configure CORS middleware for local frontend requests
origins = [
    "http://127.0.0.1:5500",
    "http://localhost:5500",
    "http://127.0.0.1:8000",
    "http://localhost:8000",
]

app.add_middleware(
    CORSMiddleware,
    allow_origins=origins,
    allow_credentials=True,
    allow_methods=["GET", "POST", "OPTIONS"],
    allow_headers=["*"],
)


class ChatRequest(BaseModel):
    message: str = Field(..., description="Natural language question about sales")

    @field_validator("message")
    @classmethod
    def validate_message(cls, v: str) -> str:
        if not isinstance(v, str) or not v.strip():
            raise ValueError("Field 'message' must be a non-empty string.")
        return v.strip()


@app.get("/health")
async def health_check() -> Dict[str, str]:
    """Health check endpoint. Does not query database directly."""
    return {
        "status": "ok",
        "service": "sales-ai-agent"
    }


@app.post("/api/chat")
async def chat(request: ChatRequest) -> Dict[str, Any]:
    """
    Sales AI Chat Endpoint.
    Passes user question to top-level sales agent (scripts/agent.py).
    Returns controlled agent response object.
    """
    try:
        response = run_agent(request.message)
        return response
    except Exception:
        # Sanitize internal errors to prevent leaking credentials or stack traces
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="An internal error occurred while processing the sales request."
        )


if __name__ == "__main__":
    print("=" * 50)
    print("FASTAPI API VALIDATION")
    print("=" * 50 + "\n")

    all_passed = True

    try:
        from fastapi.testclient import TestClient
        client = TestClient(app)
    except Exception as e:
        print(f"Failed to initialize TestClient: {e}")
        sys.exit(1)

    # TEST 1 - APP IMPORT
    print("TEST 1 - APP IMPORT")
    t1_pass = isinstance(app, FastAPI) and app.title == "ERP Sales AI Agent"
    print(f"{'[PASS]' if t1_pass else '[FAIL]'}\n")
    if not t1_pass: all_passed = False

    # TEST 2 - HEALTH ENDPOINT
    print("TEST 2 - HEALTH ENDPOINT")
    h_res = client.get("/health")
    t2_pass = (h_res.status_code == 200) and (h_res.json() == {"status": "ok", "service": "sales-ai-agent"})
    print(f"{'[PASS]' if t2_pass else '[FAIL]'}\n")
    if not t2_pass: all_passed = False

    # TEST 3 - CHAT ROUTE
    print("TEST 3 - CHAT ROUTE")
    routes = [r.path for r in app.routes]
    t3_pass = "/api/chat" in routes and "/health" in routes
    print(f"{'[PASS]' if t3_pass else '[FAIL]'}\n")
    if not t3_pass: all_passed = False

    # TEST 4 - REQUEST VALIDATION
    print("TEST 4 - REQUEST VALIDATION")
    v_res1 = client.post("/api/chat", json={})
    v_res2 = client.post("/api/chat", json={"message": "   "})
    t4_pass = (v_res1.status_code == 422) and (v_res2.status_code == 422)
    print(f"{'[PASS]' if t4_pass else '[FAIL]'}\n")
    if not t4_pass: all_passed = False

    # TEST 5 - PRODUCT SALES REQUEST
    print("TEST 5 - PRODUCT SALES REQUEST")
    p_res = client.post("/api/chat", json={"message": "Show me Jupiter sales"})
    p_data = p_res.json() if p_res.status_code == 200 else {}
    t5_pass = (p_res.status_code == 200) and (p_data.get("success") is True) and ("answer" in p_data) and ("parsed_query" in p_data)
    print(f"{'[PASS]' if t5_pass else '[FAIL]'}\n")
    if not t5_pass: all_passed = False

    # TEST 6 - NON-SALES REQUEST
    print("TEST 6 - NON-SALES REQUEST")
    n_res = client.post("/api/chat", json={"message": "What is the weather?"})
    n_data = n_res.json() if n_res.status_code == 200 else {}
    t6_pass = (n_res.status_code == 200) and (n_data.get("success") is False) and (n_data.get("stage") == "parser")
    print(f"{'[PASS]' if t6_pass else '[FAIL]'}\n")
    if not t6_pass: all_passed = False

    # TEST 7 - DESTRUCTIVE REQUEST
    print("TEST 7 - DESTRUCTIVE REQUEST")
    d_res = client.post("/api/chat", json={"message": "Delete all sales"})
    d_data = d_res.json() if d_res.status_code == 200 else {}
    t7_pass = (d_res.status_code == 200) and (d_data.get("success") is False) and (d_data.get("stage") == "parser")
    print(f"{'[PASS]' if t7_pass else '[FAIL]'}\n")
    if not t7_pass: all_passed = False

    # TEST 8 - SQL REQUEST
    print("TEST 8 - SQL REQUEST")
    s_res = client.post("/api/chat", json={"message": "Give me SQL for sales"})
    s_data = s_res.json() if s_res.status_code == 200 else {}
    t8_pass = (s_res.status_code == 200) and (s_data.get("success") is False) and (s_data.get("stage") == "parser")
    print(f"{'[PASS]' if t8_pass else '[FAIL]'}\n")
    if not t8_pass: all_passed = False

    print("=" * 50)
    print("OVERALL RESULT")
    print("=" * 50 + "\n")

    if all_passed:
        print("ALL FASTAPI TESTS PASSED [PASS]\n")
    else:
        print("SOME FASTAPI TESTS FAILED [FAIL]\n")
