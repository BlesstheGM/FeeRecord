"""
Matches raw transactions to students.
Priority:
  1. Keyword rules (exact substring match) → confidence 100
  2. Student name tokens found in description → confidence 60-90
  3. Amount matches a fee tier → small bonus signal only
Returns each transaction with: student_id, student_name, confidence, matched_how
"""
import re
from database import get_db


def match_transactions(transactions: list[dict]) -> list[dict]:
    db = get_db()
    students = db.execute("""
        SELECT s.id, s.first_name, s.last_name, t.monthly_fee
        FROM students s
        LEFT JOIN fee_tiers t ON s.tier_id = t.id
        WHERE s.is_active = 1
    """).fetchall()

    rules = db.execute(
        "SELECT keyword, student_id FROM keyword_rules"
    ).fetchall()
    db.close()

    keyword_map = {r["keyword"].lower(): r["student_id"] for r in rules}
    student_map = {s["id"]: dict(s) for s in students}

    results = []
    for tx in transactions:
        desc = tx["description"].lower()
        match_id = None
        confidence = 0
        matched_how = None

        # 1. Keyword rules — highest priority
        for kw, sid in keyword_map.items():
            if kw in desc:
                match_id = sid
                confidence = 100
                matched_how = "keyword"
                break

        # 2. Name token matching
        if not match_id:
            best_score = 0
            best_id = None
            for s in students:
                tokens = _name_tokens(s["first_name"], s["last_name"])
                score = _score_tokens(tokens, desc)
                if score > best_score:
                    best_score = score
                    best_id = s["id"]
            if best_score >= 60:
                match_id = best_id
                confidence = best_score
                matched_how = "name"

        # 3. Amount bonus (supporting signal — never sole match)
        if match_id and matched_how == "name":
            s = student_map.get(match_id, {})
            fee = s.get("monthly_fee")
            if fee and abs(tx["amount"] - fee) < 5:
                confidence = min(confidence + 10, 99)

        student_name = ""
        if match_id and match_id in student_map:
            s = student_map[match_id]
            student_name = f"{s['first_name']} {s['last_name']}"

        results.append({
            **tx,
            "student_id":   match_id,
            "student_name": student_name,
            "confidence":   confidence,
            "matched_how":  matched_how,
        })

    return results


def _name_tokens(first: str, last: str) -> list[str]:
    tokens = []
    for part in (first, last):
        for token in re.split(r"[\s\-]+", part):
            t = token.strip().lower()
            if len(t) >= 3:
                tokens.append(t)
    return tokens


def _score_tokens(tokens: list[str], desc: str) -> int:
    if not tokens:
        return 0
    matched = sum(1 for t in tokens if t in desc)
    ratio = matched / len(tokens)
    if ratio == 1.0:
        return 90
    if ratio >= 0.5:
        return 70
    if matched >= 1 and len(tokens) == 1:
        return 65
    return 0
