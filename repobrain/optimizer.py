"""Optimizer: measures complexity, applies behaviour-preserving simplifications, verifies them
(project tests + differential fuzzing), and proposes a patch. It never pushes.

Design choices that matter:
  * Rewrites are spliced in PER FUNCTION. Code the optimizer did not touch (module header, comments,
    other functions) is byte-for-byte unchanged, so diffs stay small and reviewable.
  * A function that contains comments is NOT rewritten by default (policy `preserve_comments`),
    because re-printing an AST would silently delete them.
  * Every proposal must survive (1) the project's own tests on a scratch copy and (2) differential
    fuzzing of each rewritten function. Failing either discards the proposal.
"""
import ast, copy, difflib, importlib.util, io, json, os, pathlib, re, shutil, subprocess, sys, tempfile, time, tokenize
from collections import Counter
from . import audit, fuzz, llm

TERM = (ast.Return, ast.Raise, ast.Continue, ast.Break)
SKIP_DIRS = {".git", ".repobrain", "__pycache__", ".pytest_cache", "node_modules", "venv", ".venv"}


# ---------- measurement ----------
def complexity(fn):
    """Cyclomatic complexity (McCabe style)."""
    c = 1
    for n in ast.walk(fn):
        if isinstance(n, (ast.If, ast.For, ast.AsyncFor, ast.While, ast.ExceptHandler, ast.IfExp)):
            c += 1
        elif isinstance(n, ast.BoolOp):
            c += len(n.values) - 1
        elif isinstance(n, ast.comprehension):
            c += 1 + len(n.ifs)
    return c


def depth(node, d=0):
    m = d
    for ch in ast.iter_child_nodes(node):
        nd = d + 1 if isinstance(ch, (ast.If, ast.For, ast.While, ast.Try, ast.With)) else d
        m = max(m, depth(ch, nd))
    return m


def cognitive(fn):
    """Cognitive complexity (Sonar-style): structures cost more the deeper they are nested."""
    total = 0

    def expr_cost(node, nest):
        c = 0
        for n in ast.walk(node):
            if isinstance(n, ast.BoolOp): c += 1
            elif isinstance(n, ast.IfExp): c += 1 + nest
        return c

    def stmts(body, nest):
        for st in body:
            stmt(st, nest)

    def stmt(st, nest, elif_=False):
        nonlocal total
        if isinstance(st, ast.If):
            total += 1 + (0 if elif_ else nest) + expr_cost(st.test, nest)
            stmts(st.body, nest + 1)
            if len(st.orelse) == 1 and isinstance(st.orelse[0], ast.If):
                stmt(st.orelse[0], nest, True)
            elif st.orelse:
                total += 1; stmts(st.orelse, nest + 1)
        elif isinstance(st, (ast.For, ast.AsyncFor, ast.While)):
            total += 1 + nest + expr_cost(getattr(st, "test", None) or st.iter, nest)
            stmts(st.body, nest + 1); stmts(st.orelse, nest + 1)
        elif isinstance(st, ast.Try):
            stmts(st.body, nest)
            for h in st.handlers:
                total += 1 + nest; stmts(h.body, nest + 1)
            stmts(st.orelse, nest); stmts(st.finalbody, nest)
        elif isinstance(st, (ast.With, ast.AsyncWith)):
            stmts(st.body, nest)
        elif isinstance(st, (ast.FunctionDef, ast.AsyncFunctionDef)):
            stmts(st.body, nest + 1)
        else:
            total += expr_cost(st, nest)

    stmts(fn.body, 0)
    return total


def analyze(src):
    return [{"name": n.name, "line": n.lineno, "complexity": complexity(n), "cognitive": cognitive(n),
             "depth": depth(n), "lines": n.end_lineno - n.lineno + 1}
            for n in ast.walk(ast.parse(src)) if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))]


def metrics(src):
    rows = analyze(src)
    return {"functions": len(rows), "max_complexity": max([r["complexity"] for r in rows], default=0),
            "total_complexity": sum(r["complexity"] for r in rows),
            "max_cognitive": max([r["cognitive"] for r in rows], default=0),
            "total_cognitive": sum(r["cognitive"] for r in rows),
            "max_depth": max([r["depth"] for r in rows], default=0),
            "loc": sum(1 for l in src.splitlines() if l.strip())}


def violations(rows, policy):
    """Why (if at all) each function breaks the policy."""
    out = []
    for r in rows:
        why = []
        if r["complexity"] > policy["max_complexity"]: why.append(f"complexity {r['complexity']} > {policy['max_complexity']}")
        if r["depth"] > policy["max_depth"]: why.append(f"nesting {r['depth']} > {policy['max_depth']}")
        if policy.get("max_cognitive") and r["cognitive"] > policy["max_cognitive"]:
            why.append(f"cognitive {r['cognitive']} > {policy['max_cognitive']}")
        if why:
            out.append({**r, "why": why})
    return out


# ---------- behaviour-preserving rewrites ----------
def _terminates(b):
    """True when every path through this statement list ends in return/raise/continue/break."""
    if not b:
        return False
    last = b[-1]
    if isinstance(last, TERM):
        return True
    return isinstance(last, ast.If) and bool(last.orelse) and _terminates(last.body) and _terminates(last.orelse)


def _is_bool(n, v=None):
    return isinstance(n, ast.Return) and isinstance(n.value, ast.Constant) and isinstance(n.value.value, bool) \
        and (v is None or n.value.value is v)


def _bool_return(test, val):
    if val:
        plain = isinstance(test, ast.Compare) or (isinstance(test, ast.UnaryOp) and isinstance(test.op, ast.Not))
        return ast.Return(test if plain else ast.Call(ast.Name("bool", ast.Load()), [test], []))
    return ast.Return(ast.UnaryOp(ast.Not(), test))


def _is_append(st, r):
    return (isinstance(st, ast.Expr) and isinstance(st.value, ast.Call)
            and isinstance(st.value.func, ast.Attribute) and st.value.func.attr == "append"
            and isinstance(st.value.func.value, ast.Name) and st.value.func.value.id == r
            and len(st.value.args) == 1 and not st.value.keywords)


def _append_comp(f, r):
    body, ifs = f.body, []
    if len(body) == 1 and isinstance(body[0], ast.If) and not body[0].orelse:
        ifs, body = [body[0].test], body[0].body
    if len(body) == 1 and _is_append(body[0], r):
        elt = body[0].value.args[0]
        if not any(isinstance(n, ast.Name) and n.id == r for n in ast.walk(elt)) \
                and not any(isinstance(n, ast.Name) and n.id == r for t in ifs for n in ast.walk(t)):
            return ast.ListComp(elt, [ast.comprehension(f.target, f.iter, ifs, 0)])
    return None


class Rewriter(ast.NodeTransformer):
    def __init__(self):
        self.notes = []

    def visit_Compare(self, n):
        self.generic_visit(n)
        if len(n.ops) == 1 and isinstance(n.ops[0], (ast.Eq, ast.NotEq)) \
                and isinstance(n.comparators[0], ast.Constant) and n.comparators[0].value is None:
            n.ops = [ast.Is() if isinstance(n.ops[0], ast.Eq) else ast.IsNot()]
            self.notes.append("== None -> is None")
        return n

    def generic_visit(self, node):
        super().generic_visit(node)
        for f in ("body", "orelse", "finalbody"):
            b = getattr(node, f, None)
            if isinstance(b, list) and b and isinstance(b[0], ast.stmt):
                setattr(node, f, self.block(b))
        return node

    def block(self, b):
        changed = True
        while changed:                                   # drop 'else' after a branch that always exits
            changed, out = False, []
            for st in b:
                if isinstance(st, ast.If) and st.orelse and _terminates(st.body):
                    out += [ast.If(st.test, st.body, [])] + st.orelse
                    changed = True
                    self.notes.append("flattened else-after-return")
                else:
                    out.append(st)
            b = out
        out, i = [], 0
        while i < len(b):
            st, nxt = b[i], (b[i + 1] if i + 1 < len(b) else None)
            if isinstance(st, ast.If) and not st.orelse and len(st.body) == 1 and _is_bool(st.body[0]) \
                    and nxt is not None and _is_bool(nxt) and st.body[0].value.value is not nxt.value.value:
                out.append(_bool_return(st.test, st.body[0].value.value)); i += 2
                self.notes.append("collapsed boolean return"); continue
            if isinstance(st, ast.Assign) and len(st.targets) == 1 and isinstance(st.targets[0], ast.Name) \
                    and isinstance(st.value, ast.List) and not st.value.elts \
                    and isinstance(nxt, ast.For) and not nxt.orelse:
                comp = _append_comp(nxt, st.targets[0].id)
                if comp is not None:
                    out.append(ast.Assign([ast.Name(st.targets[0].id, ast.Store())], comp)); i += 2
                    self.notes.append("loop + append -> list comprehension"); continue
            if isinstance(st, ast.If) and not st.orelse and len(st.body) == 1 \
                    and isinstance(st.body[0], ast.If) and not st.body[0].orelse:
                inner = st.body[0]
                st = ast.If(ast.BoolOp(ast.And(), [st.test, inner.test]), inner.body, [])
                self.notes.append("merged nested ifs")
            out.append(st); i += 1
        return out


# ---------- splicing ----------
def _comment_rows(src):
    rows = set()
    try:
        for t in tokenize.generate_tokens(io.StringIO(src).readline):
            if t.type == tokenize.COMMENT:
                rows.add(t.start[0])
    except (tokenize.TokenError, IndentationError):
        pass
    return rows


def _unparse_indented(node, col):
    text = ast.unparse(node)
    skip = set()                                         # rows that are inside a multi-line string literal
    try:
        for t in tokenize.generate_tokens(io.StringIO(text).readline):
            if t.type == tokenize.STRING and t.end[0] > t.start[0]:
                skip.update(range(t.start[0] + 1, t.end[0] + 1))
    except (tokenize.TokenError, IndentationError):
        pass
    pad = " " * col
    return "\n".join(l if (i + 1 in skip or not l) else pad + l for i, l in enumerate(text.split("\n"))) + "\n"


def _outer_functions(body):
    for n in body:
        if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)):
            yield n
        elif isinstance(n, ast.ClassDef):
            yield from _outer_functions(n.body)


def _unused_import_edits(tree, lines, notes):
    if any(isinstance(n, ast.Assign) and any(isinstance(t, ast.Name) and t.id == "__all__" for t in n.targets) for n in tree.body):
        return []
    used = {n.id for n in ast.walk(tree) if isinstance(n, ast.Name)}
    used |= {n.value for n in ast.walk(tree) if isinstance(n, ast.Constant) and isinstance(n.value, str) and n.value.isidentifier()}
    edits = []
    for st in tree.body:
        if not isinstance(st, (ast.Import, ast.ImportFrom)) or (isinstance(st, ast.ImportFrom) and (st.module == "__future__" or st.level)):
            continue
        seg = "".join(lines[st.lineno - 1: st.end_lineno])
        if "noqa" in seg or "type:" in seg:
            continue
        keep = [a for a in st.names if a.name == "*" or (a.asname or a.name.split(".")[0]) in used]
        if len(keep) == len(st.names):
            continue
        notes.append("removed unused import")
        if keep:
            clone = copy.copy(st); clone.names = keep
            edits.append((st.lineno, st.end_lineno, ast.unparse(clone) + "\n"))
        else:
            edits.append((st.lineno, st.end_lineno, ""))
    return edits


def rewrite(src, preserve_comments=True):
    """Returns (new_src, notes, details). details: per-function {name, line, notes|skipped}."""
    tree = ast.parse(src)
    lines = src.splitlines(keepends=True)
    crows = _comment_rows(src)
    edits, notes, details = [], [], []
    for fn in _outer_functions(tree.body):
        rw = Rewriter()
        new_fn = ast.fix_missing_locations(rw.visit(copy.deepcopy(fn)))
        if not rw.notes:
            continue
        start = min([fn.lineno] + [d.lineno for d in fn.decorator_list])
        if preserve_comments and any(start <= r <= fn.end_lineno for r in crows):
            details.append({"name": fn.name, "line": fn.lineno, "skipped": "contains comments; left untouched so none are lost"})
            continue
        edits.append((start, fn.end_lineno, _unparse_indented(new_fn, fn.col_offset)))
        notes += rw.notes
        details.append({"name": fn.name, "line": fn.lineno, "notes": dict(Counter(rw.notes))})
    edits += _unused_import_edits(tree, lines, notes)
    if not edits:
        return src, [], details
    for s, e, text in sorted(edits, reverse=True):
        lines[s - 1:e] = [text] if text else []
    new = "".join(lines)
    if not src.startswith("\n"):
        new = new.lstrip("\n")                           # imports removed from the top: no dangling blank lines
    try:
        ast.parse(new)
    except SyntaxError:                                  # never emit code that does not parse
        return src, [], details + [{"name": "*", "line": 0, "skipped": "rewrite produced invalid syntax; discarded"}]
    return new, notes, details


def changed_functions(old, new):
    """Names of top-level functions whose AST differs between two versions of a file."""
    def table(s):
        return {n.name: ast.dump(n) for n in ast.parse(s).body if isinstance(n, ast.FunctionDef)}
    o, n = table(old), table(new)
    return [k for k in n if k in o and o[k] != n[k]]


def ai_refine(src, policy):
    """Optional: ask an LLM to further simplify functions that still break policy. Verified like any other change."""
    if not violations(analyze(src), policy):
        return None
    try:
        reply = llm.ask("Simplify this Python for readability and lower complexity WITHOUT changing behaviour. "
                        "Keep comments and public names. Return only the full file in one ```python block.\n\n" + src,
                        system="You are a careful refactoring tool.")
        m = re.search(r"```python\n(.*?)```", reply, re.S)
        if m:
            ast.parse(m.group(1))
            return m.group(1)
    except Exception:
        pass
    return None


# ---------- selection, verification, proposal ----------
def select(root, files=None, base=None):
    root = pathlib.Path(root)
    if files:
        cand = list(files)
    elif base:
        out = subprocess.run(["git", "diff", "--name-only", f"{base}...HEAD"], cwd=root, capture_output=True, text=True)
        cand = out.stdout.splitlines()
    else:
        cand = [str(p.relative_to(root)) for p in root.rglob("*.py") if not (set(p.relative_to(root).parts) & SKIP_DIRS)]
    keep = []
    for f in cand:
        name = pathlib.PurePath(f).name
        if f.endswith(".py") and not (name.startswith("test_") or name.endswith("_test.py") or name == "__init__.py") \
                and (root / f).is_file():
            keep.append(f)
    return sorted(keep)


def _has_tests(root):
    return any(root.rglob("test_*.py")) or any(root.rglob("*_test.py"))


def verify(root, new_srcs):
    """Run the project's tests against the rewritten code in a scratch copy.
    Returns (ok, info). ok: True / False / None (no tests, or none could be run). info: runner, counts, output."""
    root = pathlib.Path(root)
    if not _has_tests(root):
        return None, {"runner": None, "passed": 0, "failed": 0, "skipped": 0, "output": "no tests found"}
    use_pytest = importlib.util.find_spec("pytest") is not None
    with tempfile.TemporaryDirectory() as tmp:
        work = pathlib.Path(tmp) / "w"
        shutil.copytree(root, work, ignore=shutil.ignore_patterns(*SKIP_DIRS))
        for rel, src in new_srcs.items():
            (work / rel).write_text(src)
        env = {**os.environ, "PYTHONPATH": str(pathlib.Path(__file__).resolve().parent.parent), "PYTHONDONTWRITEBYTECODE": "1"}
        cmd = [sys.executable, "-m", "pytest", "-q", "-x", "-p", "no:cacheprovider"] if use_pytest else [sys.executable, "-m", "repobrain.minitest", "."]
        p = subprocess.run(cmd, cwd=work, capture_output=True, text=True, timeout=180, env=env)
        out = (p.stdout + p.stderr).strip()
    g = lambda w: int(m.group(1)) if (m := re.search(rf"(\d+) {w}", out)) else 0
    info = {"runner": "pytest" if use_pytest else "builtin", "passed": g("passed"), "failed": g("failed"),
            "skipped": g("skipped"), "output": out[-600:]}
    if p.returncode != 0:
        return False, info
    if info["passed"] == 0:                              # everything skipped: do not pretend we verified anything
        info["output"] = "no runnable tests (all skipped): " + info["output"]
        return None, info
    return True, info


def gate(root, policy, files=None, base=None):
    if policy.get("optimize") != "required":
        return []
    bad = []
    for rel in select(root, files, base):
        try:
            rows = analyze((pathlib.Path(root) / rel).read_text())
        except SyntaxError:
            continue
        bad += [{"file": rel, **v} for v in violations(rows, policy)]
    return bad


def _log(on, *a):
    return audit.log(*a) if on else None


def run(root, policy, home, files=None, base=None, apply=False, ai=False, allow_unverified=False, log=True):
    root = pathlib.Path(root)
    res = {"ts": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()), "files": [], "tests": None, "fuzz": None, "status": ""}
    new_srcs, fuzz_total = {}, {"checked_functions": 0, "inputs": 0, "diverged": 0}
    for rel in select(root, files, base):
        src = (root / rel).read_text()
        try:
            before = metrics(src)
            new, notes, details = rewrite(src, policy.get("preserve_comments", True))
            if ai and llm.available():
                refined = ai_refine(new, policy)
                if refined:
                    new, notes = refined, notes + ["AI refinement"]
            after = metrics(new)
        except SyntaxError:
            continue
        fz, rejected = None, None
        if new != src and policy.get("fuzz", True):
            fz = fuzz.differential(src, new, changed_functions(src, new))
            for k in ("checked_functions", "inputs", "diverged"):
                fuzz_total[k] += fz[k]
            if fz["diverged"]:
                bad = next((n for n, r in fz["functions"].items() if r["diverged"]), "?")
                rejected = f"differential fuzz: {bad}() behaved differently on {fz['functions'][bad]['example']['input']}"
                new, notes, after = src, [], before
        if new != src:
            new_srcs[rel] = new
        diff = "".join(difflib.unified_diff(src.splitlines(True), new.splitlines(True), f"a/{rel}", f"b/{rel}"))
        old_rows = {r["name"]: r for r in analyze(src)}
        keys = ("complexity", "cognitive", "depth", "lines")
        fn_rows = [{"name": r["name"], "line": r["line"],
                    "before": ({k: old_rows[r["name"]][k] for k in keys} if r["name"] in old_rows else None),
                    "after": {k: r[k] for k in keys}} for r in analyze(new)]
        res["files"].append({"path": rel, "before": before, "after": after, "changes": dict(Counter(notes)), "diff": diff,
                             "functions": fn_rows, "skipped": [d for d in details if "skipped" in d], "fuzz": fz, "rejected": rejected})
    res["fuzz"] = fuzz_total if fuzz_total["inputs"] else None
    if not new_srcs:
        res["status"] = "rejected (fuzz found a behaviour change)" if any(f["rejected"] for f in res["files"]) else "nothing to optimize"
        _log(log, home, "optimize", "rejected" if res["status"].startswith("rejected") else "no-op", "repobrain", {"files": len(res["files"])})
        return res
    ok, info = verify(root, new_srcs)
    res["tests"] = {"ok": ok, **info}
    if ok is False:
        res["status"] = "rejected (tests failed, nothing proposed)"
        _log(log, home, "optimize", "rejected", "repobrain", {"reason": "tests failed", "files": list(new_srcs)})
        return res
    pdir = pathlib.Path(home) / "proposals"
    pdir.mkdir(parents=True, exist_ok=True)
    patch = "".join(l for rel, new in new_srcs.items() for l in difflib.unified_diff(
        (root / rel).read_text().splitlines(True), new.splitlines(True), f"a/{rel}", f"b/{rel}"))
    (pdir / "latest.patch").write_text(patch)
    res["status"] = "proposed (awaiting human review)" if ok else "proposed (UNVERIFIED: no runnable tests)"
    _log(log, home, "optimize", "proposed", "repobrain",
         {"files": list(new_srcs), "tests_passed": ok, "fuzz_inputs": fuzz_total["inputs"], "fuzz_divergences": fuzz_total["diverged"]})
    if apply and (ok or allow_unverified):
        for rel, new in new_srcs.items():
            (root / rel).write_text(new)
        res["status"] = "applied after human approval"
        _log(log, home, "optimize", "approved+applied", "human", {"files": list(new_srcs)})
    (pdir / "latest.json").write_text(json.dumps(res, indent=2))
    return res
