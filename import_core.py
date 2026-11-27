"""4.4 Bulk import: reading CSV / JSON files and turning them into clean row dictionaries.

This module only parses and normalises. It knows nothing about the database or the web layer,
so it can be tested on its own. The routers decide what is valid for the system (they reuse the
same validation as the forms, so a file can never create something the forms would refuse).

Every function returns (rows, errors):
  rows   - list of (row_number, dict) ready for validation
  errors - list of {"row": n, "message": "..."} for rows that could not even be read
Row numbers match what the user sees: for CSV the line in the file (header = 1, first record = 2),
for JSON the position in the list (first item = 1).
"""
import csv
import io
import json
import re

MAX_CONTENT_CHARS = 1_500_000

TYPE_ALIASES = {
    "mcq": "mcq", "single": "mcq", "single answer": "mcq", "single_answer": "mcq", "single-answer": "mcq", "one": "mcq",
    "multi": "multi", "multiple": "multi", "multiple select": "multi", "multiple_select": "multi",
    "multiple-select": "multi", "multi select": "multi", "multiselect": "multi",
    "written": "written", "essay": "written", "short": "written", "short answer": "written", "text": "written",
}
SCHEME_ALIASES = {
    "partial": "partial", "partial credit": "partial", "proportional": "partial",
    "all_or_nothing": "all_or_nothing", "all or nothing": "all_or_nothing", "all-or-nothing": "all_or_nothing", "strict": "all_or_nothing",
}
LETTERS = "ABCDEFGH"

# header aliases -> canonical column names
QUESTION_HEADERS = {
    "type": "type", "question type": "type", "question_type": "type",
    "difficulty": "difficulty", "level": "difficulty",
    "category": "category", "topic": "category",
    "question": "body", "body": "body", "question text": "body", "text": "body", "statement": "body",
    "marks": "marks", "mark": "marks", "points": "marks",
    "negative_marks": "negative_marks", "negative marks": "negative_marks", "negative": "negative_marks", "penalty": "negative_marks",
    "multi_scheme": "multi_scheme", "scheme": "multi_scheme", "marking": "multi_scheme", "marking scheme": "multi_scheme",
    "correct": "correct", "answer": "correct", "correct answer": "correct", "correct_answer": "correct", "answers": "correct",
    "model_answer": "model_answer", "model answer": "model_answer", "sample answer": "model_answer",
    "explanation": "explanation", "explain": "explanation",
}
CANDIDATE_HEADERS = {
    "full_name": "full_name", "full name": "full_name", "name": "full_name", "candidate": "full_name", "student": "full_name",
    "email": "email", "e-mail": "email", "email address": "email", "mail": "email",
    "roll_no": "roll_no", "roll no": "roll_no", "roll no.": "roll_no", "roll": "roll_no", "roll number": "roll_no",
    "rollno": "roll_no", "reg no": "roll_no", "registration no": "roll_no", "id": "roll_no",
    "password": "password", "temporary password": "password",
}


# ------------------------------------------------------------------ low-level readers
def _norm_header(h) -> str:
    return re.sub(r"\s+", " ", str(h or "").replace("\ufeff", "").strip().lower())


def _option_column(h: str):
    """'option a', 'option_1', 'choice 3', 'a' ... -> option index (0-based) or None."""
    m = re.fullmatch(r"(?:option|choice|opt)[ _\-]*([a-h]|[1-8])", h)
    if m:
        k = m.group(1)
        return LETTERS.index(k.upper()) if k.isalpha() else int(k) - 1
    return None


def read_csv(content: str):
    """Return (header_names, [(row_number, {canonical_header_or_raw: value})]) or raise ValueError."""
    content = (content or "").replace("\ufeff", "")
    if not content.strip():
        raise ValueError("The file is empty.")
    sample = content[:4000]
    try:
        dialect = csv.Sniffer().sniff(sample, delimiters=",;\t|")
    except csv.Error:
        dialect = csv.excel
    reader = csv.reader(io.StringIO(content), dialect)
    try:
        header = next(reader)
    except StopIteration:
        raise ValueError("The file is empty.")
    names = [_norm_header(h) for h in header]
    if not any(names):
        raise ValueError("The first row must contain column names.")
    out = []
    for row in reader:
        if not any((c or "").strip() for c in row):
            continue                                  # blank line
        rec = {}
        for i, cell in enumerate(row):
            if i < len(names) and names[i]:
                rec[names[i]] = (cell or "").strip()
        out.append((reader.line_num, rec))
    return names, out


def read_json(content: str):
    """Return [(item_number, dict)] from a JSON list (or {"questions"/"candidates"/"rows": [...]})."""
    try:
        data = json.loads((content or "").replace("\ufeff", ""))
    except ValueError as e:
        raise ValueError(f"This is not valid JSON ({e.msg} at line {getattr(e, 'lineno', '?')}).")
    if isinstance(data, dict):
        for key in ("questions", "candidates", "students", "rows", "items", "data"):
            if isinstance(data.get(key), list):
                data = data[key]
                break
        else:
            raise ValueError("Expected a JSON list of records, or an object holding one.")
    if not isinstance(data, list):
        raise ValueError("Expected a JSON list of records.")
    out = []
    for i, item in enumerate(data, start=1):
        out.append((i, item))
    return out


def _check_size(content: str):
    if not isinstance(content, str) or not content.strip():
        raise ValueError("The file is empty.")
    if len(content) > MAX_CONTENT_CHARS:
        raise ValueError("The file is too large. Split it into smaller files (up to about 1.5 MB each).")


def _canon(rec: dict, table: dict) -> dict:
    out = {}
    for k, v in rec.items():
        key = table.get(_norm_header(k))
        if key:
            out[key] = v
    return out


def _s(v) -> str:
    if v is None:
        return ""
    if isinstance(v, bool):
        return "true" if v else "false"
    return str(v).strip()


def _num(v, default, label):
    s = _s(v)
    if s == "":
        return default
    try:
        return float(s.replace(",", "."))
    except ValueError:
        raise ValueError(f"{label} must be a number (found '{s}').")


# ------------------------------------------------------------------ questions
def _parse_correct(raw, option_count: int):
    """'B', 'A;C', '2', '1,3', ['A','C'], [1,3] -> sorted 0-based indices. Raises ValueError."""
    if raw is None or raw == "" or raw == []:
        return []
    items = raw if isinstance(raw, list) else re.split(r"[;,|/\s]+", str(raw).strip())
    idx = []
    for it in items:
        t = _s(it)
        if not t:
            continue
        if re.fullmatch(r"[A-Ha-h]", t):
            i = LETTERS.index(t.upper())
        elif re.fullmatch(r"\d+", t):
            i = int(t) - 1                               # numbers are 1-based, like the columns
        else:
            raise ValueError(f"'{t}' is not a valid correct-answer marker. Use letters (A, B...) or option numbers (1, 2...).")
        if not (0 <= i < option_count):
            raise ValueError(f"The correct answer '{t}' points to an option that does not exist.")
        if i not in idx:
            idx.append(i)
    return sorted(idx)


def _question_from_flat(rec: dict, options_flat: list, row_no: int) -> dict:
    """Turn a canonical record + ordered option texts into the dict the QuestionIn model expects."""
    qtype = TYPE_ALIASES.get(_s(rec.get("type")).lower().replace("_", " ").strip() or "mcq") \
        or TYPE_ALIASES.get(_s(rec.get("type")).lower())
    if not qtype:
        raise ValueError(f"Unknown question type '{_s(rec.get('type'))}'. Use mcq, multi or written.")
    difficulty = _s(rec.get("difficulty")).lower() or "medium"
    if difficulty not in ("easy", "medium", "hard"):
        raise ValueError(f"Unknown difficulty '{difficulty}'. Use easy, medium or hard.")
    scheme_raw = _s(rec.get("multi_scheme")).lower()
    scheme = SCHEME_ALIASES.get(scheme_raw) if scheme_raw else "partial"
    if scheme is None:
        raise ValueError(f"Unknown multiple-select scheme '{scheme_raw}'. Use partial or all_or_nothing.")
    body = _s(rec.get("body"))
    if not body:
        raise ValueError("The question text is missing.")
    marks = _num(rec.get("marks"), 1.0, "Marks")
    negative = _num(rec.get("negative_marks"), 0.0, "Negative marks")
    out = {"question_type": qtype, "difficulty": difficulty, "body": body, "marks": marks,
           "negative_marks": negative, "multi_scheme": scheme,
           "model_answer": _s(rec.get("model_answer")) or None, "explanation": _s(rec.get("explanation")) or None,
           "category": _s(rec.get("category")) or None, "options": []}
    if qtype == "written":
        return out
    texts = [t for t in options_flat]
    while texts and not _s(texts[-1]):
        texts.pop()                                       # trailing empty option columns
    if any(not _s(t) for t in texts):
        raise ValueError("There is an empty option between filled ones. Fill the options in order, without gaps.")
    if len(texts) < 2:
        raise ValueError("Add at least two answer options.")
    correct = _parse_correct(rec.get("correct"), len(texts))
    if not correct:
        raise ValueError("Mark the correct option(s) in the 'correct' column (for example B, or A;C).")
    out["options"] = [{"text": _s(t), "is_correct": i in correct} for i, t in enumerate(texts)]
    return out


def parse_questions(fmt: str, content: str):
    """Return (rows, errors, template_hint). Each row is (row_number, question_dict)."""
    _check_size(content)
    rows, errors = [], []
    if fmt == "csv":
        names, records = read_csv(content)
        if not any(QUESTION_HEADERS.get(n) == "body" for n in names):
            raise ValueError("The first row must name the columns. A 'question' column is required (see the template).")
        opt_cols = sorted({i for n in names if (i := _option_column(n)) is not None})
        for line, rec in records:
            try:
                canon = _canon(rec, QUESTION_HEADERS)
                flat = [rec.get(next((n for n in names if _option_column(n) == i), ""), "") for i in range(max(opt_cols) + 1)] if opt_cols else []
                rows.append((line, _question_from_flat(canon, flat, line)))
            except ValueError as e:
                errors.append({"row": line, "message": str(e)})
    elif fmt == "json":
        for n, item in read_json(content):
            try:
                if not isinstance(item, dict):
                    raise ValueError("Each item must be an object with the question's fields.")
                canon = _canon(item, QUESTION_HEADERS)
                raw_opts = item.get("options", item.get("choices"))
                if isinstance(raw_opts, list) and raw_opts and all(isinstance(o, dict) for o in raw_opts):
                    flat = [_s(o.get("text", o.get("option", o.get("option_text")))) for o in raw_opts]
                    marked = [i for i, o in enumerate(raw_opts) if o.get("is_correct") in (True, 1, "1", "true", "True", "yes")]
                    canon["correct"] = [i + 1 for i in marked] if marked else canon.get("correct")
                elif isinstance(raw_opts, list):
                    flat = [_s(o) for o in raw_opts]
                else:
                    flat = []
                    for i in range(8):                    # flat form: option_a ... option_h
                        for key in (f"option_{LETTERS[i].lower()}", f"option {LETTERS[i].lower()}", f"option{i + 1}", f"option_{i + 1}"):
                            if key in item:
                                flat.append(_s(item[key]))
                                break
                        else:
                            break
                rows.append((n, _question_from_flat(canon, flat, n)))
            except ValueError as e:
                errors.append({"row": n, "message": str(e)})
    else:
        raise ValueError("Choose a CSV or JSON file.")
    return rows, errors


# ------------------------------------------------------------------ candidates / enrollments
def parse_people(fmt: str, content: str, need: tuple):
    """Rows with full_name/email/roll_no/password (any subset). `need` lists columns that must exist
    in the header (for CSV) so a wrong file fails early with a clear message."""
    _check_size(content)
    rows, errors = [], []
    if fmt == "csv":
        names, records = read_csv(content)
        have = {CANDIDATE_HEADERS.get(n) for n in names}
        if not any(k in have for k in need):
            raise ValueError("The first row must name the columns. Expected: " + ", ".join(need) + " (see the template).")
        for line, rec in records:
            rows.append((line, _canon(rec, CANDIDATE_HEADERS)))
    elif fmt == "json":
        for n, item in read_json(content):
            if not isinstance(item, dict):
                errors.append({"row": n, "message": "Each item must be an object."})
                continue
            rows.append((n, {k: _s(v) for k, v in _canon(item, CANDIDATE_HEADERS).items()}))
    else:
        raise ValueError("Choose a CSV or JSON file.")
    return rows, errors


def norm_text(s: str) -> str:
    """Lowercase, collapse whitespace: used to detect duplicate questions."""
    return re.sub(r"\s+", " ", (s or "").strip().lower())