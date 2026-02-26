# br_pay_monitor/services/reporting.py

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timedelta
from typing import Dict, List, Optional, Tuple

from flask import render_template
from sqlalchemy import func

from ..extensions import db
from ..models import (
    Brand,
    JobAd,
    JobSnapshot,
    Company,
    MonitoredPostcode,
    MonitoredRole,
)

# Any non-zero change counts as material
MATERIAL_DELTA = 0.0  # if you ever want a threshold again, set this to e.g. 0.10


@dataclass
class RateChangeRow:
    job: JobAd
    company_name: str
    role_label: str
    location_label: str
    prev_min: Optional[float]
    prev_max: Optional[float]
    curr_min: Optional[float]
    curr_max: Optional[float]
    delta_min: Optional[float]
    delta_max: Optional[float]
    prev_seen_at: Optional[datetime]
    baseline_min: Optional[float]
    baseline_max: Optional[float]
    is_blue_ribbon: bool
    is_agency: bool


@dataclass
class NewRoleRow:
    title: str
    first_seen_at: datetime
    company_count: int


@dataclass
class NewCompanyRow:
    company_name: str
    first_seen_at: datetime
    role_count: int


@dataclass
class TopPayingRow:
    company_name: str
    role_label: str
    location_label: str
    min_hourly: Optional[float]
    max_hourly: Optional[float]
    is_blue_ribbon: bool
    is_agency: bool


@dataclass
class BRUndercutRow:
    br_job: Optional[JobAd]
    br_company_name: str
    role_label: str
    location_label: str
    br_min: Optional[float]
    br_max: Optional[float]
    best_comp_company: str
    best_comp_max: Optional[float]
    diff: Optional[float]
    comp_is_agency: bool


@dataclass
class CompetitorAboveBaselineRow:
    company_name: str
    role_label: str
    location_label: str
    min_hourly: Optional[float]
    max_hourly: Optional[float]
    baseline_min: Optional[float]
    baseline_max: Optional[float]
    is_agency: bool


@dataclass
class NewLocalThreatRow:
    company_name: str
    role_label: str
    location_label: str
    min_hourly: Optional[float]
    max_hourly: Optional[float]
    baseline_min: Optional[float]
    baseline_max: Optional[float]
    first_seen_at: datetime
    is_agency: bool


def _day_bounds(target: date) -> Tuple[datetime, datetime]:
    start = datetime.combine(target, datetime.min.time())
    end = start + timedelta(days=1)
    return start, end


def _role_label_for_job(job: JobAd) -> str:
    if job.monitored_role and job.monitored_role.name:
        return job.monitored_role.name
    return job.title_normalized or job.title_raw or "Unknown role"


def _location_label_for_job(job: JobAd) -> str:
    if job.city and job.county:
        return f"{job.city} ({job.county})"
    if job.city:
        return job.city
    if job.location_raw:
        return job.location_raw
    return "Unknown"


def _compute_baseline_for_job(
    job_id: int, baseline_start: datetime, day_start: datetime
) -> Tuple[Optional[float], Optional[float]]:
    """Per-job 7-day average baseline (min/max)."""
    snaps = (
        JobSnapshot.query.filter(
            JobSnapshot.job_ad_id == job_id,
            JobSnapshot.seen_at >= baseline_start,
            JobSnapshot.seen_at < day_start,
        )
        .order_by(JobSnapshot.seen_at.asc())
        .all()
    )
    mins: List[float] = []
    maxs: List[float] = []
    for s in snaps:
        if s.salary_min_hourly is not None:
            mins.append(s.salary_min_hourly)
        if s.salary_max_hourly is not None:
            maxs.append(s.salary_max_hourly)

    baseline_min = sum(mins) / len(mins) if mins else None
    baseline_max = sum(maxs) / len(maxs) if maxs else None
    return baseline_min, baseline_max


def get_daily_report_data(
    brand_slug: str = "blue-ribbon",
    target_date: Optional[date] = None,
) -> Dict:
    """
    Build all structured data for the daily report email.
    """
    if target_date is None:
        target_date = datetime.utcnow().date()

    brand = Brand.query.filter_by(slug=brand_slug).first()
    if not brand:
        raise RuntimeError(f"Brand with slug '{brand_slug}' not found")

    day_start, day_end = _day_bounds(target_date)
    baseline_start = day_start - timedelta(days=7)

    # ---- Summary metrics ---- #

    active_jobs_count = JobAd.query.filter_by(
        brand_id=brand.id, is_open=True
    ).count()

    company_count = (
        Company.query.join(JobAd, JobAd.company_id == Company.id)
        .filter(JobAd.brand_id == brand.id, JobAd.is_open.is_(True))
        .distinct()
        .count()
    )

    roles_count = (
        MonitoredRole.query.filter_by(brand_id=brand.id, is_active=True).count()
    )
    postcodes_count = (
        MonitoredPostcode.query.filter_by(brand_id=brand.id, is_active=True).count()
    )

    # ---- Today's snapshots + last snapshot per job ---- #

    today_snaps = (
        JobSnapshot.query.join(JobAd, JobSnapshot.job_ad_id == JobAd.id)
        .filter(
            JobAd.brand_id == brand.id,
            JobSnapshot.seen_at >= day_start,
            JobSnapshot.seen_at < day_end,
        )
        .order_by(JobSnapshot.seen_at.asc())
        .all()
    )

    last_snap_per_job: Dict[int, JobSnapshot] = {}
    for s in today_snaps:
        # last one wins due to ordering
        last_snap_per_job[s.job_ad_id] = s

    # ---- BR 7-day baseline per role (Blue Ribbon only) ---- #

    baseline_rows = (
        JobSnapshot.query.join(JobAd, JobSnapshot.job_ad_id == JobAd.id)
        .filter(
            JobAd.brand_id == brand.id,
            JobAd.is_blue_ribbon.is_(True),
            JobSnapshot.seen_at >= baseline_start,
            JobSnapshot.seen_at < day_start,
        )
        .all()
    )

    baseline_by_role: Dict[str, Tuple[Optional[float], Optional[float]]] = {}
    tmp_by_role: Dict[str, Dict[str, List[float]]] = {}

    for s in baseline_rows:
        job = s.job_ad
        role_label = _role_label_for_job(job)
        bucket = tmp_by_role.setdefault(role_label, {"mins": [], "maxs": []})
        if s.salary_min_hourly is not None:
            bucket["mins"].append(s.salary_min_hourly)
        if s.salary_max_hourly is not None:
            bucket["maxs"].append(s.salary_max_hourly)

    for role_label, vals in tmp_by_role.items():
        mins = vals["mins"]
        maxs = vals["maxs"]
        bmin = sum(mins) / len(mins) if mins else None
        bmax = sum(maxs) / len(maxs) if maxs else None
        baseline_by_role[role_label] = (bmin, bmax)

    # ---- Rate changes vs previous snapshot + per-job baseline ---- #

    rate_changes: List[RateChangeRow] = []

    for job_id, curr_snap in last_snap_per_job.items():
        job = curr_snap.job_ad

        prev_snap = (
            JobSnapshot.query.filter(
                JobSnapshot.job_ad_id == job_id,
                JobSnapshot.seen_at < day_start,
            )
            .order_by(JobSnapshot.seen_at.desc())
            .first()
        )
        if not prev_snap:
            continue

        prev_min = prev_snap.salary_min_hourly
        prev_max = prev_snap.salary_max_hourly
        curr_min = curr_snap.salary_min_hourly
        curr_max = curr_snap.salary_max_hourly

        changed_min = (prev_min is not None or curr_min is not None) and prev_min != curr_min
        changed_max = (prev_max is not None or curr_max is not None) and prev_max != curr_max

        if not (changed_min or changed_max):
            continue

        delta_min: Optional[float] = None
        delta_max: Optional[float] = None
        max_abs_delta = 0.0

        if changed_min and prev_min is not None and curr_min is not None:
            delta_min = curr_min - prev_min
            max_abs_delta = max(max_abs_delta, abs(delta_min))

        if changed_max and prev_max is not None and curr_max is not None:
            delta_max = curr_max - prev_max
            max_abs_delta = max(max_abs_delta, abs(delta_max))

        # Materiality filter for competitors: ignore tiny moves if MATERIAL_DELTA > 0.
        # With MATERIAL_DELTA = 0.0, this effectively keeps any non-zero move.
        if not job.is_blue_ribbon and max_abs_delta < MATERIAL_DELTA:
            continue

        baseline_min, baseline_max = _compute_baseline_for_job(
            job_id, baseline_start, day_start
        )

        company_name = job.company.canonical_name if job.company else "Unknown"
        role_label = _role_label_for_job(job)
        location_label = _location_label_for_job(job)

        rate_changes.append(
            RateChangeRow(
                job=job,
                company_name=company_name,
                role_label=role_label,
                location_label=location_label,
                prev_min=prev_min,
                prev_max=prev_max,
                curr_min=curr_min,
                curr_max=curr_max,
                delta_min=delta_min,
                delta_max=delta_max,
                prev_seen_at=prev_snap.seen_at,
                baseline_min=baseline_min,
                baseline_max=baseline_max,
                is_blue_ribbon=job.is_blue_ribbon,
                is_agency=job.company.is_agency if job.company else False,
            )
        )

    # biggest max delta first
    rate_changes.sort(key=lambda r: (r.delta_max or 0, r.delta_min or 0), reverse=True)

    # ---- New roles today (jobs first seen today) ---- #

    jobs_first_today = (
        JobAd.query.filter(
            JobAd.brand_id == brand.id,
            JobAd.first_seen_at >= day_start,
            JobAd.first_seen_at < day_end,
        )
        .all()
    )

    role_map: Dict[str, NewRoleRow] = {}
    for job in jobs_first_today:
        title = job.title_normalized or job.title_raw or "Unknown role"
        existing = role_map.get(title)
        if existing:
            existing.company_count += 1
        else:
            role_map[title] = NewRoleRow(
                title=title,
                first_seen_at=job.first_seen_at,
                company_count=1,
            )

    new_roles = sorted(
        role_map.values(),
        key=lambda r: (r.company_count, r.title.lower()),
        reverse=True,
    )

    # ---- New companies (first ever appearance today) ---- #

    company_firsts = (
        db.session.query(
            Company,
            func.min(JobAd.first_seen_at).label("first_seen"),
            func.count(JobAd.id).label("role_count"),
        )
        .join(JobAd, JobAd.company_id == Company.id)
        .filter(JobAd.brand_id == brand.id)
        .group_by(Company.id)
        .all()
    )

    new_companies: List[NewCompanyRow] = []
    new_company_by_name: Dict[str, NewCompanyRow] = {}

    for company, first_seen, role_count in company_firsts:
        if first_seen is None:
            continue
        if day_start <= first_seen < day_end:
            row = NewCompanyRow(
                company_name=company.canonical_name,
                first_seen_at=first_seen,
                role_count=role_count,
            )
            new_companies.append(row)
            new_company_by_name[company.canonical_name] = row

    new_companies.sort(key=lambda c: c.company_name.lower())

    # ---- Top paying today by role + per-role BR/competitor split ---- #

    top_by_role: Dict[str, List[TopPayingRow]] = {}
    per_role_today: Dict[str, Dict[str, List[TopPayingRow]]] = {}

    for job_id, snap in last_snap_per_job.items():
        job = snap.job_ad
        if snap.salary_max_hourly is None and snap.salary_min_hourly is None:
            continue

        role_label = _role_label_for_job(job)
        location_label = _location_label_for_job(job)
        company_name = job.company.canonical_name if job.company else "Unknown"
        is_agency = job.company.is_agency if job.company else False

        row = TopPayingRow(
            company_name=company_name,
            role_label=role_label,
            location_label=location_label,
            min_hourly=snap.salary_min_hourly,
            max_hourly=snap.salary_max_hourly,
            is_blue_ribbon=job.is_blue_ribbon,
            is_agency=is_agency,
        )

        top_by_role.setdefault(role_label, []).append(row)

        bucket = per_role_today.setdefault(role_label, {"br": [], "competitor": []})
        if job.is_blue_ribbon:
            bucket["br"].append(row)
        else:
            bucket["competitor"].append(row)

    # sort & trim for "top by role"
    for role_label, rows in top_by_role.items():
        rows.sort(
            key=lambda r: (r.max_hourly or r.min_hourly or 0.0, r.min_hourly or 0.0),
            reverse=True,
        )
        top_by_role[role_label] = rows[:5]

    # ---- BR adverts undercut today (by role) ---- #

    br_undercut_ads: List[BRUndercutRow] = []

    for role_label, buckets in per_role_today.items():
        br_ads = buckets["br"]
        comp_ads = buckets["competitor"]
        if not br_ads or not comp_ads:
            continue

        for br_row in br_ads:
            br_max = br_row.max_hourly or br_row.min_hourly
            if br_max is None:
                continue

            best_comp = max(
                comp_ads,
                key=lambda c: (c.max_hourly or c.min_hourly or 0.0),
            )
            best_comp_max = best_comp.max_hourly or best_comp.min_hourly
            if best_comp_max is None:
                continue

            diff = best_comp_max - br_max
            # MATERIAL_DELTA still used here; with 0.0, anything > 0 shows
            if diff <= MATERIAL_DELTA:
                continue

            br_job: Optional[JobAd] = None
            for s in last_snap_per_job.values():
                j = s.job_ad
                if (
                    j.is_blue_ribbon
                    and _role_label_for_job(j) == role_label
                    and (j.company and j.company.canonical_name == br_row.company_name)
                ):
                    br_job = j
                    break

            br_undercut_ads.append(
                BRUndercutRow(
                    br_job=br_job,
                    br_company_name=br_row.company_name,
                    role_label=role_label,
                    location_label=br_row.location_label,
                    br_min=br_row.min_hourly,
                    br_max=br_row.max_hourly,
                    best_comp_company=best_comp.company_name,
                    best_comp_max=best_comp_max,
                    diff=diff,
                    comp_is_agency=best_comp.is_agency,
                )
            )

    br_undercut_ads.sort(key=lambda r: r.diff or 0.0, reverse=True)

    # ---- Competitors above BR 7-day baseline (by role) ---- #

    competitors_above_baseline: List[CompetitorAboveBaselineRow] = []

    for role_label, buckets in per_role_today.items():
        comp_ads = buckets["competitor"]
        if not comp_ads:
            continue

        baseline_vals = baseline_by_role.get(role_label)
        if not baseline_vals:
            continue

        bmin, bmax = baseline_vals
        if bmax is None and bmin is None:
            continue

        for comp_row in comp_ads:
            max_h = comp_row.max_hourly or comp_row.min_hourly
            if max_h is None:
                continue

            if bmax is not None:
                if max_h <= bmax + MATERIAL_DELTA:
                    continue
            elif bmin is not None:
                if max_h <= bmin + MATERIAL_DELTA:
                    continue

            competitors_above_baseline.append(
                CompetitorAboveBaselineRow(
                    company_name=comp_row.company_name,
                    role_label=role_label,
                    location_label=comp_row.location_label,
                    min_hourly=comp_row.min_hourly,
                    max_hourly=comp_row.max_hourly,
                    baseline_min=bmin,
                    baseline_max=bmax,
                    is_agency=comp_row.is_agency,
                )
            )

    competitors_above_baseline.sort(
        key=lambda r: (r.max_hourly or r.min_hourly or 0.0), reverse=True
    )

    # ---- New local threats: new companies + above-baseline pay ---- #

    new_local_threats: List[NewLocalThreatRow] = []

    for role_label, buckets in per_role_today.items():
        comp_ads = buckets["competitor"]
        if not comp_ads:
            continue

        baseline_vals = baseline_by_role.get(role_label)
        if not baseline_vals:
            continue

        bmin, bmax = baseline_vals
        if bmax is None and bmin is None:
            continue

        for comp_row in comp_ads:
            # Only consider companies that are brand new today
            nc = new_company_by_name.get(comp_row.company_name)
            if not nc:
                continue

            max_h = comp_row.max_hourly or comp_row.min_hourly
            if max_h is None:
                continue

            # Must be above BR baseline for this role (even by 1p if MATERIAL_DELTA = 0)
            if bmax is not None:
                if max_h <= bmax + MATERIAL_DELTA:
                    continue
            elif bmin is not None:
                if max_h <= bmin + MATERIAL_DELTA:
                    continue

            new_local_threats.append(
                NewLocalThreatRow(
                    company_name=comp_row.company_name,
                    role_label=role_label,
                    location_label=comp_row.location_label,
                    min_hourly=comp_row.min_hourly,
                    max_hourly=comp_row.max_hourly,
                    baseline_min=bmin,
                    baseline_max=bmax,
                    first_seen_at=nc.first_seen_at,
                    is_agency=comp_row.is_agency,
                )
            )

    new_local_threats.sort(
        key=lambda r: (r.max_hourly or r.min_hourly or 0.0), reverse=True
    )

    context = {
        "brand": brand,
        "target_date": target_date,
        "summary": {
            "active_jobs_count": active_jobs_count,
            "company_count": company_count,
            "roles_count": roles_count,
            "postcodes_count": postcodes_count,
        },
        "rate_changes": rate_changes,
        "new_roles": new_roles,
        "new_companies": new_companies,
        "top_by_role": top_by_role,
        "material_delta": MATERIAL_DELTA,
        "br_undercut_ads": br_undercut_ads,
        "competitors_above_baseline": competitors_above_baseline,
        "new_local_threats": new_local_threats,
    }
    return context


def build_daily_report(
    brand_slug: str = "blue-ribbon",
    target_date: Optional[date] = None,
) -> Tuple[str, str]:
    """
    High-level helper: returns (subject, html) for the daily email.
    """
    context = get_daily_report_data(brand_slug=brand_slug, target_date=target_date)
    target_date = context["target_date"]
    brand = context["brand"]

    subject = (
        f"{brand.name} – BR Pay Monitor Daily Rate Report – "
        f"{target_date.strftime('%Y-%m-%d')}"
    )
    html = render_template("email/daily_report.html", **context)
    return subject, html