# br_pay_monitor/services/adzuna_client.py

from typing import Any, Dict, List, Optional, Tuple
import time
import random

import requests
from flask import current_app


class AdzunaClient:
    """
    Thin wrapper around the Adzuna jobs search API with basic rate limiting + retries.
    """

    BASE_URL = "https://api.adzuna.com/v1/api/jobs"

    def __init__(self) -> None:
        cfg = current_app.config
        self.app_id = cfg.get("ADZUNA_APP_ID")
        self.app_key = cfg.get("ADZUNA_APP_KEY")
        self.country = cfg.get("ADZUNA_COUNTRY", "gb")

        # Trial-safe defaults
        self.min_seconds_between_calls = float(cfg.get("ADZUNA_MIN_SECONDS_BETWEEN_CALLS", 4.0))  # ~15/min
        self.max_retries = int(cfg.get("ADZUNA_MAX_RETRIES", 4))

        if not self.app_id or not self.app_key:
            raise RuntimeError("ADZUNA_APP_ID and ADZUNA_APP_KEY must be set in env/config")

    def _build_url(self, page: int) -> str:
        return f"{self.BASE_URL}/{self.country}/search/{page}"

    def _sleep_between_calls(self) -> None:
        # small jitter reduces thundering herd if multiple jobs ever overlap
        jitter = random.uniform(0.0, 0.3)
        time.sleep(self.min_seconds_between_calls + jitter)

    def search_jobs(
        self,
        where: str,
        distance: float,
        what: Optional[str] = None,
        results_per_page: int = 50,
        max_pages: int = 1,
    ) -> Tuple[List[Dict[str, Any]], int]:
        """
        Fetch jobs from Adzuna for a given location and search term.
        Returns (flat list of job dicts, api_calls_made).
        """
        params_base = {
            "app_id": self.app_id,
            "app_key": self.app_key,
            "results_per_page": results_per_page,
            "where": where,
            "distance": distance,
            "content-type": "application/json",
        }
        if what:
            params_base["what"] = what

        all_results: List[Dict[str, Any]] = []
        api_calls = 0

        for page in range(1, max_pages + 1):
            url = self._build_url(page)

            # Rate limit before each call
            self._sleep_between_calls()

            # Retry loop
            attempt = 0
            while True:
                attempt += 1
                api_calls += 1

                try:
                    resp = requests.get(url, params=params_base, timeout=20)

                    # 429 or transient errors -> backoff + retry
                    if resp.status_code in (429, 500, 502, 503, 504):
                        if attempt <= self.max_retries:
                            backoff = min(60.0, (2 ** (attempt - 1)) * 2.0)  # 2,4,8,16...
                            backoff += random.uniform(0.0, 0.5)
                            time.sleep(backoff)
                            continue
                        resp.raise_for_status()

                    resp.raise_for_status()
                    data = resp.json()
                    results = data.get("results", []) or []

                    # Early stop: no results
                    if not results:
                        return all_results, api_calls

                    all_results.extend(results)

                    # Early stop: fewer than requested means end of paging
                    if len(results) < results_per_page:
                        return all_results, api_calls

                    break  # success for this page

                except requests.RequestException:
                    if attempt <= self.max_retries:
                        backoff = min(60.0, (2 ** (attempt - 1)) * 2.0)
                        backoff += random.uniform(0.0, 0.5)
                        time.sleep(backoff)
                        continue
                    raise

        return all_results, api_calls