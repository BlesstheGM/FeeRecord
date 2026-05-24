"""
Extracts transactions from SA bank statement PDFs.
Handles FNB, Standard Bank, ABSA, Nedbank, Capitec layouts.
Returns a list of dicts: {date, description, amount, reference}
Positive amount = money received (credit). Negative = debit (ignored).
"""
import re
import pdfplumber
from datetime import datetime

# Date patterns common in SA bank statements
_DATE_PATTERNS = [
    r"\d{2}\s+\w{3}\s+\d{4}",   # 15 Jan 2024
    r"\d{2}/\d{2}/\d{4}",        # 15/01/2024
    r"\d{4}-\d{2}-\d{2}",        # 2024-01-15
    r"\d{2}-\d{2}-\d{4}",        # 15-01-2024
]
_DATE_RE = re.compile("|".join(_DATE_PATTERNS))

# Amount pattern: optional R, digits, comma or period separator
_AMOUNT_RE = re.compile(r"R?\s?(\d{1,3}(?:[,\s]\d{3})*(?:[.,]\d{2}))")


def parse(filepath: str) -> list[dict]:
    transactions = []

    with pdfplumber.open(filepath) as pdf:
        for page in pdf.pages:
            # Try table extraction first (most reliable for structured statements)
            tables = page.extract_tables()
            if tables:
                for table in tables:
                    for row in table:
                        tx = _parse_row(row)
                        if tx:
                            transactions.append(tx)
            else:
                # Fall back to raw text line parsing
                text = page.extract_text() or ""
                for line in text.splitlines():
                    tx = _parse_line(line)
                    if tx:
                        transactions.append(tx)

    # Deduplicate by (date, description, amount)
    seen = set()
    unique = []
    for tx in transactions:
        key = (tx["date"], tx["description"][:30], tx["amount"])
        if key not in seen:
            seen.add(key)
            unique.append(tx)

    return unique


def _parse_row(row: list) -> dict | None:
    if not row:
        return None
    cells = [str(c).strip() if c else "" for c in row]
    text = " ".join(cells)

    date_match = _DATE_RE.search(text)
    if not date_match:
        return None

    amounts = _AMOUNT_RE.findall(text)
    if not amounts:
        return None

    # Take the last numeric value as the credit amount
    amount = _clean_amount(amounts[-1])
    if amount <= 0:
        return None

    description = _extract_description(cells, date_match.group())

    return {
        "date":        _normalise_date(date_match.group()),
        "description": description,
        "amount":      amount,
        "reference":   _extract_reference(text),
    }


def _parse_line(line: str) -> dict | None:
    date_match = _DATE_RE.search(line)
    if not date_match:
        return None

    amounts = _AMOUNT_RE.findall(line)
    if not amounts:
        return None

    amount = _clean_amount(amounts[-1])
    if amount <= 0:
        return None

    # Description is the text between date and first amount
    desc_start = date_match.end()
    first_amount_pos = line.find(amounts[0], desc_start)
    description = line[desc_start:first_amount_pos].strip(" |,")
    if not description:
        description = line.strip()

    return {
        "date":        _normalise_date(date_match.group()),
        "description": description[:200],
        "amount":      amount,
        "reference":   _extract_reference(line),
    }


def _clean_amount(raw: str) -> float:
    cleaned = raw.replace("R", "").replace(" ", "").replace(",", "")
    try:
        return float(cleaned)
    except ValueError:
        return 0.0


def _normalise_date(raw: str) -> str:
    formats = ["%d %b %Y", "%d/%m/%Y", "%Y-%m-%d", "%d-%m-%Y"]
    for fmt in formats:
        try:
            return datetime.strptime(raw.strip(), fmt).strftime("%Y-%m-%d")
        except ValueError:
            continue
    return raw.strip()


def _extract_description(cells: list[str], date_str: str) -> str:
    for cell in cells:
        if cell and date_str not in cell and not _AMOUNT_RE.match(cell):
            if len(cell) > 3:
                return cell[:200]
    return " ".join(cells)[:200]


def _extract_reference(text: str) -> str:
    ref_match = re.search(r"(?:ref|reference|ref\s*no)[:\s#]*([A-Z0-9]{6,20})", text, re.I)
    return ref_match.group(1) if ref_match else ""
