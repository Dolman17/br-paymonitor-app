# br_pay_monitor/blueprints/admin/routes.py

from flask import render_template, redirect, url_for, flash, abort, request
from flask_login import login_required, current_user

from . import bp
from .forms import PostcodeForm, EmailRecipientForm, MonitoredRoleForm
from ...extensions import db
from ...models import MonitoredPostcode, Brand, EmailRecipient, MonitoredRole


def _require_admin():
    if not current_user.is_authenticated:
        abort(401)
    if not current_user.is_admin:
        abort(403)


def _current_brand() -> Brand:
    return current_user.brand or Brand.get_default_brand()


# -------- Postcodes management -------- #


@bp.route("/postcodes", methods=["GET", "POST"])
@login_required
def postcodes():
    _require_admin()

    brand = _current_brand()

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
    brand = _current_brand()

    pc = MonitoredPostcode.query.filter_by(id=pc_id, brand_id=brand.id).first_or_404()
    pc.is_active = not pc.is_active
    db.session.commit()
    flash(
        f"Postcode {pc.postcode} is now "
        f"{'active' if pc.is_active else 'inactive'}.",
        "info",
    )
    return redirect(url_for("admin.postcodes"))


# -------- Email recipients management (multi-brand) -------- #


@bp.route("/recipients", methods=["GET", "POST"])
@login_required
def recipients():
    _require_admin()
    # Still use current_brand for header / navigation context
    brand = _current_brand()

    form = EmailRecipientForm()
    if form.validate_on_submit():
        email = form.email.data.strip().lower()
        is_active = bool(form.is_active.data)
        include_br = bool(form.include_blue_ribbon.data)
        include_fmc = bool(form.include_forevermore.data)

        existing = EmailRecipient.query.filter_by(email=email).first()
        if existing:
            flash("That email address is already in the recipient list.", "warning")
        else:
            r = EmailRecipient(
                email=email,
                is_active=is_active,
                include_blue_ribbon=include_br,
                include_forevermore=include_fmc,
            )
            db.session.add(r)
            db.session.commit()
            flash(f"Recipient {email} added.", "success")
            return redirect(url_for("admin.recipients"))

    recipients = (
        EmailRecipient.query.order_by(EmailRecipient.email.asc()).all()
    )

    return render_template(
        "admin/recipients.html",
        form=form,
        recipients=recipients,
        brand=brand,
    )


@bp.route("/recipients/<int:recipient_id>/edit", methods=["GET", "POST"])
@login_required
def edit_recipient(recipient_id: int):
    _require_admin()
    brand = _current_brand()

    recipient = EmailRecipient.query.filter_by(id=recipient_id).first_or_404()

    form = EmailRecipientForm(obj=recipient)
    if form.validate_on_submit():
        email = form.email.data.strip().lower()
        is_active = bool(form.is_active.data)
        include_br = bool(form.include_blue_ribbon.data)
        include_fmc = bool(form.include_forevermore.data)

        existing = EmailRecipient.query.filter(
            EmailRecipient.email == email,
            EmailRecipient.id != recipient.id,
        ).first()
        if existing:
            flash("Another recipient already uses that email address.", "warning")
        else:
            recipient.email = email
            recipient.is_active = is_active
            recipient.include_blue_ribbon = include_br
            recipient.include_forevermore = include_fmc
            db.session.commit()
            flash("Recipient updated.", "success")
            return redirect(url_for("admin.recipients"))

    # Ensure checkboxes reflect current state on GET
    if request.method == "GET":
        form.include_blue_ribbon.data = recipient.include_blue_ribbon
        form.include_forevermore.data = recipient.include_forevermore

    return render_template(
        "admin/edit_recipient.html",
        form=form,
        recipient=recipient,
        brand=brand,
    )


@bp.route("/recipients/<int:recipient_id>/delete", methods=["POST"])
@login_required
def delete_recipient(recipient_id: int):
    _require_admin()
    brand = _current_brand()

    recipient = EmailRecipient.query.filter_by(id=recipient_id).first_or_404()

    email = recipient.email
    db.session.delete(recipient)
    db.session.commit()
    flash(f"Recipient {email} deleted.", "info")
    return redirect(url_for("admin.recipients"))


# -------- Monitored roles management -------- #


@bp.route("/roles", methods=["GET", "POST"])
@login_required
def roles():
    _require_admin()
    brand = _current_brand()

    postcodes = (
        MonitoredPostcode.query.filter_by(brand_id=brand.id, is_active=True)
        .order_by(MonitoredPostcode.postcode.asc())
        .all()
    )

    form = MonitoredRoleForm()
    form.postcode_id.choices = [(pc.id, pc.display_name or pc.postcode) for pc in postcodes]

    if form.validate_on_submit():
        name = form.name.data.strip()
        search_terms = (form.search_terms.data or "").strip()
        postcode_id = form.postcode_id.data

        pc = MonitoredPostcode.query.filter_by(
            id=postcode_id, brand_id=brand.id
        ).first()
        if not pc:
            flash("Invalid postcode selection.", "danger")
        else:
            role = MonitoredRole(
                brand=brand,
                postcode=pc,
                name=name,
                search_terms=search_terms or name,
                is_active=True,
            )
            db.session.add(role)
            db.session.commit()
            flash(f"Role '{name}' added for {pc.postcode}.", "success")
            return redirect(url_for("admin.roles"))

    roles = (
        MonitoredRole.query.filter_by(brand_id=brand.id)
        .order_by(MonitoredRole.is_active.desc(), MonitoredRole.name.asc())
        .all()
    )

    return render_template(
        "admin/roles.html",
        form=form,
        roles=roles,
        postcodes=postcodes,
        brand=brand,
    )


@bp.route("/roles/<int:role_id>/edit", methods=["GET", "POST"])
@login_required
def edit_role(role_id: int):
    _require_admin()
    brand = _current_brand()

    role = MonitoredRole.query.filter_by(
        id=role_id, brand_id=brand.id
    ).first_or_404()

    postcodes = (
        MonitoredPostcode.query.filter_by(brand_id=brand.id, is_active=True)
        .order_by(MonitoredPostcode.postcode.asc())
        .all()
    )

    form = MonitoredRoleForm(obj=role)
    form.postcode_id.choices = [(pc.id, pc.display_name or pc.postcode) for pc in postcodes]
    if role.postcode_id:
        form.postcode_id.data = role.postcode_id

    if form.validate_on_submit():
        name = form.name.data.strip()
        search_terms = (form.search_terms.data or "").strip()
        postcode_id = form.postcode_id.data

        pc = MonitoredPostcode.query.filter_by(
            id=postcode_id, brand_id=brand.id
        ).first()
        if not pc:
            flash("Invalid postcode selection.", "danger")
        else:
            role.name = name
            role.search_terms = search_terms or name
            role.postcode = pc
            db.session.commit()
            flash("Role updated.", "success")
            return redirect(url_for("admin.roles"))

    return render_template(
        "admin/edit_role.html",
        form=form,
        role=role,
        brand=brand,
    )


@bp.route("/roles/<int:role_id>/delete", methods=["POST"])
@login_required
def delete_role(role_id: int):
    _require_admin()
    brand = _current_brand()

    role = MonitoredRole.query.filter_by(
        id=role_id, brand_id=brand.id
    ).first_or_404()

    name = role.name
    db.session.delete(role)
    db.session.commit()
    flash(f"Role '{name}' deleted.", "info")
    return redirect(url_for("admin.roles"))