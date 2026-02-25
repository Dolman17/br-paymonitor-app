# br_pay_monitor/blueprints/dashboard/routes.py

from datetime import datetime, timedelta

from flask import render_template
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

    # Normalize into a list of dicts for each of last 7 days (including zeros)
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
