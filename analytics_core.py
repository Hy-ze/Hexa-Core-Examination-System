"""Pure question analytics computed from finished, non-sandbox attempts."""
import json
from statistics import mean

MIN_N = 5
MIN_DISCRIMINATION_N = 8
SKIP_FLAG = 0.25
HARD_FLAG = 0.25
EASY_FLAG = 0.95
LEVEL_RANK = {"easy": 1, "medium": 2, "hard": 3}
NOTICE = ("These figures come from the attempts submitted so far and are indicators, not verdicts. "
          "With few attempts a single answer moves a percentage a lot, so use them to decide where to look.")


def _ids(raw) -> list:
    try:
        return [int(x) for x in json.loads(raw or "[]")]
    except (ValueError, TypeError):
        return []


def observed_level(rate):
    if rate is None:
        return None
    return "easy" if rate >= 0.75 else "medium" if rate >= 0.40 else "hard"


def _pct(n, d):
    return round(n / d, 3) if d else None


def compute(rows: list, questions: list, options: list, order: list | None = None) -> dict:
    """Compute per-question statistics. Inputs are anonymised attempt-question rows."""
    by_q = {}
    for row in rows:
        by_q.setdefault(row["question_id"], []).append(row)
    opts_by_q = {}
    for option in sorted(options, key=lambda o: (o["position"], o["id"])):
        opts_by_q.setdefault(option["question_id"], []).append(option)
    attempts_counted = len({r.get("attempt_id") for r in rows})
    out = [_one(q, by_q.get(q["id"], []), opts_by_q.get(q["id"], [])) for q in questions]
    if order:
        pos = {qid: i for i, qid in enumerate(order)}
        out.sort(key=lambda x: pos.get(x["question_id"], 10 ** 6))

    seen = [x for x in out if x["shown"] >= MIN_N]
    rated = [x for x in seen if x["correct_rate"] is not None]
    brief = lambda x, key: {"question_id": x["question_id"], "label": x["body"][:80], key: x[key]}
    summary = {
        "questions": len(out), "with_data": len(seen),
        "avg_correct_rate": round(mean(x["correct_rate"] for x in rated), 3) if rated else None,
        "most_skipped": [brief(x, "skip_rate") for x in sorted(seen, key=lambda x: -x["skip_rate"])[:3] if x["skip_rate"] > 0],
        "hardest": [brief(x, "correct_rate") for x in sorted(rated, key=lambda x: x["correct_rate"])[:3]],
        "easiest": [brief(x, "correct_rate") for x in sorted(rated, key=lambda x: -x["correct_rate"])[:3]],
        "needs_review": sum(1 for x in out if any(f["severity"] == "review" for f in x["flags"])),
    }
    return {"attempts_counted": attempts_counted, "summary": summary, "questions": out, "notice": NOTICE}


def _one(q: dict, recs: list, opts: list) -> dict:
    shown = len(recs)
    objective = q["question_type"] != "written"
    answered = sum(1 for r in recs if r["is_answered"])
    graded = [r for r in recs if r["is_graded"] and float(r["marks"]) > 0]
    full = lambda r: float(r["marks_awarded"] or 0) >= float(r["marks"]) - 1e-9
    correct = sum(1 for r in graded if objective and full(r))
    partial = sum(1 for r in graded if objective and not full(r) and float(r["marks_awarded"] or 0) > 0)
    wrong = sum(1 for r in graded if objective and r["is_answered"] and float(r["marks_awarded"] or 0) <= 0)
    avg_pct = round(mean(max(0.0, float(r["marks_awarded"] or 0)) / float(r["marks"]) for r in graded), 3) if graded else None
    correct_rate = _pct(correct, shown) if objective and shown else None

    picks = {}
    for row in recs:
        for oid in _ids(row["selected_options"]):
            picks[oid] = picks.get(oid, 0) + 1
    option_stats = [
        {"id": option["id"], "text": option["option_text"], "is_correct": bool(option["is_correct"]),
         "picks": picks.get(option["id"], 0), "rate": _pct(picks.get(option["id"], 0), shown)}
        for option in opts
    ]
    wrong_opts = sorted((o for o in option_stats if not o["is_correct"] and o["picks"] > 0),
                        key=lambda o: -o["picks"])
    top_wrong = wrong_opts[0] if wrong_opts and wrong_opts[0]["picks"] >= 2 else None

    level_source = correct_rate if objective else (avg_pct if len(graded) >= MIN_N else None)
    sample_ok = shown >= MIN_N if objective else len(graded) >= MIN_N
    level = observed_level(level_source) if sample_ok else None
    disc = _discrimination(recs) if objective and shown >= MIN_DISCRIMINATION_N else None
    skip_rate = _pct(shown - answered, shown) or 0.0
    flags = _flags(q, shown, skip_rate, correct_rate, option_stats, top_wrong, disc, level, objective)
    return {
        "question_id": q["id"], "body": q["body"], "type": q["question_type"],
        "label": q["difficulty"], "category": q.get("category"),
        "shown": shown, "answered": answered, "skipped": shown - answered,
        "skip_rate": skip_rate, "correct": correct, "partial": partial, "wrong": wrong,
        "correct_rate": correct_rate, "avg_score_pct": avg_pct, "graded": len(graded),
        "ungraded": shown - len(graded), "observed_level": level, "discrimination": disc,
        "options": option_stats,
        "top_wrong": ({"text": top_wrong["text"], "picks": top_wrong["picks"], "rate": top_wrong["rate"]}
                      if top_wrong else None),
        "flags": flags,
    }


def _discrimination(recs: list):
    """Correct-rate of the best-scoring 27% minus that of the lowest-scoring 27%."""
    pool = [
        (float(r["total_score"]) / float(r["max_score"]),
         1 if float(r["marks_awarded"] or 0) >= float(r["marks"]) - 1e-9 else 0)
        for r in recs if r["is_graded"] and r.get("max_score") and float(r["max_score"]) > 0
    ]
    if len(pool) < MIN_DISCRIMINATION_N:
        return None
    pool.sort(key=lambda x: x[0])
    k = max(2, round(0.27 * len(pool)))
    low, high = pool[:k], pool[-k:]
    return round(sum(c for _, c in high) / k - sum(c for _, c in low) / k, 2)


def _flags(q, shown, skip_rate, correct_rate, option_stats, top_wrong, disc, level, objective) -> list:
    flags = []
    pct = lambda x: f"{round(x * 100)}%"
    if shown >= MIN_N and skip_rate >= SKIP_FLAG:
        flags.append({"code": "often_skipped", "severity": "note",
                      "text": f"Skipped by {pct(skip_rate)} of candidates. It may be unclear, too long, or sit where time ran short."})
    if objective and shown >= MIN_N and correct_rate is not None:
        if correct_rate <= HARD_FLAG:
            flags.append({"code": "very_hard", "severity": "note",
                          "text": f"Only {pct(correct_rate)} answered it fully correctly."})
        elif correct_rate >= EASY_FLAG:
            flags.append({"code": "very_easy", "severity": "note",
                          "text": "Almost everyone answered it correctly, so it does little to tell candidates apart."})
    if q["question_type"] == "mcq" and shown >= 8 and top_wrong:
        right = max((o["picks"] for o in option_stats if o["is_correct"]), default=0)
        if top_wrong["picks"] > right:
            flags.append({"code": "check_key", "severity": "review",
                          "text": f"More candidates chose “{top_wrong['text'][:60]}” ({pct(top_wrong['rate'])}) than the keyed answer. Check the answer key and the wording for ambiguity."})
    if top_wrong and shown >= MIN_N and top_wrong["rate"] is not None and top_wrong["rate"] >= 0.30 and not any(f["code"] == "check_key" for f in flags):
        flags.append({"code": "attractive_wrong", "severity": "note",
                      "text": f"A wrong option, “{top_wrong['text'][:60]}”, attracted {pct(top_wrong['rate'])} of candidates."})
    if disc is not None:
        if disc < 0:
            flags.append({"code": "inverted", "severity": "review",
                          "text": f"Candidates who scored well overall did worse on this question than those who scored badly (difference {disc:+.2f}). Check the key and the wording."})
        elif disc < 0.1:
            flags.append({"code": "low_discrimination", "severity": "note",
                          "text": f"It barely separates strong from weak candidates (difference {disc:+.2f})."})
    if level:
        gap = LEVEL_RANK[level] - LEVEL_RANK.get(q["difficulty"], 2)
        if abs(gap) >= 2 or (abs(gap) == 1 and shown >= 10):
            flags.append({"code": "level_mismatch", "severity": "note",
                          "text": f"Labelled {q['difficulty']}, but candidates found it {'harder' if gap > 0 else 'easier'} ({level} in practice)."})
    return flags
