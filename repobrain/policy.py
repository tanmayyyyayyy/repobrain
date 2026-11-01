"""Policy loading with validation. One YAML file is the single source of truth for every agent."""
import pathlib
import yaml

DEFAULT = {
    "version": 1,
    "optimize": "required", "approval": "human", "ai_changes": "log_all",
    "max_complexity": 10, "max_depth": 3, "max_cognitive": 15, "max_files_changed": 25,
    "blocked": [".github/workflows/", "secrets/", ".env"],
    "ai_actors": ["copilot", "codex", "antigravity", "claude", "bot", "agent"],
    "ignore": [],                      # paths Shield will not scan (e.g. test fixtures, detector corpora)
    "preserve_comments": True,         # never rewrite a function that contains comments
    "fuzz": True,                      # differential fuzzing of every rewritten function
    "ml_guard": True,                  # learned prompt-injection classifier on top of the rules
    "dependency_guard": True,          # typosquat / dependency-confusion checks
}

# key -> (accepted python types, human description)
SCHEMA = {
    "version": ((int,), "an integer"),
    "optimize": ((str,), "'required' or 'off'"),
    "approval": ((str,), "'human'"),
    "ai_changes": ((str,), "'log_all'"),
    "max_complexity": ((int,), "an integer >= 1"),
    "max_depth": ((int,), "an integer >= 1"),
    "max_cognitive": ((int,), "an integer >= 0 (0 disables)"),
    "max_files_changed": ((int,), "an integer >= 1"),
    "blocked": ((list,), "a list of path patterns"),
    "ai_actors": ((list,), "a list of name fragments"),
    "ignore": ((list,), "a list of path patterns"),
    "preserve_comments": ((bool,), "true or false"),
    "fuzz": ((bool,), "true or false"),
    "ml_guard": ((bool,), "true or false"),
    "dependency_guard": ((bool,), "true or false"),
}
ENUMS = {"optimize": {"required", "off"}, "approval": {"human"}, "ai_changes": {"log_all"}}
MINS = {"max_complexity": 1, "max_depth": 1, "max_cognitive": 0, "max_files_changed": 1}


def validate(raw):
    """Return (clean_policy, problems). problems: [{level: 'error'|'warn', key, msg}]."""
    problems, pol = [], dict(DEFAULT)
    if raw is None:
        return pol, problems
    if not isinstance(raw, dict):
        return pol, [dict(level="error", key="*", msg="policy must be a YAML mapping (key: value)")]
    for k, v in raw.items():
        if k not in SCHEMA:
            problems.append(dict(level="warn", key=k, msg=f"unknown key '{k}' (ignored)")); continue
        types, desc = SCHEMA[k]
        if isinstance(v, bool) and bool not in types or not isinstance(v, types):
            problems.append(dict(level="error", key=k, msg=f"'{k}' must be {desc}")); continue
        if k in ENUMS and v not in ENUMS[k]:
            problems.append(dict(level="error", key=k, msg=f"'{k}' must be {desc}")); continue
        if k in MINS and v < MINS[k]:
            problems.append(dict(level="error", key=k, msg=f"'{k}' must be {desc}")); continue
        if isinstance(v, list) and not all(isinstance(x, str) for x in v):
            problems.append(dict(level="error", key=k, msg=f"every entry of '{k}' must be a string")); continue
        pol[k] = v
    return pol, problems


def parse(text):
    """Parse policy text. Raises ValueError with a readable message on YAML errors."""
    try:
        raw = yaml.safe_load(text) if text.strip() else None
    except yaml.YAMLError as e:
        mark = getattr(e, "problem_mark", None)
        where = f" (line {mark.line + 1})" if mark else ""
        raise ValueError(f"invalid YAML{where}: {getattr(e, 'problem', e)}")
    return validate(raw)


def load(path="repobrain.yml"):
    p = pathlib.Path(path)
    pol, _ = parse(p.read_text()) if p.exists() else (dict(DEFAULT), [])
    return pol
