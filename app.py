import os
import uuid
from datetime import datetime, date
from flask import (
    Flask, render_template, request, redirect,
    url_for, flash, abort, g
)

import config
import database as db_module
from services import pdf_parser, matcher, statement as stmt_svc

app = Flask(__name__)
app.secret_key = config.SECRET_KEY
app.config["UPLOAD_FOLDER"] = config.UPLOAD_FOLDER

os.makedirs(config.UPLOAD_FOLDER, exist_ok=True)

# ── Init DB on startup ────────────────────────────────────────────────────────
with app.app_context():
    db_module.init_db()


# ── IP Guard ──────────────────────────────────────────────────────────────────
@app.before_request
def check_ip():
    # Allow Render health checks from localhost
    ip = request.remote_addr
    db = db_module.get_db()
    allowed = db.execute(
        "SELECT 1 FROM allowed_ips WHERE ip_address = ?", (ip,)
    ).fetchone()
    db.close()
    if not allowed:
        abort(403)


@app.context_processor
def inject_globals():
    def unmatched_badge():
        conn = db_module.get_db()
        n = conn.execute(
            "SELECT COUNT(*) FROM transactions WHERE student_id IS NULL"
        ).fetchone()[0]
        conn.close()
        return n
    return {
        "daycare_name": config.DAYCARE_NAME,
        "current_month": datetime.now().strftime("%Y-%m"),
        "now": datetime.now(),
        "unmatched_badge": unmatched_badge,
    }


def get_db():
    if "db" not in g:
        g.db = db_module.get_db()
    return g.db


@app.teardown_appcontext
def close_db(e=None):
    db = g.pop("db", None)
    if db:
        db.close()


# ── Dashboard ─────────────────────────────────────────────────────────────────
@app.route("/")
def dashboard():
    db = get_db()
    month = datetime.now().strftime("%Y-%m")

    total_students  = db.execute("SELECT COUNT(*) FROM students WHERE is_active=1").fetchone()[0]
    unmatched_count = db.execute("SELECT COUNT(*) FROM transactions WHERE student_id IS NULL").fetchone()[0]
    this_month_paid = db.execute(
        "SELECT COALESCE(SUM(amount),0) FROM transactions WHERE date LIKE ? AND student_id IS NOT NULL",
        (f"{month}%",)
    ).fetchone()[0]
    recent_tx = db.execute("""
        SELECT t.*, s.first_name, s.last_name
        FROM transactions t
        LEFT JOIN students s ON t.student_id = s.id
        ORDER BY t.imported_at DESC LIMIT 8
    """).fetchall()

    statuses    = stmt_svc.get_all_statuses(month)
    paid_count  = sum(1 for s in statuses if s["status"] == "paid")
    unpaid_count= sum(1 for s in statuses if s["status"] in ("unpaid", "partial"))

    return render_template("dashboard.html",
        total_students=total_students,
        unmatched_count=unmatched_count,
        this_month_paid=this_month_paid,
        recent_tx=recent_tx,
        paid_count=paid_count,
        unpaid_count=unpaid_count,
        month=month,
    )


# ── Upload ────────────────────────────────────────────────────────────────────
@app.route("/upload", methods=["GET", "POST"])
def upload():
    if request.method == "POST":
        f = request.files.get("statement")
        if not f or not f.filename.endswith(".pdf"):
            flash("Please upload a PDF file.", "danger")
            return redirect(url_for("upload"))

        batch_id = str(uuid.uuid4())[:8]
        path = os.path.join(app.config["UPLOAD_FOLDER"], f"{batch_id}.pdf")
        f.save(path)

        try:
            raw = pdf_parser.parse(path)
        except Exception as e:
            flash(f"Could not read PDF: {e}", "danger")
            return redirect(url_for("upload"))
        finally:
            os.remove(path)

        if not raw:
            flash("No transactions found in the PDF. Check the file format.", "warning")
            return redirect(url_for("upload"))

        matched = matcher.match_transactions(raw)
        students = get_db().execute(
            "SELECT id, first_name, last_name FROM students WHERE is_active=1 ORDER BY last_name"
        ).fetchall()
        return render_template("upload_review.html",
            transactions=matched,
            batch_id=batch_id,
            students=students,
        )

    return render_template("upload.html")


@app.route("/upload/confirm", methods=["POST"])
def upload_confirm():
    db = get_db()
    batch_id = request.form.get("batch_id", "")
    indexes  = [k for k in request.form if k.startswith("accept_")]

    saved = 0
    for key in indexes:
        i = key.split("_")[1]
        date_val  = request.form.get(f"date_{i}")
        desc      = request.form.get(f"desc_{i}")
        amount    = request.form.get(f"amount_{i}")
        ref       = request.form.get(f"ref_{i}", "")
        sid       = request.form.get(f"student_id_{i}") or None
        how       = request.form.get(f"matched_how_{i}", "manual")

        if not date_val or not amount:
            continue

        db.execute("""
            INSERT INTO transactions (date, description, amount, reference, student_id, matched_how, upload_batch)
            VALUES (?, ?, ?, ?, ?, ?, ?)
        """, (date_val, desc, float(amount), ref, sid, how, batch_id))
        saved += 1

    db.commit()
    flash(f"{saved} transactions saved.", "success")
    return redirect(url_for("payments"))


# ── Unmatched ─────────────────────────────────────────────────────────────────
@app.route("/unmatched")
def unmatched():
    db = get_db()
    txs = db.execute("""
        SELECT * FROM transactions WHERE student_id IS NULL ORDER BY date DESC
    """).fetchall()
    students = db.execute(
        "SELECT id, first_name, last_name FROM students WHERE is_active=1 ORDER BY last_name"
    ).fetchall()
    return render_template("unmatched.html", transactions=txs, students=students)


@app.route("/unmatched/assign", methods=["POST"])
def assign_transaction():
    db = get_db()
    tx_id = request.form["tx_id"]
    student_id = request.form["student_id"] or None
    db.execute(
        "UPDATE transactions SET student_id=?, matched_how='manual' WHERE id=?",
        (student_id, tx_id)
    )
    db.commit()
    flash("Transaction assigned.", "success")
    return redirect(url_for("unmatched"))


# ── Students ──────────────────────────────────────────────────────────────────
@app.route("/students")
def students():
    db = get_db()
    rows = db.execute("""
        SELECT s.*, t.name as tier_name, t.monthly_fee
        FROM students s
        LEFT JOIN fee_tiers t ON s.tier_id = t.id
        WHERE s.is_active = 1
        ORDER BY s.last_name, s.first_name
    """).fetchall()
    return render_template("students/list.html", students=rows)


@app.route("/students/new", methods=["GET", "POST"])
def student_new():
    db = get_db()
    tiers = db.execute("SELECT * FROM fee_tiers ORDER BY age_min").fetchall()
    if request.method == "POST":
        db.execute("""
            INSERT INTO students (first_name, last_name, date_of_birth, tier_id,
                                  parent_name, parent_phone, start_date, notes)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            request.form["first_name"], request.form["last_name"],
            request.form.get("date_of_birth") or None,
            request.form.get("tier_id") or None,
            request.form.get("parent_name"), request.form.get("parent_phone"),
            request.form.get("start_date") or None, request.form.get("notes"),
        ))
        db.commit()
        flash("Student added.", "success")
        return redirect(url_for("students"))
    return render_template("students/form.html", student=None, tiers=tiers)


@app.route("/students/<int:sid>")
def student_detail(sid):
    db = get_db()
    student = db.execute("""
        SELECT s.*, t.name as tier_name, t.monthly_fee
        FROM students s LEFT JOIN fee_tiers t ON s.tier_id = t.id
        WHERE s.id = ?
    """, (sid,)).fetchone()
    if not student:
        abort(404)

    transactions = db.execute("""
        SELECT * FROM transactions WHERE student_id = ? ORDER BY date DESC LIMIT 50
    """, (sid,)).fetchall()

    extras = db.execute("""
        SELECT * FROM extra_charges WHERE student_id = ? ORDER BY date DESC LIMIT 20
    """, (sid,)).fetchall()

    month = datetime.now().strftime("%Y-%m")
    this_month = stmt_svc.build(sid, month)

    return render_template("students/detail.html",
        student=student,
        transactions=transactions,
        extras=extras,
        this_month=this_month,
        current_month=month,
    )


@app.route("/students/<int:sid>/edit", methods=["GET", "POST"])
def student_edit(sid):
    db = get_db()
    student = db.execute("SELECT * FROM students WHERE id=?", (sid,)).fetchone()
    tiers   = db.execute("SELECT * FROM fee_tiers ORDER BY age_min").fetchall()
    if not student:
        abort(404)
    if request.method == "POST":
        db.execute("""
            UPDATE students SET first_name=?, last_name=?, date_of_birth=?,
            tier_id=?, parent_name=?, parent_phone=?, start_date=?, notes=?
            WHERE id=?
        """, (
            request.form["first_name"], request.form["last_name"],
            request.form.get("date_of_birth") or None,
            request.form.get("tier_id") or None,
            request.form.get("parent_name"), request.form.get("parent_phone"),
            request.form.get("start_date") or None, request.form.get("notes"),
            sid,
        ))
        db.commit()
        flash("Student updated.", "success")
        return redirect(url_for("student_detail", sid=sid))
    return render_template("students/form.html", student=student, tiers=tiers)


@app.route("/students/<int:sid>/deactivate", methods=["POST"])
def student_deactivate(sid):
    db = get_db()
    db.execute("UPDATE students SET is_active=0 WHERE id=?", (sid,))
    db.commit()
    flash("Student deactivated.", "info")
    return redirect(url_for("students"))


# ── Payments ──────────────────────────────────────────────────────────────────
@app.route("/payments")
def payments():
    db = get_db()
    txs = db.execute("""
        SELECT t.*, s.first_name, s.last_name
        FROM transactions t
        LEFT JOIN students s ON t.student_id = s.id
        ORDER BY t.date DESC LIMIT 100
    """).fetchall()
    students = db.execute(
        "SELECT id, first_name, last_name FROM students WHERE is_active=1 ORDER BY last_name"
    ).fetchall()
    return render_template("payments/list.html", transactions=txs, students=students)


@app.route("/payments/<int:tx_id>/reassign", methods=["POST"])
def payment_reassign(tx_id):
    db = get_db()
    sid = request.form.get("student_id") or None
    db.execute(
        "UPDATE transactions SET student_id=?, matched_how='manual' WHERE id=?",
        (sid, tx_id)
    )
    db.commit()
    flash("Transaction updated.", "success")
    return redirect(url_for("payments"))


@app.route("/payments/<int:tx_id>/delete", methods=["POST"])
def payment_delete(tx_id):
    db = get_db()
    db.execute("DELETE FROM transactions WHERE id=?", (tx_id,))
    db.commit()
    flash("Transaction deleted.", "info")
    return redirect(url_for("payments"))


@app.route("/extras/new", methods=["GET", "POST"])
def extra_new():
    db = get_db()
    students = db.execute(
        "SELECT id, first_name, last_name FROM students WHERE is_active=1 ORDER BY last_name"
    ).fetchall()
    if request.method == "POST":
        db.execute("""
            INSERT INTO extra_charges (student_id, date, description, amount, category)
            VALUES (?, ?, ?, ?, ?)
        """, (
            request.form["student_id"],
            request.form["date"],
            request.form["description"],
            float(request.form["amount"]),
            request.form.get("category", "other"),
        ))
        db.commit()
        flash("Charge added.", "success")
        sid = request.form["student_id"]
        return redirect(url_for("student_detail", sid=sid))
    return render_template("payments/extra_form.html", students=students,
                           today=date.today().isoformat())


@app.route("/extras/<int:eid>/delete", methods=["POST"])
def extra_delete(eid):
    db = get_db()
    row = db.execute("SELECT student_id FROM extra_charges WHERE id=?", (eid,)).fetchone()
    db.execute("DELETE FROM extra_charges WHERE id=?", (eid,))
    db.commit()
    flash("Charge removed.", "info")
    if row:
        return redirect(url_for("student_detail", sid=row["student_id"]))
    return redirect(url_for("payments"))


# ── Statements ────────────────────────────────────────────────────────────────
@app.route("/statements")
def statements():
    month = request.args.get("month", datetime.now().strftime("%Y-%m"))
    statuses = stmt_svc.get_all_statuses(month)
    return render_template("statements/list.html", statuses=statuses, month=month)


@app.route("/statements/<int:sid>/<month>")
def statement_view(sid, month):
    data = stmt_svc.build(sid, month)
    if not data:
        abort(404)
    return render_template("statements/view.html", data=data, month=month)


@app.route("/statements/<int:sid>/<month>/print")
def statement_print(sid, month):
    data = stmt_svc.build(sid, month)
    if not data:
        abort(404)
    return render_template("statements/print.html", data=data, month=month)


@app.route("/statements/<int:sid>/<month>/save", methods=["POST"])
def statement_save(sid, month):
    db = get_db()
    # Get tier fee as default
    student = db.execute("""
        SELECT t.monthly_fee FROM students s
        LEFT JOIN fee_tiers t ON s.tier_id = t.id WHERE s.id=?
    """, (sid,)).fetchone()
    fee = float(request.form.get("fee_amount") or (student["monthly_fee"] if student else 0))
    notes = request.form.get("notes", "")
    db.execute("""
        INSERT INTO invoices (student_id, month, fee_amount, notes)
        VALUES (?, ?, ?, ?)
        ON CONFLICT(student_id, month) DO UPDATE SET fee_amount=excluded.fee_amount, notes=excluded.notes
    """, (sid, month, fee, notes))
    db.commit()
    flash("Statement saved.", "success")
    return redirect(url_for("statement_view", sid=sid, month=month))


# ── Settings ──────────────────────────────────────────────────────────────────
@app.route("/settings/tiers")
def settings_tiers():
    db = get_db()
    tiers = db.execute("SELECT * FROM fee_tiers ORDER BY age_min NULLS LAST, name").fetchall()
    return render_template("settings/tiers.html", tiers=tiers)


@app.route("/settings/tiers/save", methods=["POST"])
def tier_save():
    db = get_db()
    tier_id  = request.form.get("tier_id") or None
    name     = request.form["name"].strip()
    age_min  = request.form.get("age_min") or None
    age_max  = request.form.get("age_max") or None
    fee      = float(request.form["monthly_fee"])
    if tier_id:
        db.execute(
            "UPDATE fee_tiers SET name=?, age_min=?, age_max=?, monthly_fee=? WHERE id=?",
            (name, age_min, age_max, fee, tier_id)
        )
    else:
        db.execute(
            "INSERT INTO fee_tiers (name, age_min, age_max, monthly_fee) VALUES (?,?,?,?)",
            (name, age_min, age_max, fee)
        )
    db.commit()
    flash("Tier saved.", "success")
    return redirect(url_for("settings_tiers"))


@app.route("/settings/tiers/<int:tier_id>/delete", methods=["POST"])
def tier_delete(tier_id):
    db = get_db()
    db.execute("DELETE FROM fee_tiers WHERE id=?", (tier_id,))
    db.commit()
    flash("Tier deleted.", "info")
    return redirect(url_for("settings_tiers"))


@app.route("/settings/keywords")
def settings_keywords():
    db = get_db()
    rules = db.execute("""
        SELECT k.id, k.keyword, k.student_id,
               s.first_name || ' ' || s.last_name AS student_name
        FROM keyword_rules k
        JOIN students s ON k.student_id = s.id
        ORDER BY k.keyword
    """).fetchall()
    students = db.execute(
        "SELECT id, first_name, last_name FROM students WHERE is_active=1 ORDER BY last_name"
    ).fetchall()
    return render_template("settings/keywords.html", rules=rules, students=students)


@app.route("/settings/keywords/save", methods=["POST"])
def keyword_save():
    db = get_db()
    db.execute(
        "INSERT INTO keyword_rules (keyword, student_id) VALUES (?,?)",
        (request.form["keyword"].strip().lower(), request.form["student_id"])
    )
    db.commit()
    flash("Keyword rule added.", "success")
    return redirect(url_for("settings_keywords"))


@app.route("/settings/keywords/<int:rule_id>/delete", methods=["POST"])
def keyword_delete(rule_id):
    db = get_db()
    db.execute("DELETE FROM keyword_rules WHERE id=?", (rule_id,))
    db.commit()
    flash("Keyword removed.", "info")
    return redirect(url_for("settings_keywords"))


@app.route("/settings/ip")
def settings_ip():
    db = get_db()
    allowed_ips = db.execute("SELECT * FROM allowed_ips ORDER BY added_at DESC").fetchall()
    current_ip  = request.remote_addr
    return render_template("settings/ip_list.html", allowed_ips=allowed_ips, current_ip=current_ip)


@app.route("/settings/ip/add", methods=["POST"])
def ip_add():
    db = get_db()
    ip    = request.form["ip_address"].strip()
    label = request.form.get("label", "")
    db.execute("INSERT OR IGNORE INTO allowed_ips (ip_address, label) VALUES (?,?)", (ip, label))
    db.commit()
    flash(f"IP {ip} added.", "success")
    return redirect(url_for("settings_ip"))


@app.route("/settings/ip/<int:ip_id>/delete", methods=["POST"])
def ip_delete(ip_id):
    db = get_db()
    row = db.execute("SELECT ip_address FROM allowed_ips WHERE id=?", (ip_id,)).fetchone()
    if row and row["ip_address"] == "127.0.0.1":
        flash("Cannot remove localhost — it is always allowed.", "danger")
        return redirect(url_for("settings_ip"))
    db.execute("DELETE FROM allowed_ips WHERE id=?", (ip_id,))
    db.commit()
    flash("IP removed.", "info")
    return redirect(url_for("settings_ip"))


if __name__ == "__main__":
    app.run(debug=True)
