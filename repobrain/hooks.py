"""Local git hook: close the 'developer bypasses the tool' gap by checking staged changes before commit."""
import pathlib, re, stat, subprocess, sys
from . import policy, shield

HOOK = """#!/bin/sh
# installed by RepoBrain: scans staged changes with the same policy as CI
exec "{py}" -m repobrain hook-check
"""


def install(root="."):
    hooks = pathlib.Path(root) / ".git" / "hooks"
    if not hooks.is_dir():
        raise SystemExit("not a git repository")
    f = hooks / "pre-commit"
    f.write_text(HOOK.format(py=sys.executable))
    f.chmod(f.stat().st_mode | stat.S_IEXEC | stat.S_IXGRP | stat.S_IXOTH)
    return f


def staged(root="."):
    names = subprocess.run(["git", "diff", "--cached", "--name-only", "--diff-filter=AM"], cwd=root, capture_output=True, text=True).stdout.split()
    added = {}
    for n in names:
        out = subprocess.run(["git", "diff", "--cached", "-U0", "--", n], cwd=root, capture_output=True, text=True).stdout
        ln, d = 0, {}
        for l in out.splitlines():
            if l.startswith("@@"):
                m = re.search(r"\+(\d+)", l); ln = int(m.group(1)) if m else 0
            elif l.startswith("+") and not l.startswith("+++"):
                d[ln] = l[1:]; ln += 1
        added[n] = d
    return names, added


def check(root="."):
    pol = policy.load(pathlib.Path(root) / "repobrain.yml")
    actor = subprocess.run(["git", "config", "user.name"], cwd=root, capture_output=True, text=True).stdout.strip() or "developer"
    names, added = staged(root)
    finds = shield.check(root, names, pol, actor, added=added)
    bad = [f for f in finds if f["severity"] == "block"]
    for f in finds:
        print(f"[RepoBrain] {f['severity'].upper():5} {f['rule']:18} {f['file']}:{f.get('line') or ''}  {f['msg']}")
    if bad:
        print(f"[RepoBrain] commit blocked by {len(bad)} finding(s). Fix them, or ask a reviewer to waive in the console.")
    return 1 if bad else 0
