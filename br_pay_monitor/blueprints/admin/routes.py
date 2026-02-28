# br_pay_monitor/blueprints/admin/routes.py

from datetime import datetime, timedelta

from flask import (
    render_template,
    redirect,
    url_for,
    flash,
    abort,
    request,
    current_app,
)
from flask_login import login_required, current_user
from sqlalchemy import func, case

from . import bp
from .forms import (
    PostcodeForm,
    EmailRecipientForm,
    MonitoredRoleForm,
    CreateUserForm,
    EditUserForm,
)
from ...extensions import db
from ...models import (
    MonitoredPostcode,
    Brand,
    EmailRecipient,
    MonitoredRole,
    ScrapeRun,
    User,
)


def _require_admin():
    if not current_user.is_authenticated:
        abort(401)
    if not current_user.is_admin:
        abort(403)


def _current_brand() -> Brand:
    return current_user.brand or Brand.get_default_brand()


def _brand_choices():
    brands = Brand.query.order_by(Brand.slug.asc()).all()
    # 0 means "no brand assigned" (falls back to default brand in dashboard)
    return [(0, "— No brand (default) —")] + [(b.id, f"{b.name} ({b.slug})") for b in brands]


# -------- Adzuna usage -------- #


@bp.route("/adzuna-usage", methods=["GET"])
@login_required
def adzuna_usage():
    _require_admin()
    brand = _current_brand()

    daily_budget = int(current_app.config.get("ADZUNA_DAILY_BUDGET", 200))

    # Today (UTC)
    start_today = datetime.utcnow().replace(hour=0, minute=0, second=0, microsecond=0)
    end_today = start_today + timedelta(days=1)

    today_used = (
        db.session.query(func.coalesce(func.sum(ScrapeRun.api_calls), 0))
        .filter(
            ScrapeRun.brand_id == brand.id,
            ScrapeRun.started_at >= start_today,
            ScrapeRun.started_at < end_today,
        )
        .scalar()
        or 0
    )
    today_used = int(today_used)
    today_remaining = max(0, daily_budget - today_used)

    # Last 7 days (UTC day buckets)
    start_7 = (start_today - timedelta(days=6)).date()
    end_7 = (start_today + timedelta(days=1)).date()

    rows = (
        db.session.query(
            func.date(ScrapeRun.started_at).label("day"),
            func.coalesce(func.sum(ScrapeRun.api_calls), 0).label("calls"),
            func.count(ScrapeRun.id).label("runs"),
            func.coalesce(
                func.sum(case((ScrapeRun.success.is_(True), 1), else_=0)),
                0,
            ).label("success_runs"),
        )
        .filter(
            ScrapeRun.brand_id == brand.id,
            func.date(ScrapeRun.started_at) >= start_7,
            func.date(ScrapeRun.started_at) < end_7,
        )
        .group_by(func.date(ScrapeRun.started_at))
        .order_by(func.date(ScrapeRun.started_at).asc())
        .all()
    )

    # Fill missing days with zeros so the table is stable
    by_day = {str(r.day): r for r in rows}
    last_7 = []
    for i in range(6, -1, -1):
        d = (start_today.date() - timedelta(days=i))
        key = str(d)
        r = by_day.get(key)

        calls = int(r.calls) if r else 0
        runs = int(r.runs) if r else 0
        success_runs = int(r.success_runs) if r else 0

        usage_pct = (calls / daily_budget * 100.0) if daily_budget else 0.0
        success_rate_pct = (success_runs / runs * 100.0) if runs else 0.0

        last_7.append(
            {
                "day": d,
                "calls": calls,
                "runs": runs,
                "success_runs": success_runs,
                "success_rate_pct": success_rate_pct,
                "budget": daily_budget,
                "remaining": max(0, daily_budget - calls),
                "pct": usage_pct,
            }
        )

    week_total = sum(x["calls"] for x in last_7)
    week_runs = sum(x["runs"] for x in last_7)
    week_success_runs = sum(x["success_runs"] for x in last_7)
    week_success_rate_pct = (
        (week_success_runs / week_runs * 100.0) if week_runs else 0.0
    )

    return render_template(
        "admin/adzuna_usage.html",
        brand=brand,
        daily_budget=daily_budget,
        today_used=today_used,
        today_remaining=today_remaining,
        last_7=last_7,
        week_total=week_total,
        week_runs=week_runs,
        week_success_runs=week_success_runs,
        week_success_rate_pct=week_success_rate_pct,
    )


# -------- Users management -------- #


@bp.route("/users", methods=["GET"])
@login_required
def users():
    _require_admin()
    brand = _current_brand()

    # Show all users, grouped/sortable by brand.
    all_users = (
        User.query.outerjoin(Brand, User.brand_id == Brand.id)
        .order_by(
            User.is_admin.desc(),
            User.is_active.desc(),
            Brand.slug.asc().nullslast(),
            User.email.asc(),
        )
        .all()
    )

    return render_template(
        "admin/users.html",
        brand=brand,
        users=all_users,
    )


@bp.route("/users/new", methods=["GET", "POST"])
@login_required
def create_user():
    _require_admin()
    brand = _current_brand()

    form = CreateUserForm()
    form.brand_id.choices = _brand_choices()

    if form.validate_on_submit():
        email = form.email.data.lower().strip()
        existing = User.query.filter_by(email=email).first()
        if existing:
            flash("That email address is already in use.", "warning")
            return redirect(url_for("admin.create_user"))

        user = User(
            email=email,
            is_admin=bool(form.is_admin.data),
            is_active=bool(form.is_active.data),
        )

        selected_brand_id = int(form.brand_id.data or 0)
        if selected_brand_id and selected_brand_id != 0:
            b = Brand.query.get(selected_brand_id)
            if b:
                user.brand = b
        else:
            user.brand = None

        user.set_password(form.password.data)

        db.session.add(user)
        db.session.commit()

        flash(f"User {email} created.", "success")
        return redirect(url_for("admin.users"))

    return render_template(
        "admin/new_user.html",
        form=form,
        brand=brand,
    )


@bp.route("/users/<int:user_id>/edit", methods=["GET", "POST"])
@login_required
def edit_user(user_id: int):
    _require_admin()
    brand = _current_brand()

    user = User.query.filter_by(id=user_id).first_or_404()

    form = EditUserForm(obj=user)
    form.brand_id.choices = _brand_choices()

    # Populate brand select on GET
    if request.method == "GET":
        form.brand_id.data = user.brand_id or 0

    if form.validate_on_submit():
        new_email = form.email.data.lower().strip()

        existing = User.query.filter(
            User.email == new_email,
            User.id != user.id,
        ).first()
        if existing:
            flash("Another user already uses that email address.", "warning")
            return redirect(url_for("admin.edit_user", user_id=user.id))

        # Prevent an admin from locking themselves out.
        if user.id == current_user.id:
            if not bool(form.is_admin.data):
                flash("You cannot remove your own admin access.", "danger")
                return redirect(url_for("admin.edit_user", user_id=user.id))
            if not bool(form.is_active.data):
                flash("You cannot deactivate your own account.", "danger")
                return redirect(url_for("admin.edit_user", user_id=user.id))

        user.email = new_email
        user.is_admin = bool(form.is_admin.data)
        user.is_active = bool(form.is_active.data)

        selected_brand_id = int(form.brand_id.data or 0)
        if selected_brand_id and selected_brand_id != 0:
            b = Brand.query.get(selected_brand_id)
            user.brand = b if b else None
        else:
            user.brand = None

        # Optional password reset
        if form.password.data:
            user.set_password(form.password.data)

        db.session.commit()
        flash("User updated.", "success")
        return redirect(url_for("admin.users"))

    return render_template(
        "admin/edit_user.html",
        form=form,
        user=user,
        brand=brand,
    )


@bp.route("/users/<int:user_id>/delete", methods=["POST"])
@login_required
def delete_user(user_id: int):
    _require_admin()

    user = User.query.filter_by(id=user_id).first_or_404()

    if user.id == current_user.id:
        flash("You cannot delete your own account.", "danger")
        return redirect(url_for("admin.users"))

    email = user.email
    db.session.delete(user)
    db.session.commit()
    flash(f"User {email} deleted.", "info")
    return redirect(url_for("admin.users"))


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

    recipients = EmailRecipient.query.order_by(EmailRecipient.email.asc()).all()

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

        pc = MonitoredPostcode.query.filter_by(id=postcode_id, brand_id=brand.id).first()
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

    role = MonitoredRole.query.filter_by(id=role_id, brand_id=brand.id).first_or_404()

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

        pc = MonitoredPostcode.query.filter_by(id=postcode_id, brand_id=brand.id).first()
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

    role = MonitoredRole.query.filter_by(id=role_id, brand_id=brand.id).first_or_404()

    name = role.name
    db.session.delete(role)
    db.session.commit()
    flash(f"Role '{name}' deleted.", "info")
    return redirect(url_for("admin.roles"))