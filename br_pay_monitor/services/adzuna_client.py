# br_pay_monitor/services/adzuna_client.py

from typing import Any, Dict, List, Optional

import requests
from flask import current_app


class AdzunaClient:
    """
    Thin wrapper around the Adzuna jobs search API.
    """

    BASE_URL = "https://api.adzuna.com/v1/api/jobs"

    def __init__(self) -> None:
        cfg = current_app.config
        self.app_id = cfg.get("ADZUNA_APP_ID")
        self.app_key = cfg.get("ADZUNA_APP_KEY")
        self.country = cfg.get("ADZUNA_COUNTRY", "gb")

        if not self.app_id or not self.app_key:
            raise RuntimeError("ADZUNA_APP_ID and ADZUNA_APP_KEY must be set in env/config")

    def _build_url(self, page: int) -> str:
        return f"{self.BASE_URL}/{self.country}/search/{page}"

    def search_jobs(
        self,
        where: str,
        distance: float,
        what: Optional[str] = None,
        results_per_page: int = 50,
        max_pages: int = 1,
    ) -> List[Dict[str, Any]]:
        """
        Fetch jobs from Adzuna for a given location and search term.
        Returns a flat list of job dicts (Adzuna's 'results').
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

        for page in range(1, max_pages + 1):
            url = self._build_url(page)
            resp = requests.get(url, params=params_base, timeout=20)
            resp.raise_for_status()
            data = resp.json()
            results = data.get("results", [])
            if not results:
                break
            all_results.extend(results)

            # If fewer than requested returned, we've hit the end
            if len(results) < results_per_page:
                break

        return all_results
