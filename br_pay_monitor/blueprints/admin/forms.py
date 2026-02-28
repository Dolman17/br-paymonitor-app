# br_pay_monitor/blueprints/admin/forms.py

from flask_wtf import FlaskForm
from wtforms import (
    StringField,
    FloatField,
    SubmitField,
    BooleanField,
    SelectField,
    PasswordField,
)
from wtforms.validators import DataRequired, Email, Optional, Length, EqualTo


class PostcodeForm(FlaskForm):
    postcode = StringField("Postcode", validators=[DataRequired()])
    radius_miles = FloatField(
        "Radius (miles)",
        default=25.0,
        validators=[DataRequired()],
    )
    display_name = StringField("Label (optional)")
    submit = SubmitField("Add postcode")


class EmailRecipientForm(FlaskForm):
    email = StringField("Email address", validators=[DataRequired(), Email()])
    is_active = BooleanField("Active", default=True)

    include_blue_ribbon = BooleanField("Include Blue Ribbon")
    include_forevermore = BooleanField("Include Forevermore Care")

    submit = SubmitField("Save")


class MonitoredRoleForm(FlaskForm):
    name = StringField("Role name", validators=[DataRequired()])
    search_terms = StringField("Search terms (optional)")
    postcode_id = SelectField(
        "Linked postcode",
        coerce=int,
        validators=[DataRequired()],
    )
    submit = SubmitField("Save")


class CreateUserForm(FlaskForm):
    email = StringField("Email address", validators=[DataRequired(), Email()])

    password = PasswordField(
        "Password",
        validators=[
            DataRequired(),
            Length(min=8, message="Password must be at least 8 characters."),
        ],
    )
    confirm_password = PasswordField(
        "Confirm password",
        validators=[
            DataRequired(),
            EqualTo("password", message="Passwords must match."),
        ],
    )

    is_admin = BooleanField("Admin", default=False)
    is_active = BooleanField("Active", default=True)

    # Optional brand assignment. We include a 'None' option with value 0.
    brand_id = SelectField(
        "Brand",
        coerce=int,
        validators=[Optional()],
        choices=[],
        description="Assign which brand this user sees by default (optional).",
    )

    submit = SubmitField("Create user")


class EditUserForm(FlaskForm):
    email = StringField("Email address", validators=[DataRequired(), Email()])

    # Password reset is optional on edit
    password = PasswordField(
        "New password (leave blank to keep)",
        validators=[
            Optional(),
            Length(min=8, message="Password must be at least 8 characters."),
        ],
    )
    confirm_password = PasswordField(
        "Confirm new password",
        validators=[
            Optional(),
            EqualTo("password", message="Passwords must match."),
        ],
    )

    is_admin = BooleanField("Admin")
    is_active = BooleanField("Active")

    # Optional brand assignment. We include a 'None' option with value 0.
    brand_id = SelectField(
        "Brand",
        coerce=int,
        validators=[Optional()],
        choices=[],
        description="Assign which brand this user sees by default (optional).",
    )

    submit = SubmitField("Save changes")