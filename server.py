from flask import Flask, render_template
from datetime import date

app = Flask(__name__)

@app.route("/")
def home():
    today = date.today()
    current_year = today.year
    return render_template("index.html", current_year=current_year)


if __name__ == "__main__":
    app.run()