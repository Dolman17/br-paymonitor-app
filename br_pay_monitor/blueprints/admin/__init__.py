# br_pay_monitor/blueprints/admin/__init__.py

from flask import Blueprint

bp = Blueprint("admin", __name__, url_prefix="/admin")

from . import routes  # noqa
