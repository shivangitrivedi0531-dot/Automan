import os
import sys
from typing import Dict, Any

# Ensure project root directory is in sys.path for importing scripts and modules
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from fastapi import FastAPI, HTTPException, status
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field, field_validator

from scripts.general_agent import run_general_agent

# Initialize FastAPI application
app = FastAPI(
    title="General ERP Sales AI Agent API",
    description="REST API layer exposing general_agent.py for querying ERP Sales data.",
    version="1.0.0"
)

# Configure CORS middleware for local frontend requests
origins = [
    "http://127.0.0.1:5500",
    "http://localhost:5500",
    "http://127.0.0.1:8000",
    "http://localhost:8000",
    "http://127.0.0.1:8001",
    "http://localhost:8001",
]

app.add_middleware(
    CORSMiddleware,
    allow_origins=origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


class QueryRequest(BaseModel):
    question: str = Field(..., description="Natural language question about sales")

    @field_validator("question")
    @classmethod
    def validate_question(cls, v: str) -> str:
        if not isinstance(v, str) or not v.strip():
            raise ValueError("Field 'question' must be a non-empty string.")
        return v.strip()


@app.get("/health")
async def health_check() -> Dict[str, str]:
    """Health check endpoint."""
    return {"status": "ok"}


@app.post("/query")
async def query(request: QueryRequest) -> Dict[str, Any]:
    """
    General Sales AI Agent Query Endpoint.
    Passes user question to run_general_agent (scripts/general_agent.py).
    Returns structured agent response payload.
    """
    try:
        response = run_general_agent(request.question)
        return response
    except Exception:
        # Sanitize internal errors to prevent leaking credentials or stack traces
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="An internal error occurred while processing the sales query."
        )
