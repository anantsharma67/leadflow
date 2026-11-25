import time
from collections import Counter
from dataclasses import dataclass, field

from .enrich import EnrichmentNotFound, TransientEnrichmentError, with_retry
from .score import score_lead
from .validate import ValidationError, validate_row


@dataclass
class PipelineResult:
    processed: list = field(default_factory=list)
    errors: list = field(default_factory=list)
    stats: dict = field(default_factory=dict)


def _merge(lead, enriched):
    """Input values win; enrichment only fills gaps."""
    merged = dict(lead)
    for key in ("industry", "employees"):
        if not merged.get(key) and enriched.get(key):
            merged[key] = enriched[key]
    merged["signals"] = list(enriched.get("signals") or [])
    merged["description"] = enriched.get("description", "")
    return merged


def run_pipeline(rows, enricher, existing_domains=(), sleep=time.sleep, max_attempts=3,
                 require_email=False, first_line=2):
    """rows: list of dicts (CSV rows). existing_domains: domains already in the CRM."""
    result = PipelineResult()
    in_crm = set(existing_domains)
    seen_in_batch = set()
    total_retries = 0

    def fail(line, row, stage, code, message):
        result.errors.append({
            "row": line,
            "company": str(row.get("company") or "").strip(),
            "domain": str(row.get("domain") or "").strip(),
            "stage": stage,
            "code": code,
            "message": message,
        })

    for line, row in enumerate(rows, start=first_line):  # CSV: line 1 is the header
        try:
            lead, warnings = validate_row(row, require_email=require_email)
        except ValidationError as e:
            fail(line, row, "validate", e.code, e.message)
            continue

        if lead["domain"] in in_crm:
            fail(line, row, "dedupe", "duplicate_in_crm", f"{lead['domain']} already in CRM")
            continue
        if lead["domain"] in seen_in_batch:
            fail(line, row, "dedupe", "duplicate_in_batch", f"{lead['domain']} appears earlier in this file")
            continue

        try:
            enriched, retries = with_retry(
                lambda: enricher.lookup(lead["domain"]),
                attempts=max_attempts, sleep=sleep,
            )
        except EnrichmentNotFound as e:
            fail(line, row, "enrich", "enrichment_not_found", str(e))
            continue
        except TransientEnrichmentError as e:
            total_retries += max_attempts - 1
            fail(line, row, "enrich", "enrichment_failed", f"gave up after {max_attempts} attempts: {e}")
            continue

        total_retries += retries
        lead = _merge(lead, enriched)
        score, tier, owner, reasons = score_lead(lead, warnings)
        seen_in_batch.add(lead["domain"])
        result.processed.append({
            **lead,
            "signals": "|".join(lead["signals"]),
            "score": score,
            "tier": tier,
            "owner": owner,
            "score_reasons": "; ".join(reasons),
            "warnings": "|".join(warnings),
            "retries": retries,
        })

    total = len(rows)
    ok = len(result.processed)
    result.stats = {
        "total_rows": total,
        "processed": ok,
        "errors": len(result.errors),
        "success_rate_pct": round(100 * ok / total, 1) if total else 0.0,
        "errors_by_code": dict(Counter(e["code"] for e in result.errors)),
        "tiers": dict(Counter(p["tier"] for p in result.processed)),
        "retries_used": total_retries,
    }
    return result
