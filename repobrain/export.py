"""Exports: SARIF (GitHub code scanning), Markdown (PR comment / job summary), CSV (auditors)."""
import csv, io, json

LEVEL = {"block": "error", "warn": "warning"}
RULE_DOC = {
    "blocked-path": "A change touches a path the policy protects from AI agents.",
    "secret": "A credential or key appears to be committed.",
    "high-entropy-string": "A high-entropy string that looks like a secret.",
    "prompt-injection": "Text that tries to instruct AI agents to bypass rules or leak data.",
    "hidden-unicode": "Invisible or bidirectional Unicode characters (hidden instructions, Trojan Source).",
    "risky-command": "A command or setting with supply-chain or privilege risk.",
    "dependency-risk": "A suspicious dependency (typosquat, URL install, custom index).",
    "large-change": "The change is larger than the policy limit.",
    "complexity-gate": "A function exceeds the complexity policy.",
}


def sarif(findings, gate, version="1.0.0"):
    results = []
    for f in findings:
        results.append({"ruleId": f["rule"], "level": LEVEL.get(f["severity"], "note"), "message": {"text": f["msg"]},
                        "locations": [{"physicalLocation": {"artifactLocation": {"uri": f["file"]},
                                                           "region": {"startLine": max(1, f.get("line") or 1)}}}]})
    for g in gate:
        results.append({"ruleId": "complexity-gate", "level": "error",
                        "message": {"text": f"{g['name']}(): " + "; ".join(g.get("why", []))},
                        "locations": [{"physicalLocation": {"artifactLocation": {"uri": g["file"]}, "region": {"startLine": g["line"]}}}]})
    used = sorted({r["ruleId"] for r in results})
    rules = [{"id": r, "shortDescription": {"text": RULE_DOC.get(r, r)}} for r in used]
    return {"version": "2.1.0", "$schema": "https://json.schemastore.org/sarif-2.1.0.json",
            "runs": [{"tool": {"driver": {"name": "RepoBrain", "version": version, "rules": rules,
                                          "informationUri": "https://github.com/"}}, "results": results}]}


def markdown(st):
    icon = {"blocked": "🛑 **Blocked**", "changes": "🟠 **Changes required**", "ready": "🟢 **Ready for human review**"}[st["verdict"]]
    r = st["risk"]
    lines = [f"## RepoBrain: {icon}", "",
             f"Merge Risk Index **{r['score']}/100** ({r['level']}) · {len(st['files'])} files · "
             f"{sum(1 for f in st['files'] if f['ai'])} AI-authored · audit chain "
             f"{'✅ verified' if st['chain']['ok'] else '❌ TAMPERED'}", ""]
    blocks = [(f["path"], x) for f in st["files"] for x in f["findings"] if x["severity"] == "block" and not x.get("waived")]
    warns = [(f["path"], x) for f in st["files"] for x in f["findings"] if x["severity"] == "warn" and not x.get("waived")]
    if blocks or warns:
        lines += ["| Severity | Rule | Location | Detail |", "|---|---|---|---|"]
        for path, x in blocks + warns:
            lines.append(f"| {'🛑 block' if x['severity'] == 'block' else '⚠️ warn'} | `{x['rule']}` | `{path}:{x.get('line') or ''}` | {x['msg']} |")
        lines.append("")
    if st["gate"]:
        lines += ["**Complexity gate failures**", ""] + [f"- `{g['file']}` `{g['name']}()`: {', '.join(g['why'])}" for g in st["gate"]] + [""]
    p = st["proposal"]
    if p["changed"]:
        t = (p.get("tests") or {})
        fz = p.get("fuzz") or {}
        lines += [f"**Optimizer** proposes a simpler version of {p['changed']} file(s): "
                  f"tests {'passed' if t.get('ok') else ('unverified' if t.get('ok') is None else 'FAILED')}"
                  + (f", {fz['inputs']} fuzz inputs / {fz['diverged']} divergences" if fz else "") + ". Nothing is pushed; a human approves.", ""]
    lines.append("<sub>Policy: `repobrain.yml` · Nothing merges without human approval.</sub>")
    return "\n".join(lines)


def audit_csv(rows):
    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow(["seq", "timestamp", "event", "decision", "actor", "detail", "prev_hash", "hash"])
    for r in rows:
        w.writerow([r.get("seq", ""), r["ts"], r["event"], r["decision"], r["actor"], json.dumps(r["detail"]), r["prev"], r["hash"]])
    return buf.getvalue()
