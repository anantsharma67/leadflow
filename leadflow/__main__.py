import argparse
import csv
import json
from pathlib import Path

from .enrich import MockEnricher, WebsiteEnricher
from .pipeline import run_pipeline
from .validate import normalize_domain

PROCESSED_FIELDS = [
    "company", "domain", "contact_name", "first_name", "last_name", "contact_title", "email", "industry",
    "employees", "signals", "score", "tier", "owner", "score_reasons",
    "warnings", "retries", "description",
]
ERROR_FIELDS = ["row", "company", "domain", "stage", "code", "message"]


def _write_csv(path, fields, rows):
    with open(path, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=fields, extrasaction="ignore")
        w.writeheader()
        w.writerows(rows)


def main():
    p = argparse.ArgumentParser(prog="leadflow")
    p.add_argument("--input", required=True, help="CSV of raw leads")
    p.add_argument("--existing", help="text file of domains already in the CRM, one per line")
    p.add_argument("--provider", choices=["mock", "website"], default="mock")
    p.add_argument("--mock-data", default="data/mock_enrichment.json")
    p.add_argument("--out", default="out")
    args = p.parse_args()

    with open(args.input, newline="", encoding="utf-8") as f:
        rows = list(csv.DictReader(f))
    existing = set()
    if args.existing:
        existing = {normalize_domain(l) for l in Path(args.existing).read_text().splitlines() if l.strip()}

    enricher = MockEnricher(args.mock_data) if args.provider == "mock" else WebsiteEnricher()
    result = run_pipeline(rows, enricher, existing_domains=existing)

    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    _write_csv(out / "processed.csv", PROCESSED_FIELDS, result.processed)
    _write_csv(out / "errors.csv", ERROR_FIELDS, result.errors)
    (out / "summary.json").write_text(json.dumps(result.stats, indent=2))
    print(json.dumps(result.stats, indent=2))


if __name__ == "__main__":
    main()
