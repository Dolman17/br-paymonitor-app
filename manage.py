# manage.py

from br_pay_monitor import create_app

app = create_app()

if __name__ == "__main__":
    app.run(debug=True)
