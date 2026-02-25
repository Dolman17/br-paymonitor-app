# br_pay_monitor/blueprints/dashboard/__init__.py

from flask import Blueprint

bp = Blueprint("dashboard", __name__)

from . import routes  # noqa
