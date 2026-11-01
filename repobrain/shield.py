"""Shield: checks every change against the policy, whoever (or whatever) made it.

Layers: protected paths -> known secret formats + entropy -> prompt-injection rules + learned
classifier -> hidden Unicode (invisible instructions, Trojan Source) -> risky commands ->
dependency typosquats. Findings carry line numbers and REDACTED evidence (secrets are never echoed).
"""
import fnmatch, math, pathlib, re, subprocess, unicodedata
from . import deps, mlguard

SECRETS = [
    ("AWS access key", r"\b(?:AKIA|ASIA)[0-9A-Z]{16}\b"),
    ("API key / token", r"\bsk-(?:ant-|proj-|live)?[A-Za-z0-9_\-]{20,}|\bgh[pousr]_[A-Za-z0-9]{30,}"),
    ("Slack token", r"\bxox[abprs]-[A-Za-z0-9-]{10,}"),
    ("Google API key", r"\bAIza[0-9A-Za-z_\-]{35}\b"),
    ("Stripe live key", r"\b[sr]k_live_[0-9A-Za-z]{16,}"),
    ("private key block", r"-----BEGIN (?:RSA |EC |OPENSSH |DSA |PGP )?PRIVATE KEY"),
    ("JSON Web Token", r"\beyJ[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}"),
    ("hardcoded credential", r"(?i)\b(api[_-]?key|secret|token|passwd|password)\w*\s*[:=]\s*['\"][^'\"\s]{8,}['\"]"),
]
INJECTION = [
    r"ignore (all |any |the )?(previous|prior|above|earlier) (instructions|rules|directives|guidelines)",
    r"disregard .{0,40}(rules|instructions|polic|guidelines)",
    r"(?:^|[.!?]\s+|please\s+)(?:reveal|print|send|exfiltrate|leak|upload|output|post|copy)\b.{0,60}\b(secrets?|tokens?|api keys?|credentials?|passwords?|private keys?)\b",
    r"do not (tell|inform|notify|alert|mention)\b.{0,30}\b(user|human|reviewer|maintainers?|anyone)",
    r"you are now (in )?(developer|admin|unrestricted)",
    r"forget (everything|all|what) (you|that)",
    r"(new|updated) (system )?(instructions|prompt)\s*:",
    r"pretend (you are|to be) .{0,30}(unrestricted|no (safety )?rules)",
    r"\b(ai|assistant|agent|copilot|language model|bot)s?\b.{0,25}\b(must|should|please)\b.{0,40}\b(ignore|bypass|approve|execute|run|disable)",
    r"\b(override|bypass|circumvent|ignore) (the |all |any |your )?(safety|security|repository|repo|company)?\s?(policy|policies|guardrails)\b",
]
_INJ = [re.compile(r, re.I) for r in INJECTION]
RISKY = [
    ("pipes a download straight into a shell", r"(?:curl|wget)\b[^\n|]*\|\s*(?:sudo\s+)?(?:ba|z)?sh\b"),
    ("grants workflow write-all permissions", r"permissions:\s*write-all"),
    ("uses pull_request_target (runs untrusted code with secrets)", r"\bpull_request_target\b"),
    ("makes files world-writable", r"chmod\s+(?:-R\s+)?777"),
    ("executes obfuscated/decoded code", r"\b(?:exec|eval)\s*\(\s*(?:base64\.b64decode|bytes\.fromhex|codecs\.decode|atob)"),
]
HIDDEN = re.compile("[\u200b-\u200f\u202a-\u202e\u2060-\u2064\u2066-\u2069\ufeff\U000e0000-\U000e007f]")
SKIP_ENTROPY = re.compile(r"(?:\.lock|package-lock\.json|yarn\.lock|\.svg|\.min\.js|\.map)$")


# ---------- helpers ----------
def is_ai(actor, policy):
    return any(a in actor.lower() for a in policy["ai_actors"])


def _glob(path, pat):
    if pat.endswith("/"):
        return ("/" + path).find("/" + pat) != -1
    return fnmatch.fnmatch(path, pat) or fnmatch.fnmatch(pathlib.PurePath(path).name, pat)


def blocked_by(path, policy):
    return next((p for p in policy["blocked"] if _glob(path, p)), None)


def ignored(path, policy):
    return any(_glob(path, p) for p in policy.get("ignore", []))


def mask(s):
    return (s[:4] + "…[" + str(len(s)) + " chars redacted]") if len(s) > 8 else "[redacted]"


def entropy(s):
    return -sum(c / len(s) * math.log2(c / len(s)) for c in (s.count(ch) for ch in set(s)))


def injection_rule_hit(text):
    return any(rx.search(text) for rx in _INJ)


def _sentences(line):
    s = re.sub(r"^\s*(?:#+|//+|/\*+|\*+|<!--|-|>|\d+\.)\s*", "", line).replace("-->", "").strip()
    return [x for x in re.split(r"(?<=[.!?])\s+", s) if len(x.split()) >= 5]


def changed_files(base, root="."):
    out = subprocess.run(["git", "diff", "--name-only", f"{base}...HEAD"], cwd=root, capture_output=True, text=True)
    return [l for l in out.stdout.splitlines() if l.strip()]


def added_lines(root, base, path):
    """{lineno: text} of lines this branch added to `path` (whole file when it is new)."""
    out = subprocess.run(["git", "diff", "-U0", f"{base}...HEAD", "--", path], cwd=root, capture_output=True, text=True).stdout
    res, ln = {}, 0
    for l in out.splitlines():
        if l.startswith("@@"):
            m = re.search(r"\+(\d+)", l)
            ln = int(m.group(1)) if m else 0
        elif l.startswith("+") and not l.startswith("+++"):
            res[ln] = l[1:]; ln += 1
    return res


# ---------- content scanning ----------
def scan_text(path, text, policy, actor, only_lines=None):
    """Scan file content. only_lines: restrict findings to these 1-based line numbers (added lines)."""
    ai, out, lines = is_ai(actor, policy), [], text.split("\n")
    want = lambda n: only_lines is None or n in only_lines
    add = lambda sev, rule, ln, msg, ev="", **kw: out.append(dict(severity=sev, rule=rule, file=path, line=ln, msg=msg, evidence=ev, **kw))
    seen = set()

    for i, line in enumerate(lines, 1):
        if not want(i) or len(line) > 2000:
            continue
        for name, rx in SECRETS:                      # known formats
            m = re.search(rx, line)
            if m and ("secret", i) not in seen:
                seen.add(("secret", i)); add("block", "secret", i, f"Possible {name} committed", mask(m.group(0)))
                break
        if ("secret", i) not in seen and not SKIP_ENTROPY.search(path):   # entropy fallback
            for m in re.finditer(r"['\"]([A-Za-z0-9+/_=\-]{24,})['\"]", line):
                tok = m.group(1)
                if entropy(tok) >= 4.2 and re.search(r"\d", tok) and re.search(r"[A-Za-z]", tok) and not re.fullmatch(r"[0-9a-f]{32,64}", tok):
                    add("block" if ai else "warn", "high-entropy-string", i, "High-entropy string that looks like a secret", mask(tok)); break
        if HIDDEN.search(line) and not (i == 1 and line.startswith("\ufeff") and not HIDDEN.search(line[1:])):
            chars = sorted({unicodedata.name(c, f"U+{ord(c):04X}") for c in HIDDEN.findall(line)})[:3]
            add("block", "hidden-unicode", i, "Invisible/bidirectional Unicode characters (hidden instructions or Trojan Source)", ", ".join(chars).lower())
        for desc, rx in RISKY:
            if re.search(rx, line):
                add("block" if ai else "warn", "risky-command", i, f"Change {desc}", line.strip()[:90]); break

    # prompt injection: rules on each line, plus a 2-line window for sentences wrapped across lines
    flagged = set()
    for i, line in enumerate(lines, 1):
        if not want(i) or len(line) > 4000:
            continue
        nxt = lines[i] if i < len(lines) else ""
        single = injection_rule_hit(line)
        if single or (injection_rule_hit(line + " " + nxt) and not injection_rule_hit(nxt)):
            flagged.add(i)
            hid = "<!--" in line or (i > 1 and "<!--" in lines[i - 2] and "-->" not in lines[i - 2])
            add("block", "prompt-injection", i, "Text that tries to instruct AI agents to bypass rules or leak data"
                + (" (hidden in an HTML comment)" if hid else ""), re.sub(r"\s+", " ", line.strip())[:90], source="rules")
    if policy.get("ml_guard", True):
        for i, line in enumerate(lines, 1):
            if not want(i) or i in flagged or len(line) > 2000:
                continue
            best = 0.0
            for s in _sentences(line):
                if len(re.findall(r"[A-Za-z ,']", s)) / len(s) < 0.85 or not mlguard.directive(s):
                    continue
                best = max(best, mlguard.score(s))
            if best >= mlguard.WARN_AT:
                add("warn", "prompt-injection", i, f"Learned classifier: wording resembles an instruction aimed at AI agents (p={best:.2f})",
                    re.sub(r"\s+", " ", line.strip())[:90], source="model", score=round(best, 3),
                    terms=mlguard.model().top_terms(line))
    return out


def check(root, files, policy, actor, added=None, base=None):
    """Check `files` (paths relative to root). `added`: {path: {lineno: text}} limits content scans to new lines."""
    findings, ai = [], is_ai(actor, policy)
    if len(files) > policy["max_files_changed"]:
        findings.append(dict(severity="warn", rule="large-change", file="*", line=0, evidence="",
                             msg=f"{len(files)} files changed (limit {policy['max_files_changed']})"))
    for path in files:
        if ignored(path, policy):
            continue
        hit = blocked_by(path, policy)
        if hit:
            findings.append(dict(severity="block" if ai else "warn", rule="blocked-path", file=path, line=0, evidence=hit,
                                 msg=f"{'AI actor' if ai else 'Change'} touches protected path '{hit}'"))
        fp = pathlib.Path(root) / path
        if not fp.is_file() or fp.stat().st_size > 1_000_000:
            continue
        try:
            text = fp.read_text(errors="ignore")
        except OSError:
            continue
        only = set(added[path]) if added and path in added else None
        findings += scan_text(path, text, policy, actor, only)
        if policy.get("dependency_guard", True) and deps.is_manifest(path):
            ls = [(n, t) for n, t in enumerate(text.split("\n"), 1) if only is None or n in only]
            for d in deps.check_added(path, ls, policy):
                findings.append(dict(severity="block" if ai else "warn", rule="dependency-risk", file=path, line=d["line"],
                                     msg=d["msg"], evidence=d["evidence"], kind=d["kind"]))
    return findings
