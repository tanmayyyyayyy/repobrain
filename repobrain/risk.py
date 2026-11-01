"""Merge Risk Index: one transparent 0-100 number per change, with the reasons that built it.

This is a hand-weighted, explainable heuristic, NOT a trained model: reviewers should be able to
see exactly why a change scored what it did. Weights live in WEIGHTS below.
"""
WEIGHTS = {
    "blocking finding":            (30, 60),   # (per item, cap)
    "unwaived warning":            (6, 18),
    "AI-authored file":            (3, 15),
    "policy gate violation":       (7, 21),
    "optimization unverified":     (8, 8),
    "protected path touched":      (10, 20),
    "large change":                (5, 5),
}


def score(files, gate, proposal, blocked_active, warn_active, large):
    parts = []
    def add(name, n):
        if n:
            per, cap = WEIGHTS[name]
            parts.append({"factor": name, "count": n, "points": min(cap, per * n)})
    add("blocking finding", blocked_active)
    add("unwaived warning", warn_active)
    add("AI-authored file", sum(1 for f in files if f["ai"]))
    add("policy gate violation", len(gate))
    add("protected path touched", sum(1 for f in files for x in f["findings"] if x["rule"] == "blocked-path" and not x.get("waived")))
    tests = (proposal or {}).get("tests")
    add("optimization unverified", 1 if tests and tests.get("ok") is None else 0)
    add("large change", 1 if large else 0)
    total = min(100, sum(p["points"] for p in parts))
    level = "critical" if total >= 70 else "high" if total >= 40 else "moderate" if total >= 15 else "low"
    return {"score": total, "level": level, "factors": sorted(parts, key=lambda p: -p["points"])}
