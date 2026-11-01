"""Failure Explainer: turns build/test logs into plain-language causes, fixes and (where safe) a patch."""
import re
from . import deps, llm

# import name -> PyPI package name, for the cases where they differ
PIP = {"yaml": "pyyaml", "cv2": "opencv-python", "PIL": "pillow", "sklearn": "scikit-learn", "bs4": "beautifulsoup4",
       "dateutil": "python-dateutil", "jwt": "pyjwt", "dotenv": "python-dotenv", "OpenSSL": "pyopenssl", "Crypto": "pycryptodome",
       "MySQLdb": "mysqlclient", "serial": "pyserial", "git": "gitpython", "magic": "python-magic", "skimage": "scikit-image"}

# (regex, cause, fix, category)
RULES = [
    (r"ModuleNotFoundError: No module named '([\w\.]+)'", "A Python package is missing: '{0}'.", "Add it to requirements.txt and reinstall (pip install -r requirements.txt).", "dependency"),
    (r"ImportError: cannot import name '(\w+)' from '([\w\.]+)'", "'{1}' has no name '{0}' (version mismatch or a typo).", "Check the installed version of '{1}' and the import spelling.", "dependency"),
    (r"Cannot find module '([^']+)'", "Node cannot find module '{0}'.", "Run npm install, or add '{0}' to package.json.", "dependency"),
    (r"error TS(\d+): (.+)", "TypeScript compile error TS{0}: {1}.", "Fix the type error at the location shown; run tsc --noEmit locally.", "code"),
    (r"SyntaxError: (.+)", "Python could not parse a file: {0}.", "Open the file and line shown above and fix the syntax.", "code"),
    (r"IndentationError: (.+)", "Inconsistent indentation: {0}.", "Use 4 spaces consistently, no tabs.", "code"),
    (r"AssertionError(?:: (.+))?", "A test assertion failed {0}.", "Compare expected vs actual values in the failing test; check recent logic changes.", "test"),
    (r"KeyError: (.+)", "Code read a missing dictionary key {0}.", "Use .get() with a default, or make sure the key is set before use.", "code"),
    (r"AttributeError: (.+)", "Code used something that does not exist: {0}.", "Check for a None value or a renamed attribute.", "code"),
    (r"TypeError: (.+)", "Wrong type passed or used: {0}.", "Check argument types and None values at the call site.", "code"),
    (r"ZeroDivisionError", "Code divided by zero.", "Guard the divisor or handle the empty-input case.", "code"),
    (r"(?:Process completed with exit code 137|Killed|MemoryError|OOMKilled|JavaScript heap out of memory)", "The job ran out of memory.", "Reduce parallelism, raise the runner memory limit, or fix the leak/large allocation.", "infra"),
    (r"(?:timed out|TimeoutError|deadline exceeded|exceeded the maximum execution time)", "A step or request took too long.", "Check for an infinite loop or a hung network call; raise the timeout only after that.", "infra"),
    (r"Permission denied", "The process lacked permission for a file or command.", "Check file modes and that the CI token has the needed scopes.", "infra"),
    (r"command not found", "A command used in the pipeline is not installed.", "Install it in the workflow before running the step.", "infra"),
    (r"Connection (?:refused|timed out|reset)|ECONNREFUSED|Name or service not known", "A service could not be reached.", "Check the service is running and the host/port or secret is correct.", "infra"),
    (r"npm ERR! (.+)", "npm failed: {0}.", "Delete node_modules and lockfile conflicts, then reinstall.", "dependency"),
    (r"ERESOLVE|Could not find a version that satisfies the requirement ([\w\-\.]+)", "Dependency resolution failed {0}.", "Loosen or align the conflicting version pins, then regenerate the lockfile.", "dependency"),
    (r"E: Unable to locate package ([\w\-\.]+)", "apt cannot find package '{0}'.", "Run apt-get update first, or fix the package name.", "infra"),
    (r"(?:fatal: )?[Aa]uthentication failed|401 Unauthorized|403 Forbidden", "Credentials were rejected.", "Refresh the token/secret and confirm it has the right scopes.", "infra"),
    (r"error: (?:linker|could not compile) `?([\w\-]+)`?", "Rust failed to build '{0}'.", "Read the first compiler error above; fix it before the linker messages.", "code"),
    (r"(\d+) problems? \((\d+) errors?", "ESLint reported {1} error(s).", "Run the linter locally with --fix and review what is left.", "lint"),
    (r"(?:ruff|flake8|pylint).*?(\w\d{3,4}) ", "A linter rule ({0}) failed.", "Run the linter locally and fix the reported lines.", "lint"),
]


def _confidence(n_matches, has_loc):
    return "high" if n_matches and has_loc else ("medium" if n_matches else "low")


def explain(text, use_ai=False):
    out, mods = [], []
    for rx, cause, fix, cat in RULES:
        m = re.search(rx, text)
        if m:
            args = [g or "" for g in m.groups()] or [""]
            args += [""] * 4
            f = {"cause": cause.format(*args).replace(" .", "."), "fix": fix.format(*args), "evidence": m.group(0)[:120], "category": cat}
            if rx.startswith("ModuleNotFoundError"):
                mods.append(m.group(1).split(".")[0])
            out.append(f)
    loc = re.findall(r'File "([^"]+)", line (\d+)', text) or re.findall(r"([\w/\.-]+\.(?:py|js|ts|tsx|rs|go)):(\d+)", text)
    patches = []
    for mod in dict.fromkeys(mods):
        pkg = PIP.get(mod, mod.replace("_", "-"))
        patch = {"file": "requirements.txt", "kind": "append-line", "line": pkg,
                 "diff": f"--- a/requirements.txt\n+++ b/requirements.txt\n@@\n+{pkg}\n", "note": f"import '{mod}' -> PyPI package '{pkg}'"}
        t = deps.typosquat_of(pkg, deps.PY_POPULAR)      # AI-hallucinated package names are a supply-chain attack vector
        if t:
            patch["warning"] = f"'{pkg}' resembles the popular package '{t[0]}': verify it exists and is the one you intend before installing"
        patches.append(patch)
    summary = {"findings": out, "location": f"{loc[-1][0]}:{loc[-1][1]}" if loc else None,
               "failed_tests": re.findall(r"FAILED ([\w/\.:\[\]-]+)", text), "patches": patches,
               "confidence": _confidence(len(out), bool(loc)), "lines": len(text.splitlines())}
    if use_ai and llm.available():
        try:
            summary["ai_explanation"] = llm.ask("Explain this build failure in 3 plain sentences and give the fix:\n" + text[-6000:])
        except Exception as e:
            summary["ai_explanation"] = f"(AI unavailable: {e})"
    return summary
