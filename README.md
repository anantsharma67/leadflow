# leadflow

A lead-processing workflow built the way a GTM implementation would be: **signal in -> validate -> dedupe -> enrich -> score -> route -> CRM**, with every failure explained instead of dropped.

- **Engine:** Python (FastAPI), deployed on Render
- **Orchestration:** n8n (webhook trigger, HubSpot upsert, Google Sheets error log)
- **CRM:** HubSpot contacts carry `leadflow_score`, `leadflow_tier` and `leadflow_owner`
- **Quality:** 33 automated tests

```
Webhook -> LeadFlow Engine (HTTP) -+-> Respond to Webhook (stats)
                                   +-> Split Processed -> HubSpot Upsert Contact (score, tier, owner)
                                   +-> Split Errors    -> Google Sheet "errors"
                                   +-> Slack summary (disabled by default)
```

Live engine health check (free tier, sleeps when idle, first call can take about a minute):
`https://leadflow-pn2o.onrender.com/health`

## Sample run

On the bundled 13-row file in `data/` (made-up leads, not real customer data):
7 rows processed (4 hot, 3 warm), 6 rejected, each with a stage and reason code:
`duplicate_in_batch`, `missing_domain`, `invalid_email`, `enrichment_not_found`, `duplicate_in_crm`, `invalid_domain`.
The retry path is exercised too: one sample lead fails twice and succeeds on the third attempt.

## Run it locally

```bash
pip install -r requirements.txt
python -m leadflow --input data/sample_leads.csv --existing data/existing_domains.txt --out out
python -m pytest -q
```

Use `--provider website` to enrich from real homepages instead of the offline mock.

Outputs in `out/`:
- `processed.csv`: clean leads with `score`, `tier`, `owner` and `score_reasons` (every point is explained)
- `errors.csv`: every rejected row with its line number, stage and a stable reason code
- `summary.json`: totals, success rate, errors by code, tier counts, retries used

## Run it as an API

```bash
uvicorn leadflow.api:app --port 8000          # or: docker compose up --build
curl -s localhost:8000/process -H 'Content-Type: application/json' -d @n8n/test_payload.json
```

`POST /process` takes `{"leads": [...], "existing_domains": [...], "require_email": true}` and returns
`{"processed": [...], "errors": [...], "stats": {...}}`.
Set `LEADFLOW_API_KEY` to require an `X-API-Key` header. `LEADFLOW_PROVIDER` is `mock` (default) or `website`.
`require_email` defaults to true because the HubSpot upsert is keyed on email, so rows without one land in `errors` instead of failing inside n8n.

## Rules

| Stage | Behaviour |
|---|---|
| Validate | Hard errors: missing company, missing/invalid domain, malformed email. Warnings (row continues, score adjusts): no email, free email provider, email domain differs from company domain, unparseable headcount |
| Dedupe | Against domains already in the CRM and earlier rows in the same file. Duplicates never reach the enrichment API |
| Enrich | Transient failures (timeouts, 5xx) retry up to 3 times with exponential backoff. "Not found" never retries. Input values win; enrichment only fills gaps |
| Score | 0-100, rule-based: target industry +30, team size up to +25, hiring +15, ecommerce +10, pricing page +5, business email +15, decision-maker title +15, free email -10 |
| Route | 80+ hot -> founder, 40-79 warm -> sdr, below 40 cold -> nurture |

## Failure paths

Nothing is dropped silently. Each failed row lands in `errors.csv` (or the Google Sheet in the n8n flow) with where it failed (`validate` / `dedupe` / `enrich`), why, and its row number in the source file.

## n8n setup (`n8n/leadflow.workflow.json`)

1. Import via n8n > Workflows > Import from file. Setup steps are in the sticky note on the canvas.
2. In **LeadFlow Engine**, set the URL to your deployed engine's `/process` and the `X-API-Key` header.
3. In HubSpot, create three contact properties: `leadflow_score` (number), `leadflow_tier` (text), `leadflow_owner` (text). Connect HubSpot credentials.
4. Google Sheets: a tab named `errors` with headers `row, company, domain, stage, code, message, logged_at`.
5. n8n Cloud cannot reach `localhost`, so deploy the engine (Dockerfile included) or tunnel to it.

## Known limitations

- The engine accepts any well-formed email. HubSpot additionally rejects reserved domains such as `.example`, so one sample lead fails at the CRM step. The fix is a reserved-domain rule in `validate.py`.
- HubSpot associates a contact with a company by email domain, so a contact on a subdomain (for example `mailer.adloop.co`) can land under a differently named company. The engine flags this as `email_domain_mismatch` and scores it down, but does not rewrite it.
- Enrichment in the default mode is a mock lookup; `--provider website` only reads homepage signals (hiring, ecommerce, pricing). A production version would plug a real enrichment provider into the same `lookup(domain)` interface.
