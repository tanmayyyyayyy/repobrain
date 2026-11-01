"""RepoBrain command line. Same engine as the console and the GitHub Action."""
import argparse, json, pathlib, subprocess, sys
from . import audit, explainer, export, hooks, mlguard, optimizer, policy, report, server, shield


def _root(a):
    return pathlib.Path(getattr(a, "repo", None) or ".").resolve()


def _pol(a):
    return policy.load(_root(a) / "repobrain.yml")


def cmd_serve(a):
    server.serve(a.repo, a.base, a.port, open_browser=not a.no_browser)


def cmd_demo(a):
    """Run the whole story in the terminal (no browser needed)."""
    server.seed_demo()
    root, base = server.DEMO, "main"
    home = server.home_for(root)
    print("== 1. Shield + gate on an AI-authored PR ==")
    st = server.state(root, base)
    for f in st["files"]:
        for x in f["findings"]:
            print(f"  {x['severity'].upper():5} {x['rule']:18} {f['path']}:{x.get('line') or ''}  {x['msg']}")
    print(f"  verdict: {st['verdict'].upper()}   merge risk: {st['risk']['score']}/100 ({st['risk']['level']})")
    print("== 2. Optimizer (tests + differential fuzz) ==")
    p = st["proposal"]
    print(f"  {p['status']}  tests={p['tests'] and p['tests']['ok']} runner={p['tests'] and p['tests']['runner']}  fuzz={p['fuzz']}")
    if a.approve:
        print("== 3. Human approval applies the verified simplification ==")
        print(" ", server.approve(root, base, "demo-reviewer"))
        print("  gate violations now:", len(server.state(root, base)["gate"]))
    print("== Audit chain ==", audit.verify_detail(home))


def cmd_shield(a):
    root, pol = _root(a), _pol(a)
    files = shield.changed_files(a.base, root) if a.base else a.files
    added = {f: shield.added_lines(root, a.base, f) for f in files} if a.base else None
    finds = shield.check(root, files, pol, a.actor, added=added)
    audit.log(server.home_for(root), "shield", "block" if any(f["severity"] == "block" for f in finds) else "pass", a.actor, {"findings": len(finds)})
    if a.sarif:
        pathlib.Path(a.sarif).write_text(json.dumps(export.sarif(finds, []), indent=1))
    for f in finds:
        print(f"{f['severity'].upper():5} {f['rule']:18} {f['file']}:{f.get('line') or ''}  {f['msg']}")
    sys.exit(1 if any(f["severity"] == "block" for f in finds) else 0)


def cmd_gate(a):
    root, pol = _root(a), _pol(a)
    bad = optimizer.gate(root, pol, base=a.base)
    for b in bad:
        print(f"GATE  {b['file']}::{b['name']}()  {', '.join(b['why'])}")
    sys.exit(1 if bad else 0)


def cmd_optimize(a):
    root, pol = _root(a), _pol(a)
    r = optimizer.run(root, pol, server.home_for(root), base=a.base, apply=a.apply, ai=a.ai)
    for f in r["files"]:
        print(f"{f['path']}: complexity {f['before']['total_complexity']}->{f['after']['total_complexity']}  "
              f"cognitive {f['before']['total_cognitive']}->{f['after']['total_cognitive']}  nesting {f['before']['max_depth']}->{f['after']['max_depth']}  {f['changes']}")
    print(r["status"], "| tests:", r["tests"] and r["tests"]["ok"], "| fuzz:", r["fuzz"])


def cmd_explain(a):
    text = sys.stdin.read() if a.log == "-" else pathlib.Path(a.log).read_text()
    print(json.dumps(explainer.explain(text, a.ai), indent=2))


def cmd_audit(a):
    home = server.home_for(_root(a))
    d = audit.verify_detail(home)
    print(("OK: audit chain intact" if d["ok"] else f"TAMPERED at record {d['bad_index']}: {d['reason']}"), f"({d['records']} records, signed={d['signed']})")
    sys.exit(0 if d["ok"] else 2)


def cmd_report(a):
    print(report.build(server.home_for(_root(a))))


def cmd_preflight(a):
    content = pathlib.Path(a.content_file).read_text() if a.content_file else ""
    r = server.preflight(_root(a), a.actor, [{"path": a.path, "content": content}])
    print(json.dumps(r, indent=2))
    sys.exit(1 if r["decision"] == "block" else 0)


def cmd_ml_eval(a):
    print(json.dumps(mlguard.evaluate(shield.injection_rule_hit), indent=2))


def cmd_hook(a):
    print("installed", hooks.install(_root(a)))


def cmd_hook_check(a):
    sys.exit(hooks.check("."))


def cmd_ci(a):
    """One command for CI: shield + gate + optimizer proposal -> SARIF + Markdown summary + exit code."""
    root = _root(a)
    st = server.state(root, a.base)
    finds = [x for f in st["files"] for x in f["findings"] if not x["waived"]]
    if a.sarif:
        pathlib.Path(a.sarif).write_text(json.dumps(export.sarif(finds, st["gate"]), indent=1))
    md = export.markdown(st)
    if a.summary:
        pathlib.Path(a.summary).write_text(md)
    print(md)
    audit.log(server.home_for(root), "ci", st["verdict"], a.actor, {"risk": st["risk"]["score"], "blocking": st["blocking"]})
    sys.exit(0 if st["verdict"] == "ready" else 1)


def main():
    ap = argparse.ArgumentParser(prog="repobrain", description="Policy, proof and clean code for AI-assisted repos")
    sub = ap.add_subparsers(dest="cmd", required=True)
    def add(name, fn, **kw):
        p = sub.add_parser(name, **kw); p.set_defaults(fn=fn); p.add_argument("--repo", default="."); return p
    p = add("serve", cmd_serve, help="open the 3D review console"); p.add_argument("--base", default="main"); p.add_argument("--port", type=int, default=8765); p.add_argument("--no-browser", action="store_true")
    p.set_defaults(repo=None)
    p = add("demo", cmd_demo, help="run the full story in the terminal"); p.add_argument("--approve", action="store_true")
    p = add("shield", cmd_shield); p.add_argument("--actor", default="unknown"); p.add_argument("--base"); p.add_argument("--sarif"); p.add_argument("files", nargs="*")
    p = add("gate", cmd_gate); p.add_argument("--base")
    p = add("optimize", cmd_optimize); p.add_argument("--base"); p.add_argument("--apply", action="store_true"); p.add_argument("--ai", action="store_true")
    p = add("explain", cmd_explain); p.add_argument("log"); p.add_argument("--ai", action="store_true")
    add("audit", cmd_audit); add("report", cmd_report)
    p = add("preflight", cmd_preflight); p.add_argument("--actor", required=True); p.add_argument("--path", required=True); p.add_argument("--content-file")
    add("ml-eval", cmd_ml_eval); add("install-hook", cmd_hook); add("hook-check", cmd_hook_check)
    p = add("ci", cmd_ci); p.add_argument("--base", default="origin/main"); p.add_argument("--actor", default="ci"); p.add_argument("--sarif"); p.add_argument("--summary")
    a = ap.parse_args()
    a.fn(a)
