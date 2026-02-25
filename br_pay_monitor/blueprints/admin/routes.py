# br_pay_monitor/blueprints/admin/routes.py

from flask import render_template, redirect, url_for, flash, request, abort
from flask_login import login_required, current_user

from . import bp
from .forms import PostcodeForm
from ...extensions import db
from ...models import MonitoredPostcode, Brand


def _require_admin():
    if not current_user.is_authenticated:
        abort(401)
    if not current_user.is_admin:
        abort(403)


@bp.route("/postcodes", methods=["GET", "POST"])
@login_required
def postcodes():
    _require_admin()

    # For now, assume user's brand or default brand
    brand = current_user.brand or Brand.get_default_brand()

    form = PostcodeForm()
    if form.validate_on_submit():
        postcode = form.postcode.data.strip().upper()
        radius = form.radius_miles.data or 25.0
        label = form.display_name.data.strip() or f"{postcode} + {radius:g}mi"

        existing = MonitoredPostcode.query.filter_by(
            brand_id=brand.id, postcode=postcode
        ).first()
        if existing:
            flash("This postcode is already being monitored.", "warning")
        else:
            pc = MonitoredPostcode(
                brand=brand,
                postcode=postcode,
                radius_miles=radius,
                display_name=label,
                is_active=True,
            )
            db.session.add(pc)
            db.session.commit()
            flash(f"Postcode {postcode} added for brand {brand.slug}.", "success")
            return redirect(url_for("admin.postcodes"))

    # List postcodes for this brand
    postcodes = (
        MonitoredPostcode.query.filter_by(brand_id=brand.id)
        .order_by(MonitoredPostcode.is_active.desc(), MonitoredPostcode.postcode.asc())
        .all()
    )

    return render_template(
        "admin/postcodes.html",
        form=form,
        postcodes=postcodes,
        brand=brand,
    )


@bp.route("/postcodes/<int:pc_id>/toggle", methods=["POST"])
@login_required
def toggle_postcode(pc_id: int):
    _require_admin()
    brand = current_user.brand or Brand.get_default_brand()

    pc = MonitoredPostcode.query.filter_by(id=pc_id, brand_id=brand.id).first_or_404()
    pc.is_active = not pc.is_active
    db.session.commit()
    flash(
        f"Postcode {pc.postcode} is now "
        f"{'active' if pc.is_active else 'inactive'}.",
        "info",
    )
    return redirect(url_for("admin.postcodes"))
