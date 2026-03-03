# br_pay_monitor/__init__.py

import os
from typing import Optional

from flask import Flask
from flask_login import current_user

from .config import config_by_name
from .extensions import db, migrate, login_manager, mail


def create_app(config_name: Optional[str] = None) -> Flask:
    """Application factory for BR Pay Monitor."""
    if config_name is None:
        config_name = os.environ.get("FLASK_ENV", "default")

    app = Flask(__name__)
    app.config.from_object(config_by_name.get(config_name, config_by_name["default"]))

    # Init extensions
    db.init_app(app)
    migrate.init_app(app, db)
    login_manager.init_app(app)
    mail.init_app(app)

    login_manager.login_view = "auth.login"
    login_manager.login_message_category = "warning"

    from .models import User  # noqa: F401

    @login_manager.user_loader
    def load_user(user_id: str):
        from .models import User as _User  # local import to avoid circulars

        try:
            return _User.query.get(int(user_id))
        except (TypeError, ValueError):
            return None

    # Register blueprints
    from .blueprints.auth import bp as auth_bp
    from .blueprints.dashboard import bp as dashboard_bp
    from .blueprints.admin import bp as admin_bp

    app.register_blueprint(auth_bp)
    app.register_blueprint(dashboard_bp)
    app.register_blueprint(admin_bp)

    # Simple context processor for templates
    @app.context_processor
    def inject_user():
        return {"current_user": current_user}

    # CLI commands
    register_cli_commands(app)

    return app


def register_cli_commands(app: Flask) -> None:
    import click
    from .models import (
        User,
        Brand,
        MonitoredPostcode,
        MonitoredRole,
        EmailRecipient,
        EmailLog,
        db as _db,
    )

    # -------- Admin user creation -------- #

    @app.cli.command("create-admin")
    @click.argument("email")
    @click.argument("password")
    def create_admin(email: str, password: str):
        """Create an admin user."""
        email_clean = email.lower().strip()
        existing = User.query.filter_by(email=email_clean).first()
        if existing:
            click.echo(f"User {email_clean} already exists.")
            return

        brand = Brand.get_default_brand()
        user = User(email=email_clean, is_admin=True, brand=brand)
        user.set_password(password)
        _db.session.add(user)
        _db.session.commit()
        click.echo(f"Created admin user {email_clean} for brand {brand.slug}.")

    # -------- Seed demo config (brand/postcode/roles) -------- #

    @app.cli.command("seed-demo-config")
    @click.argument("postcode")
    def seed_demo_config(postcode: str):
        """
        Seed a basic brand/postcode/roles config for quick testing.

        Example:
            flask seed-demo-config "WS13 6QF"
        """
        brand = Brand.get_default_brand()

        pc = (
            MonitoredPostcode.query.filter_by(
                brand_id=brand.id, postcode=postcode.strip().upper()
            ).first()
        )
        if not pc:
            pc = MonitoredPostcode(
                brand=brand,
                postcode=postcode.strip().upper(),
                radius_miles=25.0,
                display_name=f"{postcode.strip().upper()} + 25mi",
            )
            _db.session.add(pc)
            click.echo(f"Created monitored postcode {pc.postcode}")
        else:
            click.echo(f"Postcode {pc.postcode} already exists, skipping create.")

        default_roles = [
            "Care Assistant",
            "Senior Care Assistant",
            "Support Worker",
        ]

        for role_name in default_roles:
            existing = (
                MonitoredRole.query.filter_by(
                    brand_id=brand.id, name=role_name, postcode=pc
                ).first()
            )
            if existing:
                continue
            role = MonitoredRole(
                brand=brand,
                postcode=pc,
                name=role_name,
                search_terms=role_name,
            )
            _db.session.add(role)
            click.echo(f"Created monitored role '{role_name}' for {pc.postcode}")

        _db.session.commit()
        click.echo("Demo config seeded.")

    # -------- Scraping commands group -------- #

    @app.cli.group("scrape")
    def scrape_group():
        """Scraping related commands."""
        pass

    @scrape_group.command("adzuna-once")
    @click.option("--brand", "brand_slug", default="blue-ribbon", help="Brand slug")
    @click.option("--max-pages", default=1, show_default=True, type=int)
    @click.option("--results-per-page", default=50, show_default=True, type=int)
    def scrape_adzuna_once(brand_slug: str, max_pages: int, results_per_page: int):
        """
        Run a single Adzuna scrape for all active postcodes x roles.

        Example:
            flask scrape adzuna-once --max-pages=1 --results-per-page=20
        """
        from .services.scraping import run_adzuna_scrape

        click.echo(f"Running Adzuna scrape for brand '{brand_slug}'...")
        run_obj, total = run_adzuna_scrape(
            brand_slug=brand_slug,
            trigger="manual",
            max_pages=max_pages,
            results_per_page=results_per_page,
        )
        click.echo(
            f"Scrape {run_obj.id} complete: {total} jobs fetched, "
            f"{run_obj.api_calls} API calls (success={run_obj.success})."
        )

    @scrape_group.command("adzuna-scheduled")
    @click.option("--brand", "brand_slug", default="blue-ribbon", help="Brand slug")
    @click.option("--max-pages", default=1, show_default=True, type=int)
    @click.option("--results-per-page", default=50, show_default=True, type=int)
    def scrape_adzuna_scheduled(brand_slug: str, max_pages: int, results_per_page: int):
        """
        Run Adzuna scrape with trigger='scheduled' (intended for Railway cron).

        Example:
            flask scrape adzuna-scheduled --brand=blue-ribbon --max-pages=1
        """
        from .services.scraping import run_adzuna_scrape

        click.echo(f"Running *scheduled* Adzuna scrape for brand '{brand_slug}'...")
        run_obj, total = run_adzuna_scrape(
            brand_slug=brand_slug,
            trigger="scheduled",
            max_pages=max_pages,
            results_per_page=results_per_page,
        )
        click.echo(
            f"Scheduled scrape {run_obj.id} complete: {total} jobs fetched, "
            f"{run_obj.api_calls} API calls (success={run_obj.success})."
        )

    # -------- Report commands group -------- #

    @app.cli.group("report")
    def report_group():
        """Reporting and email commands."""
        pass

    @report_group.command("send-daily")
    @click.option("--brand", "brand_slug", default="blue-ribbon", help="Brand slug")
    @click.option(
        "--date",
        "date_str",
        default=None,
        help="Target date (YYYY-MM-DD). Defaults to today (UTC).",
    )
    def send_daily_report(brand_slug: str, date_str: Optional[str]):
        """
        Build and send the daily email report for the given brand.

        Example:
            flask report send-daily --brand=blue-ribbon
            flask report send-daily --brand=blue-ribbon --date=2026-02-25
        """
        from datetime import datetime as _dt

        from .services.reporting import build_daily_report
        from .services.emailer import send_html_email

        brand = Brand.query.filter_by(slug=brand_slug).first()
        if not brand:
            click.echo(f"Brand with slug '{brand_slug}' not found.")
            return

        if date_str:
            try:
                target_date = _dt.strptime(date_str, "%Y-%m-%d").date()
            except ValueError:
                click.echo("Invalid date format. Use YYYY-MM-DD.")
                return
        else:
            target_date = _dt.utcnow().date()

        # Brand-specific recipient selection using per-brand flags
        if brand.slug == "blue-ribbon":
            recipients = (
                EmailRecipient.query.filter_by(
                    is_active=True,
                    include_blue_ribbon=True,
                )
                .order_by(EmailRecipient.email.asc())
                .all()
            )
        elif brand.slug == "forevermore-care":
            recipients = (
                EmailRecipient.query.filter_by(
                    is_active=True,
                    include_forevermore=True,
                )
                .order_by(EmailRecipient.email.asc())
                .all()
            )
        else:
            # No one subscribed for unknown brands yet
            recipients = []

        if not recipients:
            click.echo(
                f"No active email recipients configured for brand '{brand_slug}'. "
                "Skipping send."
            )
            return

        to_emails = [r.email for r in recipients]
        click.echo(
            f"Building daily report for {brand.slug} on {target_date.isoformat()} "
            f"to {len(to_emails)} recipients..."
        )
        subject, html = build_daily_report(
            brand_slug=brand_slug, target_date=target_date
        )
        success, log = send_html_email(subject, to_emails, html, brand=brand)

        if success:
            click.echo(
                f"Daily report sent successfully. Log id={log.id if log else 'N/A'}."
            )
        else:
            click.echo("Failed to send daily report. See logs for details.")

    @report_group.command("send-daily-scheduled")
    @click.option("--brand", "brand_slug", default="blue-ribbon", help="Brand slug")
    def send_daily_report_scheduled(brand_slug: str):
        """
        DST-safe scheduled daily report sender.

        Intended usage:
        - Schedule this command at 08:00 UTC and 09:00 UTC daily.
        - It will only send when the local time in APP_TIMEZONE is exactly 09:00.
        - It is idempotent: won't send twice for the same brand/date.

        Example:
            flask report send-daily-scheduled --brand=blue-ribbon
        """
        from datetime import datetime as _dt
        from zoneinfo import ZoneInfo

        from .services.reporting import build_daily_report
        from .services.emailer import send_html_email

        brand = Brand.query.filter_by(slug=brand_slug).first()
        if not brand:
            click.echo(f"Brand with slug '{brand_slug}' not found.")
            return

        tz_name = app.config.get("APP_TIMEZONE", "Europe/London")
        try:
            tz = ZoneInfo(tz_name)
        except Exception:
            click.echo(f"Invalid APP_TIMEZONE '{tz_name}'. Falling back to Europe/London.")
            tz = ZoneInfo("Europe/London")

        now_local = _dt.now(tz)
        if now_local.hour != 9:
            click.echo(
                f"Not sending: local time is {now_local.strftime('%Y-%m-%d %H:%M %Z')}, "
                "only sends at 09:00 local."
            )
            return

        target_date = now_local.date()
        subject_expected = (
            f"{brand.name} – BR Pay Monitor Daily Rate Report – "
            f"{target_date.strftime('%Y-%m-%d')}"
        )

        already_sent = (
            EmailLog.query.filter_by(
                brand_id=brand.id,
                subject=subject_expected,
                success=True,
            )
            .first()
            is not None
        )
        if already_sent:
            click.echo(f"Already sent daily report for {brand.slug} on {target_date}. Skipping.")
            return

        # Brand-specific recipient selection using per-brand flags
        if brand.slug == "blue-ribbon":
            recipients = (
                EmailRecipient.query.filter_by(
                    is_active=True,
                    include_blue_ribbon=True,
                )
                .order_by(EmailRecipient.email.asc())
                .all()
            )
        elif brand.slug == "forevermore-care":
            recipients = (
                EmailRecipient.query.filter_by(
                    is_active=True,
                    include_forevermore=True,
                )
                .order_by(EmailRecipient.email.asc())
                .all()
            )
        else:
            recipients = []

        if not recipients:
            click.echo(
                f"No active email recipients configured for brand '{brand_slug}'. "
                "Skipping send."
            )
            return

        to_emails = [r.email for r in recipients]
        click.echo(
            f"Sending scheduled daily report for {brand.slug} on {target_date.isoformat()} "
            f"({now_local.strftime('%H:%M %Z')}) to {len(to_emails)} recipients..."
        )

        subject, html = build_daily_report(
            brand_slug=brand_slug, target_date=target_date
        )
        success, log = send_html_email(subject, to_emails, html, brand=brand)

        if success:
            click.echo(
                f"Daily report sent successfully. Log id={log.id if log else 'N/A'}."
            )
        else:
            click.echo("Failed to send daily report. See logs for details.")