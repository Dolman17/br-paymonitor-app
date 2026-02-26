# br_pay_monitor/blueprints/dashboard/routes.py

from datetime import datetime, timedelta

from flask import render_template, request
from flask_login import login_required, current_user
from sqlalchemy import func

from . import bp
from ...extensions import db
from ...models import (
    Brand,
    JobAd,
    JobSnapshot,
    Company,
    MonitoredPostcode,
    MonitoredRole,
    ScrapeRun,
)


def _get_current_brand() -> Brand:
    """
    For now, use the user's brand if set, otherwise the default Blue Ribbon brand.
    """
    if current_user.is_authenticated and current_user.brand:
        return current_user.brand
    return Brand.get_default_brand()


@bp.route("/")
@login_required
def index():
    brand = _get_current_brand()

    # ---- Summary metrics ---- #

    active_jobs_q = JobAd.query.filter_by(brand_id=brand.id, is_open=True)
    active_jobs_count = active_jobs_q.count()

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

    last_scrape = (
        ScrapeRun.query.filter_by(brand_id=brand.id)
        .order_by(ScrapeRun.started_at.desc())
        .first()
    )

    # ---- 7-day activity trend ---- #

    today = datetime.utcnow().date()
    start_date = today - timedelta(days=6)  # inclusive 7 days window

    trend_rows = (
        db.session.query(
            func.date(JobSnapshot.seen_at).label("day"),
            func.count(JobSnapshot.id).label("snapshot_count"),
        )
        .join(JobAd, JobSnapshot.job_ad_id == JobAd.id)
        .filter(
            JobAd.brand_id == brand.id,
            JobSnapshot.seen_at >= datetime.combine(start_date, datetime.min.time()),
        )
        .group_by(func.date(JobSnapshot.seen_at))
        .order_by("day")
        .all()
    )

    trend_map = {row.day: row.snapshot_count for row in trend_rows}
    trend_data = []
    for i in range(6, -1, -1):  # 6 days ago -> today
        d = today - timedelta(days=i)
        trend_data.append(
            {
                "day": d,
                "count": trend_map.get(d, 0),
            }
        )

    # ---- Latest jobs (by most recent snapshot) ---- #

    latest_snapshots = (
        JobSnapshot.query.join(JobAd, JobSnapshot.job_ad_id == JobAd.id)
        .filter(JobAd.brand_id == brand.id)
        .order_by(JobSnapshot.seen_at.desc())
        .limit(10)
        .all()
    )

    return render_template(
        "dashboard/index.html",
        brand=brand,
        active_jobs_count=active_jobs_count,
        company_count=company_count,
        roles_count=roles_count,
        postcodes_count=postcodes_count,
        last_scrape=last_scrape,
        trend_data=trend_data,
        latest_snapshots=latest_snapshots,
    )


@bp.route("/jobs")
@login_required
def jobs():
    brand = _get_current_brand()

    postcodes = (
        MonitoredPostcode.query.filter_by(brand_id=brand.id, is_active=True)
        .order_by(MonitoredPostcode.postcode.asc())
        .all()
    )
    roles = (
        MonitoredRole.query.filter_by(brand_id=brand.id, is_active=True)
        .order_by(MonitoredRole.name.asc())
        .all()
    )

    postcode_id = request.args.get("postcode_id", type=int)
    role_id = request.args.get("role_id", type=int)
    adv_type = request.args.get("adv_type", default="all")  # all, br, competitor
    agency_only = request.args.get("agency_only") == "1"
    min_rate = request.args.get("min_rate", type=float)
    max_rate = request.args.get("max_rate", type=float)

    # Get latest snapshot per job_id (Python grouping, fine for small dataset)
    all_snaps = (
        JobSnapshot.query.join(JobAd, JobSnapshot.job_ad_id == JobAd.id)
        .filter(JobAd.brand_id == brand.id)
        .order_by(JobSnapshot.job_ad_id.asc(), JobSnapshot.seen_at.desc())
        .all()
    )
    latest_by_job = {}
    for s in all_snaps:
        if s.job_ad_id not in latest_by_job:
            latest_by_job[s.job_ad_id] = s
    latest_snaps = list(latest_by_job.values())

    filtered_snaps = []
    for snap in latest_snaps:
        job = snap.job_ad

        # postcode filter
        if postcode_id:
            if not job.monitored_role or job.monitored_role.postcode_id != postcode_id:
                continue

        # role filter
        if role_id:
            if not job.monitored_role or job.monitored_role.id != role_id:
                continue

        # advertiser type
        if adv_type == "br" and not job.is_blue_ribbon:
            continue
        if adv_type == "competitor" and job.is_blue_ribbon:
            continue

        # agency filter
        is_agency = job.company.is_agency if job.company else False
        if agency_only and not is_agency:
            continue

        # pay band filter
        max_h = snap.salary_max_hourly
        min_h = snap.salary_min_hourly
        rate_for_filter = max_h if max_h is not None else min_h

        if min_rate is not None:
            if rate_for_filter is None or rate_for_filter < min_rate:
                continue
        if max_rate is not None:
            if rate_for_filter is None or rate_for_filter > max_rate:
                continue

        filtered_snaps.append(snap)

    filtered_snaps.sort(
        key=lambda s: (s.salary_max_hourly or s.salary_min_hourly or 0.0),
        reverse=True,
    )

    filters = {
        "postcode_id": postcode_id,
        "role_id": role_id,
        "adv_type": adv_type,
        "agency_only": agency_only,
        "min_rate": min_rate,
        "max_rate": max_rate,
    }

    return render_template(
        "dashboard/jobs.html",
        brand=brand,
        snaps=filtered_snaps,
        postcodes=postcodes,
        roles=roles,
        filters=filters,
    )