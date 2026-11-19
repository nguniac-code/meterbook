import os
from contextlib import contextmanager
from datetime import date
from decimal import Decimal, InvalidOperation
import psycopg2
import psycopg2.errors
import psycopg2.extras
import hmac
import hmac
from urllib.parse import urlparse
from flask import (Flask, flash, jsonify, redirect, render_template,
                   request, session, url_for)
from dotenv import load_dotenv
from flask import Flask, flash, jsonify, redirect, render_template, request, session, url_for
import hmac
from urllib.parse import urlparse

load_dotenv()
app = Flask(__name__)
app.secret_key = os.environ.get("FLASK_SECRET_KEY", "meterbook-secret-key-123")

# =====================================================================
# LOGIN (set APP_USERNAME / APP_PASSWORD in .env)
# =====================================================================
APP_USERNAME = os.environ.get("APP_USERNAME", "admin")
APP_PASSWORD = os.environ.get("APP_PASSWORD", "change-me-123")

@app.before_request
def require_login():
    if request.endpoint in ("login", "static"):
        return None
    if not session.get("logged_in"):
        if request.path.startswith("/api/"):
            return jsonify(error="login required"), 401
        return redirect(url_for("login", next=request.full_path.rstrip("?")))
    return None

@app.route("/login", methods=["GET", "POST"])
def login():
    if session.get("logged_in"):
        return redirect("/")
    if request.method == "POST":
        u = request.form.get("username", "").strip()
        p = request.form.get("password", "")
        if hmac.compare_digest(u.encode(), APP_USERNAME.encode()) and hmac.compare_digest(p.encode(), APP_PASSWORD.encode()):
            session.clear()
            session["logged_in"] = True
            nxt = request.args.get("next", "")
            if nxt.startswith("/") and not nxt.startswith("//") and not urlparse(nxt).netloc:
                return redirect(nxt)
            return redirect("/")
        flash("Wrong username or password.", "bad")
    return render_template("dlogin.html")

@app.route("/logout")
def logout():
    session.clear()
    return redirect(url_for("login"))

# =====================================================================
# LOCAL POSTGRESQL CONNECTION
# =====================================================================
DB_CONFIG = {
    "host": os.environ.get("PGHOST", "127.0.0.1"),
    "dbname": os.environ.get("PGDATABASE", "meter_readings_db"),
    "user": os.environ.get("PGUSER", "postgres"),
    "password": os.environ.get("PGPASSWORD", ""),
    "port": int(os.environ.get("PGPORT", "5432")),
}

HIGH_USE_FACTOR = 3

SCHEMA = """
CREATE TABLE IF NOT EXISTS meters (
    id SERIAL PRIMARY KEY,
    meter_number TEXT NOT NULL UNIQUE,
    customer_name TEXT NOT NULL,
    area TEXT NOT NULL,
    address TEXT,
    meter_type TEXT NOT NULL DEFAULT 'Prepaid',
    initial_reading NUMERIC NOT NULL DEFAULT 0,
    installed_on DATE,
    active BOOLEAN NOT NULL DEFAULT TRUE,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS meter_readings (
    id SERIAL PRIMARY KEY,
    meter_number TEXT NOT NULL,
    customer_name TEXT NOT NULL,
    area TEXT NOT NULL,
    previous_reading NUMERIC NOT NULL,
    current_reading NUMERIC NOT NULL,
    consumption NUMERIC NOT NULL,
    reading_date DATE NOT NULL,
    notes TEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

ALTER TABLE meter_readings ADD COLUMN IF NOT EXISTS status TEXT NOT NULL DEFAULT 'correct';
ALTER TABLE meter_readings ADD COLUMN IF NOT EXISTS flag_reason TEXT;

INSERT INTO meters (meter_number, customer_name, area, initial_reading)
SELECT DISTINCT ON (meter_number) meter_number, customer_name, area, previous_reading
FROM meter_readings
ORDER BY meter_number, id
ON CONFLICT (meter_number) DO NOTHING;
"""

def get_db():
    return psycopg2.connect(**DB_CONFIG)

@contextmanager
def db():
    conn = get_db()
    try:
        cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
        yield cur
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()

def init_db():
    with db() as cur:
        cur.execute(SCHEMA)

@app.template_filter("num")
def num(value):
    if value is None:
        return ""
    text = format(Decimal(value), "f")
    if "." in text:
        text = text.rstrip("0").rstrip(".")
    return text

def pct(part, total):
    if not total:
        return None
    return round(100.0 * part / total, 1)

def baseline_reading(cur, meter):
    cur.execute(
        """SELECT current_reading FROM meter_readings
           WHERE meter_number = %s AND status = 'correct'
           ORDER BY reading_date DESC, id DESC LIMIT 1""",
        (meter["meter_number"],),
    )
    row = cur.fetchone()
    return row["current_reading"] if row else meter["initial_reading"]

def check_reading(cur, meter_number, previous, current):
    used = current - previous
    if used < 0:
        return "flagged", "Lower than the previous reading"
    if used == 0:
        return "flagged", "No consumption (meter may be stuck or empty house)"
    
    cur.execute(
        """SELECT consumption FROM meter_readings
           WHERE meter_number = %s AND status = 'correct' AND consumption > 0
           ORDER BY reading_date DESC, id DESC LIMIT 6""",
        (meter_number,),
    )
    history = [r["consumption"] for r in cur.fetchall()]
    if len(history) >= 2:
        usual = sum(history) / len(history)
        if used > HIGH_USE_FACTOR * usual:
            return "flagged", f"Unusually high (over {HIGH_USE_FACTOR}x the usual use)"
    return "correct", None

@app.route("/")
def dashboard():
    period = "all" if request.args.get("period") == "all" else "month"
    cond = "r.reading_date >= date_trunc('month', CURRENT_DATE)" if period == "month" else "TRUE"
        
    with db() as cur:
        cur.execute(f"SELECT COUNT(*) AS total, COUNT(*) FILTER (WHERE r.status = 'correct') AS correct, COUNT(*) FILTER (WHERE r.status = 'flagged') AS flagged FROM meter_readings r WHERE {cond}")
        totals = cur.fetchone()
        
        cur.execute("SELECT COUNT(*) AS n FROM meters WHERE active")
        meter_count = cur.fetchone()["n"]
        
        cur.execute(f"SELECT COUNT(DISTINCT r.meter_number) AS n FROM meter_readings r JOIN meters m ON m.meter_number = r.meter_number AND m.active WHERE {cond}")
        meters_read = cur.fetchone()["n"]
        
        cur.execute(f"SELECT m.meter_number, m.customer_name, m.area FROM meters m WHERE m.active AND NOT EXISTS (SELECT 1 FROM meter_readings r WHERE r.meter_number = m.meter_number AND {cond}) ORDER BY m.area, m.meter_number LIMIT 8")
        unread = cur.fetchall()
        
        cur.execute(f"SELECT r.flag_reason, COUNT(*) AS n FROM meter_readings r WHERE r.status = 'flagged' AND {cond} GROUP BY r.flag_reason ORDER BY n DESC")
        reasons = cur.fetchall()
        
        cur.execute(f"SELECT r.area, COUNT(*) AS total, COUNT(*) FILTER (WHERE r.status = 'flagged') AS flagged FROM meter_readings r WHERE {cond} GROUP BY r.area ORDER BY r.area")
        areas = cur.fetchall()
        
        cur.execute(f"SELECT * FROM meter_readings r WHERE r.status = 'flagged' AND {cond} ORDER BY r.id DESC LIMIT 6")
        recent_flagged = cur.fetchall()

    for a in areas:
        a["error_pct"] = pct(a["flagged"], a["total"])

    return render_template("dashboard.html", period=period, totals=totals, correct_pct=pct(totals["correct"], totals["total"]), flagged_pct=pct(totals["flagged"], totals["total"]), meter_count=meter_count, meters_read=meters_read, unread_total=meter_count - meters_read, unread=unread, reasons=reasons, areas=areas, recent_flagged=recent_flagged, active="dashboard")

@app.route("/meters")
def meters():
    with db() as cur:
        cur.execute("""SELECT m.*, (SELECT COUNT(*) FROM meter_readings r WHERE r.meter_number = m.meter_number) AS n_readings, (SELECT COUNT(*) FROM meter_readings r WHERE r.meter_number = m.meter_number AND r.status = 'flagged') AS n_flagged, (SELECT MAX(reading_date) FROM meter_readings r WHERE r.meter_number = m.meter_number) AS last_read FROM meters m ORDER BY m.area, m.meter_number""")
        rows = cur.fetchall()
    return render_template("meters.html", rows=rows, active="meters")

@app.route("/meters/register", methods=["GET", "POST"])
def register():
    with db() as cur:
        cur.execute("SELECT DISTINCT area FROM meters ORDER BY area")
        areas = [r["area"] for r in cur.fetchall()]

    if request.method == "GET":
        return render_template("register.html", areas=areas, form={"meter_number": request.args.get("meter", "").strip().upper()}, active="register")

    form = {k: request.form.get(k, "").strip() for k in ("meter_number", "customer_name", "area", "address", "meter_type", "initial_reading", "installed_on")}
    form["meter_number"] = form["meter_number"].upper()

    def again(message):
        flash(message, "bad")
        return render_template("register.html", areas=areas, form=form, active="register")

    if not form["meter_number"] or not form["customer_name"] or not form["area"]:
        return again("Meter number, customer name and area are all needed.")

    try:
        initial = Decimal(form["initial_reading"] or "0")
    except InvalidOperation:
        return again("The starting reading has to be a number.")

    if initial < 0:
        return again("The starting reading can't be negative.")

    installed = None
    if form["installed_on"]:
        try:
            installed = date.fromisoformat(form["installed_on"])
        except ValueError:
            return again("That installation date doesn't look right.")

    try:
        with db() as cur:
            cur.execute("""INSERT INTO meters (meter_number, customer_name, area, address, meter_type, initial_reading, installed_on) VALUES (%s, %s, %s, %s, %s, %s, %s)""",
                (form["meter_number"], form["customer_name"], form["area"], form["address"] or None, form["meter_type"] or "Prepaid", initial, installed))
    except psycopg2.errors.UniqueViolation:
        return again("A meter with the number %s is already registered." % form["meter_number"])

    flash("Meter %s registered for %s." % (form["meter_number"], form["customer_name"]), "ok")
    return redirect(url_for("meters"))

@app.route("/api/meter/<meter_number>")
def meter_lookup(meter_number):
    with db() as cur:
        cur.execute("SELECT * FROM meters WHERE meter_number = %s", (meter_number.strip().upper(),))
        meter = cur.fetchone()
    if not meter:
        return jsonify(found=False)
    with db() as cur:
        previous = baseline_reading(cur, meter)
    return jsonify(found=True, customer_name=meter["customer_name"], area=meter["area"], previous_reading=num(previous))

@app.route("/entry")
def entry():
    with db() as cur:
        cur.execute("SELECT meter_number, customer_name FROM meters WHERE active ORDER BY meter_number")
        meter_list = cur.fetchall()
    return render_template("entry.html", meter_list=meter_list, today=date.today().isoformat(), prefill=request.args.get("meter", "").strip().upper(), active="entry")

@app.route("/submit", methods=["POST"])
def submit():
    meter_number = request.form.get("meter_number", "").strip().upper()
    notes = request.form.get("notes", "").strip()
    back = url_for("entry", meter=meter_number)

    try:
        current = Decimal(request.form.get("current_reading", ""))
    except InvalidOperation:
        flash("The reading has to be a number. Please check and try again.", "bad")
        return redirect(back)

    try:
        reading_date = date.fromisoformat(request.form.get("reading_date", ""))
    except ValueError:
        flash("Please pick the date of the reading.", "bad")
        return redirect(back)

    if reading_date > date.today():
        flash("The reading date can't be in the future.", "bad")
        return redirect(back)

    with db() as cur:
        cur.execute("SELECT * FROM meters WHERE meter_number = %s", (meter_number,))
        meter = cur.fetchone()
        if not meter:
            flash("Meter %s is not registered yet. Register it first." % meter_number, "bad")
            return redirect(url_for("register", meter=meter_number))

        previous = baseline_reading(cur, meter)
        status, reason = check_reading(cur, meter_number, previous, current)
        used = current - previous

        cur.execute("""INSERT INTO meter_readings (meter_number, customer_name, area, previous_reading, current_reading, consumption, reading_date, notes, status, flag_reason) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)""",
            (meter_number, meter["customer_name"], meter["area"], previous, current, used, reading_date, notes, status, reason))

    if status == "correct":
        flash("Saved. %s used %s units since the last reading." % (meter_number, num(used)), "ok")
    else:
        flash("Saved, but flagged: %s. Please look at the meter again if you can." % reason, "warn")

    return redirect(url_for("records"))

@app.route("/records")
def records():
    status = request.args.get("status", "all")
    where = ""
    if status == "flagged":
        where = "WHERE status = 'flagged'"
    elif status == "correct":
        where = "WHERE status = 'correct'"
    else:
        status = "all"

    with db() as cur:
        cur.execute(f"SELECT * FROM meter_readings {where} ORDER BY reading_date DESC, id DESC LIMIT 300")
        rows = cur.fetchall()
        
    return render_template("records.html", rows=rows, status=status, active="records")

if __name__ == "__main__":
    init_db()
    app.run(debug=True, host="0.0.0.0", port=5000)