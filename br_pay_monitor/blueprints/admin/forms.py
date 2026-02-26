# br_pay_monitor/blueprints/admin/forms.py

from flask_wtf import FlaskForm
from wtforms import StringField, FloatField, SubmitField, BooleanField, SelectField
from wtforms.validators import DataRequired, Email


class PostcodeForm(FlaskForm):
    postcode = StringField("Postcode", validators=[DataRequired()])
    radius_miles = FloatField("Radius (miles)", default=25.0, validators=[DataRequired()])
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
    postcode_id = SelectField("Linked postcode", coerce=int, validators=[DataRequired()])
    submit = SubmitField("Save")