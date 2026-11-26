# leadflow

A lead-processing workflow built the way a GTM implementation would be: **signal in -> validate -> dedupe -> enrich -> score -> route -> CRM**, with every failure explained instead of dropped.

Leads come in through a webhook. A Python engine cleans and scores them. n8n pushes the good ones into HubSpot with an owner assigned and logs every rejected row, with its reason, to a Google Sheet. It is a working reference build with 33 automated tests, not a shipped product.

Live engine health check (free tier, sleeps when idle, first call can take about a minute):
`https://leadflow-pn2o.onrender.com/health`

## Use case

GTM teams collect leads from forms, CSVs and enrichment exports, and the data is dirty: duplicates, malformed emails, missing domains. leadflow cleans a batch automatically. For example, a prospect list for an ad agency becomes scored HubSpot contacts, where hot leads go to the founder, warm leads to an SDR and the rest to nurture. Nothing disappears, because every reject lands in a sheet with the stage it failed at and why.

## Architecture

```
Webhook (leads) -> n8n -> Engine (Python / FastAPI on Render)
                            validate -> dedupe -> enrich (with retry) -> score -> route
                     <- { processed, errors, stats }

n8n then fans out:
  -> Respond to Webhook (stats)
  -> Split Processed -> HubSpot Upsert Contact (score, tier, owner)
  -> Split Errors    -> Google Sheet "errors"
  -> Slack summary (disabled by default)
```

The business rules live in tested code. n8n only wires the steps together, so someone who is not an engineer can change the flow without touching the logic.

## Tech stack

| Layer | Tools |
|---|---|
| Engine | Python, FastAPI, Uvicorn |
| Orchestration | n8n (webhook, HTTP request, split, HubSpot and Google Sheets nodes) |
| CRM | HubSpot (OAuth, custom contact properties) |
| Ops | Docker, Render, GitHub |
| Quality | pytest (33 tests), API-key authentication |

## Why this works as a GTM build

- **It follows the real loop.** Signal, rules, CRM action, then visible feedback.
- **Scores are explainable.** Every point is written into `score_reasons`, so an SDR can see why a lead scored 70 and trust it.
- **Failures are visible.** Each reject gets a row number, a stage and a reason code, so customers never wonder where a lead went.
- **It is reusable.** Rules, enrichment provider and CRM are separate pieces. Adapting it to another customer is mostly configuration.
- **It serves both audiences.** The engine and tests suit engineers. The n8n canvas and the error sheet suit operators.

## Sample run

On the bundled 13-row file in `data/` (made-up leads, not real customer data):
7 rows processed (4 hot, 3 warm) and 6 rejected, each with a stage and reason code:
`duplicate_in_batch`, `missing_domain`, `invalid_email`, `enrichment_not_found`, `duplicate_in_crm`, `invalid_domain`.
The retry path is exercised too: one sample lead fails twice and succeeds on the third attempt.

## Rules

| Stage | Behaviour |
|---|---|
| Validate | Hard errors: missing company, missing/invalid domain, malformed email. Warnings (row continues, score adjusts): no email, free email provider, email domain differs from company domain, unparseable headcount |
| Dedupe | Against domains already in the CRM and earlier rows in the same file. Duplicates never reach the enrichment API |
| Enrich | Transient failures (timeouts, 5xx) retry up to 3 times with exponential backoff. "Not found" never retries. Input values win; enrichment only fills gaps |
| Score | 0-100, rule-based: target industry +30, team size up to +25, hiring +15, ecommerce +10, pricing page +5, business email +15, decision-maker title +15, free email -10 |
| Route | 80+ hot -> founder, 40-79 warm -> sdr, below 40 cold -> nurture |

Nothing is dropped silently. Each failed row lands in `errors.csv` (or the Google Sheet in the n8n flow) with where it failed (`validate` / `dedupe` / `enrich`), why, and its row number in the source file.

## Run it locally

```bash
pip install -r requirements.txt
python -m leadflow --input data/sample_leads.csv --existing data/existing_domains.txt --out out
python -m pytest -q
```

Use `--provider website` to enrich from real homepages instead of the offline mock.

Outputs in `out/`:
- `processed.csv`: clean leads with `score`, `tier`, `owner` and `score_reasons`
- `errors.csv`: every rejected row with its line number, stage and reason code
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

## n8n setup (`n8n/leadflow.workflow.json`)

1. Import via n8n > Workflows > Import from file. Setup steps are in the sticky note on the canvas.
2. In **LeadFlow Engine**, set the URL to your deployed engine's `/process` and the `X-API-Key` header.
3. In HubSpot, create three contact properties: `leadflow_score` (number), `leadflow_tier` (text), `leadflow_owner` (text). Connect HubSpot credentials.
4. Google Sheets: a tab named `errors` with headers `row, company, domain, stage, code, message, logged_at`.
5. n8n Cloud cannot reach `localhost`, so deploy the engine (Dockerfile included) or tunnel to it. Free quick tunnels dropped repeatedly during testing, which is why the engine runs on Render.

## Known limitations

- The engine accepts any well-formed email. HubSpot additionally rejects reserved domains such as `.example`, so one sample lead fails at the CRM step. The fix is a reserved-domain rule in `validate.py`.
- HubSpot associates a contact with a company by email domain, so a contact on a subdomain (for example `mailer.adloop.co`) can land under a differently named company. The engine flags this as `email_domain_mismatch` and scores it down, but does not rewrite it.
- Enrichment in the default mode is a mock lookup; `--provider website` only reads homepage signals (hiring, ecommerce, pricing). A production version would plug a real enrichment provider into the same `lookup(domain)` interface.
- Results above come from sample data. It has not been run on real customer leads.
