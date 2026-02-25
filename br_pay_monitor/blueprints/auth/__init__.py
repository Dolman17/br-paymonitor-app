# br_pay_monitor/blueprints/auth/__init__.py

from flask import Blueprint

bp = Blueprint("auth", __name__, url_prefix="/auth")

from . import routes  # noqa
