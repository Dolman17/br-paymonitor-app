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
        # This group just names the subcommands.
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
