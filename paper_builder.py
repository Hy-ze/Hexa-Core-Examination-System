"""5.2 Fairness of randomized papers.

Every candidate gets a different paper drawn from the exam's question pool, but each paper
is built to (a) total the same marks, (b) have a similar average difficulty, and (c) have a
similar mix of question types. Difficulty is not just the label an examiner typed in: once a
question has been answered by enough real candidates, its OBSERVED difficulty (share of
candidates who got it right) is blended in, so the balancing improves with every exam.
"""
import random
from statistics import mean, pstdev

NOMINAL = {"easy": 1.0, "medium": 2.0, "hard": 3.0}
MIN_OBSERVATIONS = 5        # need this many real attempts before observed data is used
FULL_TRUST_AT = 60          # evidence weight reaches its 50% cap at 30 attempts (n / 60)
RESTARTS = 30
STEPS = 200
MARKS_TOLERANCE = 0.01
INDEX_TOLERANCE = 0.08      # on the 1..3 difficulty scale


def effective_difficulty(q: dict) -> float:
    """Blend of the examiner's label and what real candidates actually did (1 easy .. 3 hard)."""
    nominal = NOMINAL.get(q.get("difficulty"), 2.0)
    shown = q.get("times_presented") or 0
    if shown >= MIN_OBSERVATIONS and q.get("question_type") != "written":
        rate = min(1.0, (q.get("times_correct") or 0) / shown)
        observed = 1.0 + 2.0 * (1.0 - rate)
        weight = min(0.5, shown / FULL_TRUST_AT)
        return round((1 - weight) * nominal + weight * observed, 3)
    return nominal


def build_paper(pool: list, n, target_marks: float, balance: bool = True, shuffle: bool = True,
                used: set | None = None, rng=random):
    """Return (questions, difficulty_index, method). `pool` items need question_id, marks,
    difficulty, question_type, times_presented, times_correct."""
    used = used or set()
    total = len(pool)
    eff = [effective_difficulty(q) for q in pool]
    marks = [float(q["marks"]) for q in pool]

    if not n or n >= total:
        idx, method = list(range(total)), "full"
    elif not balance:
        idx, method = rng.sample(range(total), n), "random"
    else:
        method = "balanced"
        avg_d = mean(eff)
        kinds = [q["question_type"] for q in pool]
        share = {k: kinds.count(k) / total for k in set(kinds)}

        def cost(sel):
            m = sum(marks[i] for i in sel)
            d = sum(eff[i] for i in sel) / n
            c = 5 * abs(m - target_marks) + 25 * abs(d - avg_d)
            for k, s in share.items():
                c += abs(sum(1 for i in sel if kinds[i] == k) - n * s)
            if frozenset(pool[i]["question_id"] for i in sel) in used:
                c += 0.75          # prefer a paper nobody has had yet (keeps variation)
            return c, m, d

        good, best, best_cost = [], None, 1e9
        for _ in range(RESTARTS):
            sel = rng.sample(range(total), n)
            chosen = set(sel)
            out = [i for i in range(total) if i not in chosen]
            cur = cost(sel)[0]
            for _ in range(STEPS):
                a, b = rng.randrange(n), rng.randrange(len(out))
                sel[a], out[b] = out[b], sel[a]
                c = cost(sel)[0]
                if c <= cur:
                    cur = c            # equal-cost swaps are accepted on purpose: more variety
                else:
                    sel[a], out[b] = out[b], sel[a]
            c, m, d = cost(sel)
            key = frozenset(pool[i]["question_id"] for i in sel)
            if abs(m - target_marks) <= MARKS_TOLERANCE and abs(d - avg_d) <= INDEX_TOLERANCE and key not in used:
                good.append(list(sel))
            if c < best_cost:
                best, best_cost = list(sel), c
        idx = rng.choice(good) if good else best

    if shuffle:
        rng.shuffle(idx)
    else:
        idx.sort()
    index = round(mean(eff[i] for i in idx), 3) if idx else 0.0
    return [pool[i] for i in idx], index, method


def simulate(pool: list, n, target_marks: float, count: int, balance: bool, rng=None):
    """Build `count` papers (without saving anything) so examiners can compare methods."""
    rng = rng or random.Random()
    used, papers = set(), []
    for _ in range(count):
        qs, index, _m = build_paper(pool, n, target_marks, balance=balance, shuffle=False, used=used, rng=rng)
        used.add(frozenset(q["question_id"] for q in qs))
        papers.append({"marks": round(sum(float(q["marks"]) for q in qs), 2), "index": index})
    idxs, mks = [p["index"] for p in papers], [p["marks"] for p in papers]
    return {
        "papers": papers,
        "distinct": len(used),
        "index": {"min": min(idxs), "max": max(idxs), "mean": round(mean(idxs), 3), "std": round(pstdev(idxs), 3)},
        "marks": {"min": min(mks), "max": max(mks), "mean": round(mean(mks), 2), "std": round(pstdev(mks), 2)},
    }
