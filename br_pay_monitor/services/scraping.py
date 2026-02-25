# br_pay_monitor/services/scraping.py

from __future__ import annotations

from typing import Tuple

from flask import current_app

from ..extensions import db
from ..models import (
    Brand,
    MonitoredPostcode,
    MonitoredRole,
    Company,
    JobAd,
    ScrapeRun,
    JobSnapshot,
)
from .adzuna_client import AdzunaClient


def _normalise_company_name(raw: str | None) -> str:
    if not raw:
        return "Unknown"
    return " ".join(raw.strip().split())


def _ensure_company(canonical_name: str) -> Company:
    company = Company.query.filter_by(canonical_name=canonical_name).first()
    if company:
        return company

    company = Company(canonical_name=canonical_name)
    db.session.add(company)
    db.session.flush()
    return company


def _is_blue_ribbon_company(name: str) -> bool:
    n = name.lower()
    return "blue ribbon" in n or "blue-ribbon" in n or "blueribbon" in n


def _extract_location(job: dict) -> tuple[str | None, str | None, str | None]:
    """
    Returns (display_name, city, county) from Adzuna's location block.
    """
    loc = job.get("location") or {}
    display_name = loc.get("display_name")
    area = loc.get("area") or []
    city = None
    county = None
    if len(area) >= 3:
        # e.g. ["UK", "West Midlands", "Lichfield"]
        county = area[1]
        city = area[2]
    elif len(area) == 2:
        county = area[1]
    return display_name, city, county


def _convert_to_hourly(
    salary_min: float | None,
    salary_max: float | None,
    salary_is_annual: bool,
) -> tuple[float | None, float | None, str | None]:
    cfg = current_app.config
    hours_per_week = float(cfg.get("HOURS_PER_WEEK", 37.5))
    weeks_per_year = float(cfg.get("WEEKS_PER_YEAR", 52))

    if salary_min is None and salary_max is None:
        return None, None, None

    if not salary_is_annual:
        return salary_min, salary_max, "hourly"

    denom = hours_per_week * weeks_per_year
    h_min = salary_min / denom if salary_min is not None else None
    h_max = salary_max / denom if salary_max is not None else None
    return h_min, h_max, "annual"


def run_adzuna_scrape(
    brand_slug: str = "blue-ribbon",
    trigger: str = "manual",
    max_pages: int = 1,
    results_per_page: int = 50,
) -> Tuple[ScrapeRun, int]:
    """
    Run a single Adzuna scrape for all active postcodes x roles for the given brand.
    Returns (ScrapeRun, jobs_fetched_count).
    """
    brand = Brand.query.filter_by(slug=brand_slug).first()
    if not brand:
        raise RuntimeError(f"Brand with slug '{brand_slug}' not found")

    postcodes = (
        MonitoredPostcode.query.filter_by(brand_id=brand.id, is_active=True)
        .order_by(MonitoredPostcode.id.asc())
        .all()
    )
    roles = (
        MonitoredRole.query.filter_by(brand_id=brand.id, is_active=True)
        .order_by(MonitoredRole.id.asc())
        .all()
    )

    if not postcodes or not roles:
        raise RuntimeError("No monitored postcodes or roles configured yet")

    scrape_run = ScrapeRun(brand=brand, trigger=trigger)
    db.session.add(scrape_run)
    db.session.flush()

    client = AdzunaClient()
    total_jobs = 0
    api_calls = 0

    for pc in postcodes:
        for role in roles:
            # If role tied to specific postcode, skip others
            if role.postcode_id and role.postcode_id != pc.id:
                continue

            what = (role.search_terms or role.name).strip()
            where = pc.postcode
            distance = pc.radius_miles

            results = client.search_jobs(
                where=where,
                distance=distance,
                what=what,
                results_per_page=results_per_page,
                max_pages=max_pages,
            )

            # Rough call count approximation
            api_calls += max_pages
            total_jobs += len(results)

            for job in results:
                adzuna_id = str(job.get("id") or job.get("adref") or "")
                if not adzuna_id:
                    continue

                title = job.get("title") or "Untitled"
                company_raw = (job.get("company") or {}).get("display_name") or "Unknown"
                company_name = _normalise_company_name(company_raw)
                company = _ensure_company(company_name)

                loc_display, city, county = _extract_location(job)

                salary_min = job.get("salary_min")
                salary_max = job.get("salary_max")
                salary_is_predicted = bool(job.get("salary_is_predicted"))
                # If predicted only, we still use it for now
                is_annual = job.get("contract_time") == "full_time" and job.get("salary_min") and job.get("salary_max") and job.get("salary_min") > 1000

                h_min, h_max, salary_source = _convert_to_hourly(
                    salary_min,
                    salary_max,
                    salary_is_annual=is_annual,
                )

                job_ad = JobAd.query.filter_by(adzuna_id=adzuna_id).first()
                if not job_ad:
                    job_ad = JobAd(
                        adzuna_id=adzuna_id,
                        brand=brand,
                        company=company,
                        title_raw=title,
                        location_raw=loc_display,
                        city=city,
                        county=county,
                        monitored_role=role,
                        is_blue_ribbon=_is_blue_ribbon_company(company_name),
                    )
                    db.session.add(job_ad)

                # update "last seen"
                job_ad.company = company
                job_ad.title_raw = title
                job_ad.location_raw = loc_display
                job_ad.city = city
                job_ad.county = county
                job_ad.monitored_role = role
                job_ad.is_open = True

                from datetime import datetime

                now = datetime.utcnow()
                if job_ad.first_seen_at is None:
                    job_ad.first_seen_at = now
                job_ad.last_seen_at = now

                snapshot = JobSnapshot(
                    job_ad=job_ad,
                    scrape_run=scrape_run,
                    salary_min_hourly=h_min,
                    salary_max_hourly=h_max,
                    salary_source=salary_source,
                    is_open=True,
                    raw_payload=job,
                )
                db.session.add(snapshot)

    # TODO: mark jobs that were not seen in this run as closed (next iteration)

    scrape_run.jobs_fetched = total_jobs
    scrape_run.api_calls = api_calls
    scrape_run.success = True

    from datetime import datetime as _dt

    scrape_run.finished_at = _dt.utcnow()

    db.session.commit()
    return scrape_run, total_jobs
