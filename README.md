# leadflow

A small, testable lead-processing workflow: **signal in -> validate -> dedupe -> enrich -> score -> route -> output**.
Built as the engine behind a GTM automation (n8n / HubSpot layers come next).

## Run it

```bash
pip install -r requirements.txt          # only pytest, for the tests
python -m leadflow --input data/sample_leads.csv --existing data/existing_domains.txt --out out
python -m pytest -q
```

Use `--provider website` to enrich from real homepages instead of the offline mock.

## Outputs (`out/`)
- `processed.csv`: clean leads with `score`, `tier`, `owner`, and `score_reasons` (every point is explained)
- `errors.csv`: every rejected row with its line number, stage and a stable reason code
- `summary.json`: totals, success rate, errors by code, tier counts, retries used

## Rules

| Stage | Behaviour |
|---|---|
| Validate | Hard errors: missing company, missing/invalid domain, malformed email. Warnings (row continues, score adjusts): no email, free email provider, email domain differs from company domain, unparseable headcount |
| Dedupe | Against domains already in the CRM and earlier rows in the same file. Duplicates never reach the enrichment API |
| Enrich | Transient failures (timeouts, 5xx) retry up to 3 times with exponential backoff. "Not found" never retries. Input values win; enrichment only fills gaps |
| Score | 0-100, rule-based: target industry +30, team size up to +25, hiring +15, ecommerce +10, pricing page +5, business email +15, decision-maker title +15, free email -10 |
| Route | 80+ hot -> founder, 40-79 warm -> sdr, below 40 cold -> nurture |

## Failure paths
Nothing is dropped silently. Each failed row lands in `errors.csv` with where it failed
(`validate` / `dedupe` / `enrich`) and why.

## Next
1. n8n workflow: webhook/Sheet trigger -> this engine (HTTP) -> HubSpot create/update
2. Error-sheet + Slack summary
3. Loom demo and a reusable template/playbook

## Run it as an API
```bash
uvicorn leadflow.api:app --port 8000          # or: docker compose up --build
curl -s localhost:8000/process -H 'Content-Type: application/json' -d @n8n/test_payload.json
```
`POST /process` takes `{"leads": [...], "existing_domains": [...], "require_email": true}` and returns
`{"processed": [...], "errors": [...], "stats": {...}}`. Set `LEADFLOW_API_KEY` to require an `X-API-Key` header.
`require_email` defaults to true here because the HubSpot upsert is keyed on email, so rows without one
land in `errors` instead of failing inside n8n.

## n8n workflow (`n8n/leadflow.workflow.json`)
```
Webhook -> LeadFlow Engine (HTTP) -+-> Respond to Webhook (stats)
                                   +-> Split Processed -> HubSpot Upsert Contact (score, tier, owner)
                                   +-> Split Errors    -> Google Sheet "errors"
                                   +-> Slack summary (disabled by default)
```
Import it via n8n > Workflows > Import from file. The setup steps are in the sticky note on the canvas.
If n8n runs on n8n Cloud it cannot reach `localhost`: use docker compose, run n8n locally, or expose the engine with a tunnel.
