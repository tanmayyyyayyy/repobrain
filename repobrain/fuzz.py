"""Differential fuzzing: prove a rewritten function behaves like the original, beyond the project's tests.

For every rewritten function that looks pure (no I/O, no imports, no unknown names), run the old and
new versions on a few hundred generated inputs (boundary values mined from the function's own
constants, plus type-confused inputs) in a resource-limited subprocess, and compare results,
exception types and argument mutation. Any divergence rejects the rewrite.
"""
import ast, json, os, pathlib, subprocess, sys

HARNESS = pathlib.Path(__file__).with_name("_fuzz_harness.py")
SAFE_BUILTINS = set("abs all any bool dict divmod enumerate filter float int isinstance len list map max min pow range reversed round set sorted str sum tuple zip repr ord chr TypeError ValueError KeyError IndexError ZeroDivisionError AttributeError Exception True False None".split())
SAFE_METHODS = set("""get lower upper strip lstrip rstrip split rsplit join startswith endswith replace format items keys values append extend count index
isdigit isalpha isnumeric title capitalize copy update pop add sort reverse find rfind zfill ljust rjust center partition rpartition isupper
islower isspace casefold splitlines setdefault insert remove clear discard union intersection difference bit_length is_integer""".split())


def _top(tree):
    return {n.name: n for n in tree.body if isinstance(n, ast.FunctionDef)}


def _literal(node):
    try:
        ast.literal_eval(node); return True
    except Exception:
        return False


def pure_reason(fn, known):
    """None if the function looks pure enough to fuzz, else a short reason."""
    bound = {a.arg for n in ast.walk(fn) if isinstance(n, ast.arguments) for a in n.args + n.kwonlyargs + n.posonlyargs}
    for n in ast.walk(fn):
        if isinstance(n, (ast.Import, ast.ImportFrom, ast.Global, ast.Nonlocal, ast.Await, ast.AsyncFunctionDef, ast.Yield, ast.YieldFrom)):
            return f"uses {type(n).__name__.lower()}"
        if isinstance(n, ast.Name) and isinstance(n.ctx, (ast.Store, ast.Del)):
            bound.add(n.id)
        if isinstance(n, ast.ExceptHandler) and n.name:
            bound.add(n.name)
        if isinstance(n, (ast.FunctionDef, ast.Lambda)) and n is not fn and isinstance(n, ast.FunctionDef):
            bound.add(n.name)
    for n in ast.walk(fn):
        if isinstance(n, ast.Call):
            f = n.func
            if isinstance(f, ast.Name) and f.id not in SAFE_BUILTINS | known | bound:
                return f"calls '{f.id}()'"
            if isinstance(f, ast.Attribute) and f.attr not in SAFE_METHODS:
                return f"calls method '.{f.attr}()'"
            if not isinstance(f, (ast.Name, ast.Attribute)):
                return "calls a computed callable"
        if isinstance(n, ast.Name) and isinstance(n.ctx, ast.Load) and n.id not in SAFE_BUILTINS | known | bound:
            return f"references external name '{n.id}'"
    return None


def _prelude(tree, names_ok):
    """Module-level literal constants + the pure top-level functions, as source text."""
    parts = []
    for n in tree.body:
        if isinstance(n, ast.Assign) and len(n.targets) == 1 and isinstance(n.targets[0], ast.Name) and _literal(n.value):
            parts.append(ast.unparse(n))
        elif isinstance(n, ast.FunctionDef) and n.name in names_ok:
            parts.append(ast.unparse(n))
    return "\n\n".join(parts)


def _consts(fn):
    nums, strs = [], []
    for n in ast.walk(fn):
        if isinstance(n, ast.Constant):
            if isinstance(n.value, bool): continue
            if isinstance(n.value, (int, float)) and abs(n.value) < 1e9 and n.value not in nums: nums.append(n.value)
            if isinstance(n.value, str) and 0 < len(n.value) < 24 and n.value not in strs: strs.append(n.value)
    return {"nums": nums[:24], "strs": strs[:16]}


def _params(fn):
    a = fn.args
    pos = a.posonlyargs + a.args
    defaults = [None] * (len(pos) - len(a.defaults)) + list(a.defaults)
    out = []
    for p, d in zip(pos, defaults):
        dv = None
        if d is not None and _literal(d):
            dv = ast.literal_eval(d)
        out.append({"name": p.arg, "default": dv if isinstance(dv, (bool, int, float, str, list, dict)) else None})
    return out


def differential(old_src, new_src, names, n=250, seed=0, timeout=15):
    """Returns {"functions": {name: {...}}, "checked_functions", "inputs", "diverged", "skipped": {name: reason}}."""
    res = {"functions": {}, "checked_functions": 0, "inputs": 0, "diverged": 0, "skipped": {}}
    try:
        ot, nt = ast.parse(old_src), ast.parse(new_src)
    except SyntaxError as e:
        res["skipped"]["*"] = f"syntax error: {e.msg}"; return res
    of, nf = _top(ot), _top(nt)
    pure_old = {k for k, v in of.items() if pure_reason(v, set(of) - {k}) is None}
    pure_new = {k for k, v in nf.items() if pure_reason(v, set(nf) - {k}) is None}
    targets = []
    for name in names:
        if name not in of or name not in nf:
            res["skipped"][name] = "not a top-level function"; continue
        r = pure_reason(of[name], pure_old - {name}) or pure_reason(nf[name], pure_new - {name})
        if r:
            res["skipped"][name] = r; continue
        targets.append({"name": name, "params": _params(of[name]), "consts": _consts(of[name])})
    if not targets:
        return res
    job = {"old": _prelude(ot, pure_old), "new": _prelude(nt, pure_new), "targets": targets, "n": n, "seed": seed}

    def limits():                                           # POSIX only; harmless elsewhere
        try:
            import resource
            resource.setrlimit(resource.RLIMIT_CPU, (timeout, timeout))
            resource.setrlimit(resource.RLIMIT_AS, (768 * 2**20, 768 * 2**20))
            resource.setrlimit(resource.RLIMIT_FSIZE, (0, 0))
        except Exception:
            pass
    try:
        p = subprocess.run([sys.executable, "-I", str(HARNESS)], input=json.dumps(job), capture_output=True, text=True,
                           timeout=timeout, preexec_fn=limits if os.name == "posix" else None, cwd="/")
        out = json.loads(p.stdout) if p.returncode == 0 and p.stdout else None
    except (subprocess.TimeoutExpired, ValueError):
        out = None
    if out is None:
        for t in targets:
            res["skipped"][t["name"]] = "fuzz harness failed or timed out"
        return res
    for name, r in out.items():
        res["functions"][name] = r
        res["checked_functions"] += 1; res["inputs"] += r["checked"]; res["diverged"] += r["diverged"]
    return res
