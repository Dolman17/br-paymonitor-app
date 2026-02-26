# br_pay_monitor/config.py

import os
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent


class Config:
    # General Flask
    SECRET_KEY = os.environ.get("SECRET_KEY", "dev-change-me")

    # Database: prefer DATABASE_URL (Railway/Postgres), fallback to local SQLite
    SQLALCHEMY_DATABASE_URI = os.environ.get(
        "DATABASE_URL",
        "sqlite:///" + str(BASE_DIR / "dev.db"),
    )

    # Railway / Postgres compatibility: SQLAlchemy prefers postgresql://
    if SQLALCHEMY_DATABASE_URI.startswith("postgres://"):
        SQLALCHEMY_DATABASE_URI = SQLALCHEMY_DATABASE_URI.replace(
            "postgres://", "postgresql://", 1
        )

    SQLALCHEMY_TRACK_MODIFICATIONS = False

    # Adzuna config (fill these when you create the Blue Ribbon account)
    ADZUNA_APP_ID = os.environ.get("ADZUNA_APP_ID", "")
    ADZUNA_APP_KEY = os.environ.get("ADZUNA_APP_KEY", "")
    ADZUNA_COUNTRY = os.environ.get("ADZUNA_COUNTRY", "gb")
    ADZUNA_DAILY_LIMIT = int(os.environ.get("ADZUNA_DAILY_LIMIT", "900"))  # example cap
    ADZUNA_SAFETY_BUFFER = int(os.environ.get("ADZUNA_SAFETY_BUFFER", "50"))

    # Pay normalisation
    HOURS_PER_WEEK = float(os.environ.get("HOURS_PER_WEEK", "37.5"))
    WEEKS_PER_YEAR = float(os.environ.get("WEEKS_PER_YEAR", "52"))

    # Mail config (Gmail SMTP with app password)
    MAIL_SERVER = os.environ.get("MAIL_SERVER", "smtp.gmail.com")
    MAIL_PORT = int(os.environ.get("MAIL_PORT", "587"))
    MAIL_USE_TLS = os.environ.get("MAIL_USE_TLS", "1") == "1"
    MAIL_USERNAME = os.environ.get("MAIL_USERNAME", "")  # full Gmail address
    MAIL_PASSWORD = os.environ.get("MAIL_PASSWORD", "")  # app password
    MAIL_DEFAULT_SENDER = os.environ.get("MAIL_DEFAULT_SENDER", MAIL_USERNAME)

    # General app config
    WTF_CSRF_TIME_LIMIT = None

    # Timezone assumption for scheduling/reporting
    APP_TIMEZONE = os.environ.get("APP_TIMEZONE", "Europe/London")


class DevelopmentConfig(Config):
    DEBUG = True


class ProductionConfig(Config):
    DEBUG = False


config_by_name = {
    # explicit
    "dev": DevelopmentConfig,
    "prod": ProductionConfig,
    "default": DevelopmentConfig,
    # common aliases so FLASK_ENV can be more human
    "development": DevelopmentConfig,
    "production": ProductionConfig,
}