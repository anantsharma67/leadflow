"""HTTP wrapper so n8n (or anything else) can call the engine.

POST /process  {"leads": [...], "existing_domains": [...], "require_email": true}
GET  /health

Env: LEADFLOW_API_KEY (if set, requests need an X-API-Key header),
     LEADFLOW_PROVIDER = mock | website (default mock),
     LEADFLOW_MOCK_DATA = path to the mock enrichment JSON.
"""
import os
from pathlib import Path

from fastapi import FastAPI, Header, HTTPException
from pydantic import BaseModel, Field

from .enrich import MockEnricher, WebsiteEnricher
from .pipeline import run_pipeline
from .validate import normalize_domain

MAX_LEADS = 500
API_KEY = os.getenv("LEADFLOW_API_KEY", "")
PROVIDER = os.getenv("LEADFLOW_PROVIDER", "mock")
MOCK_DATA = os.getenv(
    "LEADFLOW_MOCK_DATA",
    str(Path(__file__).resolve().parent.parent / "data" / "mock_enrichment.json"),
)

app = FastAPI(title="leadflow", version="0.1.0")
_enricher = WebsiteEnricher() if PROVIDER == "website" else MockEnricher(MOCK_DATA)


class ProcessRequest(BaseModel):
    leads: list[dict]
    existing_domains: list[str] = Field(default_factory=list)
    # n8n's HubSpot upsert is keyed on email, so default to rejecting rows without one
    require_email: bool = True


@app.get("/health")
def health():
    return {"status": "ok", "provider": PROVIDER}


@app.post("/process")
def process(req: ProcessRequest, x_api_key: str | None = Header(default=None)):
    if API_KEY and x_api_key != API_KEY:
        raise HTTPException(status_code=401, detail="invalid API key")
    if len(req.leads) > MAX_LEADS:
        raise HTTPException(status_code=413, detail=f"max {MAX_LEADS} leads per request")
    existing = {normalize_domain(d) for d in req.existing_domains if d}
    result = run_pipeline(
        req.leads, _enricher, existing_domains=existing,
        require_email=req.require_email, first_line=1,  # "row" = position in the request
    )
    return {"processed": result.processed, "errors": result.errors, "stats": result.stats}
