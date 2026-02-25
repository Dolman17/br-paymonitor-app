# br_pay_monitor/blueprints/admin/forms.py

from flask_wtf import FlaskForm
from wtforms import StringField, FloatField, SubmitField
from wtforms.validators import DataRequired


class PostcodeForm(FlaskForm):
    postcode = StringField("Postcode", validators=[DataRequired()])
    radius_miles = FloatField("Radius (miles)", default=25.0, validators=[DataRequired()])
    display_name = StringField("Label (optional)")
    submit = SubmitField("Add postcode")
