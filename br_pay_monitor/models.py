# br_pay_monitor/models.py

from datetime import datetime

from flask_login import UserMixin
from werkzeug.security import generate_password_hash, check_password_hash

from .extensions import db


class Brand(db.Model):
    __tablename__ = "brands"

    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(128), nullable=False)
    slug = db.Column(db.String(64), unique=True, nullable=False)
    is_active = db.Column(db.Boolean, default=True, nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)

    def __repr__(self) -> str:
        return f"<Brand {self.slug}>"

    @staticmethod
    def get_default_brand():
        # For now assume a single brand; we can add an admin UI later
        brand = Brand.query.filter_by(slug="blue-ribbon").first()
        if not brand:
            brand = Brand(name="Blue Ribbon", slug="blue-ribbon")
            db.session.add(brand)
            db.session.commit()
        return brand


class User(UserMixin, db.Model):
    __tablename__ = "users"

    id = db.Column(db.Integer, primary_key=True)
    email = db.Column(db.String(255), unique=True, index=True, nullable=False)
    password_hash = db.Column(db.String(255), nullable=False)

    is_admin = db.Column(db.Boolean, default=False, nullable=False)
    is_active = db.Column(db.Boolean, default=True, nullable=False)

    brand_id = db.Column(db.Integer, db.ForeignKey("brands.id"), nullable=True)
    brand = db.relationship("Brand", backref=db.backref("users", lazy="dynamic"))

    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)

    def __repr__(self) -> str:
        return f"<User {self.email}>"

    def set_password(self, password: str) -> None:
        self.password_hash = generate_password_hash(password)

    def check_password(self, password: str) -> bool:
        return check_password_hash(self.password_hash, password)

    def get_id(self) -> str:
        return str(self.id)


class MonitoredPostcode(db.Model):
    __tablename__ = "monitored_postcodes"

    id = db.Column(db.Integer, primary_key=True)
    brand_id = db.Column(db.Integer, db.ForeignKey("brands.id"), nullable=False)
    brand = db.relationship(
        "Brand", backref=db.backref("postcodes", lazy="dynamic")
    )

    postcode = db.Column(db.String(16), nullable=False, index=True)
    radius_miles = db.Column(db.Float, default=25.0, nullable=False)
    display_name = db.Column(db.String(128), nullable=True)

    is_active = db.Column(db.Boolean, default=True, nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)

    def __repr__(self) -> str:
        return f"<Postcode {self.postcode} ({self.radius_miles}mi)>"


class MonitoredRole(db.Model):
    __tablename__ = "monitored_roles"

    id = db.Column(db.Integer, primary_key=True)
    brand_id = db.Column(db.Integer, db.ForeignKey("brands.id"), nullable=False)
    brand = db.relationship(
        "Brand", backref=db.backref("roles", lazy="dynamic")
    )

    # Optional: tie to specific postcode
    postcode_id = db.Column(
        db.Integer, db.ForeignKey("monitored_postcodes.id"), nullable=True
    )
    postcode = db.relationship(
        "MonitoredPostcode", backref=db.backref("roles", lazy="dynamic")
    )

    name = db.Column(db.String(128), nullable=False)
    # Search terms to send to Adzuna (JSON or comma-separated)
    search_terms = db.Column(db.Text, nullable=True)

    is_active = db.Column(db.Boolean, default=True, nullable=False)

    def __repr__(self) -> str:
        return f"<Role {self.name}>"


class Company(db.Model):
    __tablename__ = "companies"

    id = db.Column(db.Integer, primary_key=True)
    canonical_name = db.Column(db.String(255), unique=True, nullable=False)
    is_agency = db.Column(db.Boolean, default=False, nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)

    def __repr__(self) -> str:
        return f"<Company {self.canonical_name}>"


class CompanyAlias(db.Model):
    __tablename__ = "company_aliases"

    id = db.Column(db.Integer, primary_key=True)
    company_id = db.Column(db.Integer, db.ForeignKey("companies.id"), nullable=False)
    company = db.relationship(
        "Company", backref=db.backref("aliases", lazy="dynamic")
    )
    alias_name = db.Column(db.String(255), unique=True, nullable=False)


class JobAd(db.Model):
    __tablename__ = "job_ads"

    id = db.Column(db.Integer, primary_key=True)

    adzuna_id = db.Column(db.String(64), unique=True, nullable=False, index=True)
    brand_id = db.Column(db.Integer, db.ForeignKey("brands.id"), nullable=False)
    brand = db.relationship(
        "Brand", backref=db.backref("job_ads", lazy="dynamic")
    )

    company_id = db.Column(db.Integer, db.ForeignKey("companies.id"), nullable=True)
    company = db.relationship(
        "Company", backref=db.backref("job_ads", lazy="dynamic")
    )

    title_raw = db.Column(db.String(255), nullable=False)
    title_normalized = db.Column(db.String(255), nullable=True)

    location_raw = db.Column(db.String(255), nullable=True)
    location_postcode = db.Column(db.String(16), nullable=True, index=True)
    city = db.Column(db.String(128), nullable=True)
    county = db.Column(db.String(128), nullable=True)

    monitored_role_id = db.Column(
        db.Integer, db.ForeignKey("monitored_roles.id"), nullable=True
    )
    monitored_role = db.relationship(
        "MonitoredRole", backref=db.backref("job_ads", lazy="dynamic")
    )

    is_blue_ribbon = db.Column(db.Boolean, default=False, nullable=False)

    first_seen_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)
    last_seen_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)
    closed_at = db.Column(db.DateTime, nullable=True)
    is_open = db.Column(db.Boolean, default=True, nullable=False)

    def __repr__(self) -> str:
        return f"<JobAd {self.adzuna_id} {self.title_raw[:30]}>"


class ScrapeRun(db.Model):
    __tablename__ = "scrape_runs"

    id = db.Column(db.Integer, primary_key=True)
    brand_id = db.Column(db.Integer, db.ForeignKey("brands.id"), nullable=False)
    brand = db.relationship(
        "Brand", backref=db.backref("scrape_runs", lazy="dynamic")
    )

    started_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)
    finished_at = db.Column(db.DateTime, nullable=True)

    trigger = db.Column(db.String(32), default="schedule", nullable=False)  # schedule/manual
    success = db.Column(db.Boolean, default=False, nullable=False)

    jobs_fetched = db.Column(db.Integer, default=0, nullable=False)
    api_calls = db.Column(db.Integer, default=0, nullable=False)

    error_message = db.Column(db.Text, nullable=True)


class JobSnapshot(db.Model):
    __tablename__ = "job_snapshots"

    id = db.Column(db.Integer, primary_key=True)

    job_ad_id = db.Column(db.Integer, db.ForeignKey("job_ads.id"), nullable=False)
    job_ad = db.relationship(
        "JobAd", backref=db.backref("snapshots", lazy="dynamic")
    )

    scrape_run_id = db.Column(
        db.Integer, db.ForeignKey("scrape_runs.id"), nullable=False
    )
    scrape_run = db.relationship(
        "ScrapeRun", backref=db.backref("snapshots", lazy="dynamic")
    )

    seen_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)

    salary_min_hourly = db.Column(db.Float, nullable=True)
    salary_max_hourly = db.Column(db.Float, nullable=True)
    salary_source = db.Column(db.String(16), nullable=True)  # hourly/annual

    currency = db.Column(db.String(8), default="GBP", nullable=False)
    is_open = db.Column(db.Boolean, default=True, nullable=False)

    raw_payload = db.Column(db.JSON, nullable=True)


class EmailRecipient(db.Model):
    __tablename__ = "email_recipients"

    id = db.Column(db.Integer, primary_key=True)

    # One row per email, with per-brand flags
    email = db.Column(db.String(255), unique=True, index=True, nullable=False)
    is_active = db.Column(db.Boolean, default=True, nullable=False)

    # Brand subscriptions
    include_blue_ribbon = db.Column(db.Boolean, default=True, nullable=False)
    include_forevermore = db.Column(db.Boolean, default=False, nullable=False)

    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)

    def __repr__(self) -> str:
        return f"<EmailRecipient {self.email}>"


class EmailLog(db.Model):
    __tablename__ = "email_logs"

    id = db.Column(db.Integer, primary_key=True)
    brand_id = db.Column(db.Integer, db.ForeignKey("brands.id"), nullable=False)
    brand = db.relationship(
        "Brand", backref=db.backref("email_logs", lazy="dynamic")
    )

    sent_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)
    subject = db.Column(db.String(255), nullable=False)
    to_count = db.Column(db.Integer, nullable=False)
    html_size = db.Column(db.Integer, nullable=False)

    success = db.Column(db.Boolean, default=False, nullable=False)
    error_message = db.Column(db.Text, nullable=True)

class ScrapeCheckpoint(db.Model):
    __tablename__ = "scrape_checkpoints"

    id = db.Column(db.Integer, primary_key=True)

    brand_id = db.Column(db.Integer, db.ForeignKey("brands.id"), nullable=False)
    brand = db.relationship("Brand", backref=db.backref("scrape_checkpoints", lazy="dynamic"))

    postcode_id = db.Column(db.Integer, db.ForeignKey("monitored_postcodes.id"), nullable=False)
    postcode = db.relationship("MonitoredPostcode", backref=db.backref("scrape_checkpoints", lazy="dynamic"))

    role_id = db.Column(db.Integer, db.ForeignKey("monitored_roles.id"), nullable=False)
    role = db.relationship("MonitoredRole", backref=db.backref("scrape_checkpoints", lazy="dynamic"))

    last_scraped_at = db.Column(db.DateTime, nullable=True)

    __table_args__ = (
        db.UniqueConstraint("brand_id", "postcode_id", "role_id", name="uq_scrape_checkpoint_combo"),
    )