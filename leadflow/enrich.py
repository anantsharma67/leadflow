import json
import re
import socket
import time
import urllib.error
import urllib.request
from pathlib import Path


class TransientEnrichmentError(Exception):
    """Timeouts, 5xx, rate limits: worth retrying."""


class EnrichmentNotFound(Exception):
    """The source has nothing for this domain: retrying will not help."""


def with_retry(fn, attempts=3, base_delay=0.5, sleep=time.sleep):
    """Call fn(); retry transient failures with exponential backoff.

    Returns (result, retries_used). Re-raises after the last attempt.
    """
    for attempt in range(1, attempts + 1):
        try:
            return fn(), attempt - 1
        except TransientEnrichmentError:
            if attempt == attempts:
                raise
            sleep(base_delay * 2 ** (attempt - 1))


class MockEnricher:
    """Offline provider for demos and tests, driven by a JSON file.

    A record with "_flaky": true fails `flaky_failures` times before succeeding,
    so the retry path can be demonstrated without a network.
    """

    def __init__(self, path, flaky_failures=2):
        self.data = json.loads(Path(path).read_text())
        self.flaky_failures = flaky_failures
        self._calls = {}

    def lookup(self, domain):
        record = self.data.get(domain)
        if record is None:
            raise EnrichmentNotFound(f"no data for {domain}")
        if record.get("_flaky"):
            n = self._calls.get(domain, 0)
            self._calls[domain] = n + 1
            if n < self.flaky_failures:
                raise TransientEnrichmentError("simulated timeout")
        return {k: v for k, v in record.items() if not k.startswith("_")}


SIGNAL_KEYWORDS = {
    "hiring": ("we're hiring", "we are hiring", "careers", "join our team"),
    "ecommerce": ("add to cart", "shop now", "checkout"),
    "pricing_page": ("pricing",),
}


class WebsiteEnricher:
    """Real provider: reads the homepage and detects simple buying signals."""

    def __init__(self, timeout=8, user_agent="leadflow/0.1"):
        self.timeout = timeout
        self.user_agent = user_agent

    def lookup(self, domain):
        req = urllib.request.Request(
            f"https://{domain}", headers={"User-Agent": self.user_agent}
        )
        try:
            with urllib.request.urlopen(req, timeout=self.timeout) as resp:
                html = resp.read(500_000).decode("utf-8", errors="ignore")
        except urllib.error.HTTPError as e:  # must precede URLError (subclass)
            if e.code in (404, 410):
                raise EnrichmentNotFound(f"HTTP {e.code} for {domain}")
            raise TransientEnrichmentError(f"HTTP {e.code}")
        except urllib.error.URLError as e:
            if isinstance(e.reason, socket.gaierror):
                raise EnrichmentNotFound(f"domain does not resolve: {domain}")
            raise TransientEnrichmentError(str(e.reason))
        except (TimeoutError, OSError) as e:
            raise TransientEnrichmentError(str(e))

        title = re.search(r"<title[^>]*>(.*?)</title>", html, re.I | re.S)
        desc = re.search(
            r'<meta[^>]+name=["\']description["\'][^>]+content=["\'](.*?)["\']',
            html, re.I | re.S,
        )
        text = html.lower()
        signals = [
            name for name, words in SIGNAL_KEYWORDS.items()
            if any(w in text for w in words)
        ]
        return {
            "website_title": title.group(1).strip() if title else "",
            "description": desc.group(1).strip() if desc else "",
            "signals": signals,
        }
