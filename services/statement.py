"""
Builds fee statement data for a student for a given month (YYYY-MM).
"""
from database import get_db


def build(student_id: int, month: str) -> dict | None:
    db = get_db()

    student = db.execute("""
        SELECT s.*, t.name as tier_name, t.monthly_fee
        FROM students s
        LEFT JOIN fee_tiers t ON s.tier_id = t.id
        WHERE s.id = ?
    """, (student_id,)).fetchone()

    if not student:
        db.close()
        return None

    # Fee for this month (use invoice override if exists, else tier fee)
    invoice = db.execute(
        "SELECT * FROM invoices WHERE student_id = ? AND month = ?",
        (student_id, month)
    ).fetchone()

    fee_amount = invoice["fee_amount"] if invoice else (student["monthly_fee"] or 0)
    invoice_notes = invoice["notes"] if invoice else ""

    # Payments received this month
    payments = db.execute("""
        SELECT * FROM transactions
        WHERE student_id = ? AND date LIKE ? AND amount > 0
        ORDER BY date
    """, (student_id, f"{month}%")).fetchall()

    # Extra charges this month
    extras = db.execute("""
        SELECT * FROM extra_charges
        WHERE student_id = ? AND date LIKE ?
        ORDER BY date
    """, (student_id, f"{month}%")).fetchall()

    db.close()

    total_paid    = sum(p["amount"] for p in payments)
    total_extras  = sum(e["amount"] for e in extras)
    total_due     = fee_amount + total_extras
    balance       = total_due - total_paid

    return {
        "student":       dict(student),
        "month":         month,
        "fee_amount":    fee_amount,
        "extras":        [dict(e) for e in extras],
        "total_extras":  total_extras,
        "payments":      [dict(p) for p in payments],
        "total_paid":    total_paid,
        "total_due":     total_due,
        "balance":       balance,
        "invoice_notes": invoice_notes,
        "status":        _status(balance, total_paid, total_due),
    }


def _status(balance: float, total_paid: float, total_due: float) -> str:
    if total_due == 0:
        return "no_fee"
    if balance <= 0:
        return "paid"
    if total_paid > 0:
        return "partial"
    return "unpaid"


def get_all_statuses(month: str) -> list[dict]:
    """Return statement status for every active student for a given month."""
    db = get_db()
    students = db.execute("""
        SELECT s.id, s.first_name, s.last_name, t.monthly_fee
        FROM students s
        LEFT JOIN fee_tiers t ON s.tier_id = t.id
        WHERE s.is_active = 1
        ORDER BY s.last_name, s.first_name
    """).fetchall()
    db.close()

    statuses = []
    for s in students:
        data = build(s["id"], month)
        if data:
            statuses.append({
                "student_id":   s["id"],
                "name":         f"{s['first_name']} {s['last_name']}",
                "monthly_fee":  s["monthly_fee"],
                "status":       data["status"],
                "total_paid":   data["total_paid"],
                "balance":      data["balance"],
            })
    return statuses
