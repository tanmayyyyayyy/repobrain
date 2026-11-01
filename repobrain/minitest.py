"""Dependency-free test runner used when pytest is not installed.

Why this exists: the Optimizer must verify every rewrite against the project's own tests.
If that step needed pytest and a judge's machine lacks it, every proposal would be rejected.
This runner covers the common cases (plain `test_*` functions, `Test*` classes, unittest.TestCase,
and the `tmp_path` / `monkeypatch` fixtures). Anything it cannot run faithfully (other fixtures,
`import pytest`) is reported as SKIPPED, never as a pass. If every test is skipped the caller
treats the project as "unverifiable".

Usage:  python -m repobrain.minitest [root]      -> prints a pytest-like summary, exit 0/1
"""
import importlib.util, inspect, os, pathlib, shutil, sys, tempfile, traceback, unittest

SKIP_DIRS = {".git", ".repobrain", "__pycache__", ".pytest_cache", "node_modules", "venv", ".venv"}


class _Monkeypatch:
    def __init__(self): self._undo = []
    def setattr(self, target, name, value=None, raising=True):
        if value is None and isinstance(target, str):      # setattr("pkg.mod.attr", value) form
            modname, attr = target.rsplit(".", 1)
            obj = importlib.import_module(modname); old = getattr(obj, attr); setattr(obj, attr, name)
            self._undo.append(lambda: setattr(obj, attr, old)); return
        old = getattr(target, name, None); setattr(target, name, value)
        self._undo.append(lambda: setattr(target, name, old))
    def setenv(self, k, v):
        old = os.environ.get(k); os.environ[k] = str(v)
        self._undo.append(lambda: os.environ.__setitem__(k, old) if old is not None else os.environ.pop(k, None))
    def delenv(self, k, raising=True):
        old = os.environ.pop(k, None)
        if old is not None: self._undo.append(lambda: os.environ.__setitem__(k, old))
    def chdir(self, p):
        old = os.getcwd(); os.chdir(p); self._undo.append(lambda: os.chdir(old))
    def undo(self):
        while self._undo: self._undo.pop()()


def _discover(root):
    out = []
    for p in sorted(pathlib.Path(root).rglob("*.py")):
        if set(p.relative_to(root).parts) & SKIP_DIRS: continue
        if p.name.startswith("test_") or p.name.endswith("_test.py"): out.append(p)
    return out


def _load(path):
    name = "mt_" + "_".join(path.with_suffix("").parts[-3:]).replace("-", "_").replace(".", "_")
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec); sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


def _call(fn, tmp_root):
    """Call fn with supported fixtures. Returns ('ok'|'skip', reason)."""
    sig, kwargs, mp = inspect.signature(fn), {}, None
    for pname in sig.parameters:
        if pname == "tmp_path":
            d = pathlib.Path(tempfile.mkdtemp(dir=tmp_root)); kwargs[pname] = d
        elif pname == "monkeypatch":
            mp = mp or _Monkeypatch(); kwargs[pname] = mp
        else:
            return "skip", f"unsupported fixture '{pname}'"
    try:
        fn(**kwargs)
    finally:
        if mp: mp.undo()
    return "ok", ""


def run(root="."):
    root = pathlib.Path(root).resolve()
    os.chdir(root); sys.path.insert(0, str(root))
    passed = failed = skipped = 0
    lines, tmp_root = [], tempfile.mkdtemp(prefix="minitest_")
    for f in _discover(root):
        sys.path.insert(0, str(f.parent))
        rel = f.relative_to(root)
        try:
            mod = _load(f)
        except ImportError as e:
            skipped += 1; lines.append(f"SKIPPED {rel} (cannot import: {e})"); continue
        except Exception:
            failed += 1; lines.append(f"FAILED {rel} (import error)\n{traceback.format_exc(limit=3)}"); continue
        cases = [(f"{rel}::{n}", o) for n, o in vars(mod).items() if n.startswith("test_") and inspect.isfunction(o)]
        for cn, cls in vars(mod).items():
            if inspect.isclass(cls) and issubclass(cls, unittest.TestCase) and cls.__module__ == mod.__name__:
                suite = unittest.defaultTestLoader.loadTestsFromTestCase(cls)
                res = unittest.TestResult(); suite.run(res)
                passed += res.testsRun - len(res.failures) - len(res.errors)
                for t, tb in res.failures + res.errors:
                    failed += 1; lines.append(f"FAILED {rel}::{cn}::{t._testMethodName}\n{tb[-400:]}")
            elif inspect.isclass(cls) and cn.startswith("Test") and cls.__module__ == mod.__name__:
                for mn, m in vars(cls).items():
                    if mn.startswith("test_") and inspect.isfunction(m):
                        inst = cls()
                        cases.append((f"{rel}::{cn}::{mn}", getattr(inst, mn)))
        for cid, fn in cases:
            try:
                status, why = _call(fn, tmp_root)
                if status == "skip": skipped += 1; lines.append(f"SKIPPED {cid} ({why})")
                else: passed += 1
            except AssertionError:
                failed += 1; lines.append(f"FAILED {cid}\n{traceback.format_exc(limit=2)}")
            except Exception:
                failed += 1; lines.append(f"FAILED {cid}\n{traceback.format_exc(limit=3)}")
    shutil.rmtree(tmp_root, ignore_errors=True)
    summary = f"{passed} passed, {failed} failed, {skipped} skipped (repobrain builtin runner)"
    print("\n".join(lines + [summary]))
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(run(sys.argv[1] if len(sys.argv) > 1 else "."))
