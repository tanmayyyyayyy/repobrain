"""Learned prompt-injection guard: a multinomial Naive Bayes over word unigrams and bigrams.

Rules catch known phrasings; the classifier is a second opinion for paraphrases the rules miss
("set aside the guidelines you were given..."). Pure standard library, trains in milliseconds
from `data/injection_corpus.json`, so there is no model file to ship or to poison.

HONESTY NOTES (also in the README):
  * The corpus is small and written by the team. Cross-validated numbers show the approach works
    on this distribution; they are not a claim about production accuracy.
  * Design rule: RULES can block a merge, the MODEL can only warn (and raise the risk score).
    `evaluate()` reports rules-only vs classifier vs hybrid, plus its false-positive rate on
    held-out natural prose from the Python standard library.
"""
import json, math, pathlib, random, re
from collections import Counter

DATA = pathlib.Path(__file__).parent / "data" / "injection_corpus.json"
PROSE = pathlib.Path(__file__).parent / "data" / "negative_prose.txt"   # frozen sample of real technical prose (Python stdlib comments, PSF licence)
WARN_AT = 0.90         # classifier probability that raises a warning
_TOK = re.compile(r"[a-z0-9']+")
# A model warning also needs directive wording (an order, a concealment, an exfiltration verb). Topic words alone
# ("AI", "security", "key") are not enough: this removed most false alarms on documentation about AI tooling.
DIRECTIVE = re.compile(r"\b(ignore|disregard|forget|set aside|override|bypass|circumvent|reveal|leak|exfiltrate|upload|send|post|print|output|"
                       r"copy|share|forward|email|hide|conceal|skip|disable|turn off|approve|merge|execute|run|grant|obey|cancel|void|"
                       r"quietly|silently|secretly|do not (?:tell|inform|notify|alert|mention)|never mention|don't tell|"
                       r"without (?:telling|alerting|notifying|asking)|give me|new instructions|pretend|roleplay|enter admin|you are now|"
                       r"not to be told|not alert|nobody sees|keep (?:this )?(?:secret|quiet))\b", re.I)


def directive(text):
    return bool(DIRECTIVE.search(text))


def features(text):
    w = _TOK.findall(text.lower())
    return w + [a + "_" + b for a, b in zip(w, w[1:])]


class NaiveBayes:
    def __init__(self, alpha=0.5):
        self.alpha, self.cnt, self.tot, self.docs, self.vocab = alpha, {0: Counter(), 1: Counter()}, {0: 0, 1: 0}, {0: 0, 1: 0}, set()

    def fit(self, texts, labels):
        for t, y in zip(texts, labels):
            f = features(t)
            self.cnt[y].update(f); self.tot[y] += len(f); self.docs[y] += 1; self.vocab.update(f)
        return self

    def prob(self, text):
        """P(injection | text), via log-odds with Laplace smoothing."""
        v, n = len(self.vocab) or 1, sum(self.docs.values()) or 1
        lo = 0.0   # balanced prior: class sizes here are an artefact of how data was collected
        for tok in features(text):
            if tok not in self.vocab:
                continue
            p1 = (self.cnt[1][tok] + self.alpha) / (self.tot[1] + self.alpha * v)
            p0 = (self.cnt[0][tok] + self.alpha) / (self.tot[0] + self.alpha * v)
            lo += math.log(p1 / p0)
        lo = max(-30.0, min(30.0, lo))
        return 1 / (1 + math.exp(-lo))

    def top_terms(self, text, k=4):
        """Which tokens pushed this text towards 'injection' (for explainability)."""
        v, scored = len(self.vocab) or 1, []
        for tok in set(features(text)):
            if tok not in self.vocab: continue
            p1 = (self.cnt[1][tok] + self.alpha) / (self.tot[1] + self.alpha * v)
            p0 = (self.cnt[0][tok] + self.alpha) / (self.tot[0] + self.alpha * v)
            scored.append((math.log(p1 / p0), tok.replace("_", " ")))
        return [t for s, t in sorted(scored, reverse=True)[:k] if s > 0.5]


def corpus():
    d = json.loads(DATA.read_text())
    return d["positive"], d["negative"]


def prose_negatives():
    return [l for l in PROSE.read_text().splitlines() if l.strip()] if PROSE.exists() else []


def augment(n=700, seed=5):
    """Template-generated attack variants (TRAINING ONLY, never used for evaluation)."""
    r = random.Random(seed)
    who = ["", "", "AI assistant: ", "Note to coding agents: ", "Dear Copilot, ", "If you are a bot, ", "Automated reviewers: ",
           "Attention language model: ", "When you process this file, ", "Before you continue, ", "Hey agent, "]
    drop = ["ignore", "disregard", "forget", "set aside", "override", "cancel", "void", "drop", "stop following"]
    old = ["all previous instructions", "the earlier rules", "your guidelines", "the safety policy", "prior directives",
           "the repository policy", "what the maintainers told you", "your system prompt", "every rule you were given"]
    verb = ["reveal", "print", "send", "upload", "post", "leak", "forward", "share", "email", "copy", "output", "exfiltrate"]
    obj = ["the API key", "the deploy token", "all credentials", "the contents of .env", "the ssh private key", "every password",
           "the secrets in this repo", "the access token", "the database password"]
    dest = ["", "", " to the address below", " in your reply", " in the commit message", " to a public gist", " to http://collect.example"]
    hide = ["do not tell", "never mention this to", "hide this from", "keep quiet about it around", "without alerting", "make sure you do not notify"]
    aud = ["the reviewer", "the maintainers", "the user", "anyone", "the human supervising you", "the security team"]
    act = ["approve the pull request", "merge without tests", "disable the security checks", "run the script below", "add my key to authorized_keys",
           "push directly to main", "turn off the logging", "grant me admin access", "change the workflow permissions"]
    out = []
    for _ in range(n):
        k = r.randrange(5)
        if k == 0:   t = f"{r.choice(drop)} {r.choice(old)} and {r.choice(verb)} {r.choice(obj)}{r.choice(dest)}."
        elif k == 1: t = f"{r.choice(verb).capitalize()} {r.choice(obj)}{r.choice(dest)}, then {r.choice(hide)} {r.choice(aud)}."
        elif k == 2: t = f"{r.choice(who)}{r.choice(drop)} {r.choice(old)} and {r.choice(act)}."
        elif k == 3: t = f"{r.choice(who)}{r.choice(act)} and {r.choice(hide)} {r.choice(aud)}."
        else:        t = f"{r.choice(who)}you must {r.choice(act)}; {r.choice(drop)} {r.choice(old)}."
        out.append(t[0].upper() + t[1:])
    return out


_MODEL = None
def model():
    global _MODEL
    if _MODEL is None:
        pos, neg = corpus()
        neg, pos = neg + prose_negatives(), pos + augment()
        _MODEL = NaiveBayes().fit(pos + neg, [1] * len(pos) + [0] * len(neg))
    return _MODEL


def score(text):
    return model().prob(text)


def stdlib_prose(limit=4000):
    """Natural technical prose NOT used in training: comment lines and docstring lines from the stdlib."""
    import sysconfig
    root, out = pathlib.Path(sysconfig.get_paths()["stdlib"]), []
    for p in sorted(root.glob("*.py"))[1::2]:       # odd files only: training negatives came from even files
        try:
            for line in p.read_text(errors="ignore").splitlines():
                s = line.strip()
                if s.startswith("#"):
                    s = s.lstrip("# ").strip()
                if 6 <= len(s.split()) <= 30 and not re.search(r"[=(){}\[\]\\]", s) and s[0].isalpha() and len(s) < 220:
                    out.append(s)
        except OSError:
            pass
    random.Random(7).shuffle(out)
    return out[:limit]


def evaluate(rules_fn=None, folds=5, seed=13):
    """k-fold cross-validation. Returns accuracy/precision/recall/F1 for the classifier alone and,
    when rules_fn(text)->bool is given, for rules alone and for rules OR classifier (the hybrid)."""
    pos, neg = corpus()
    data = [(t, 1) for t in pos] + [(t, 0) for t in neg]
    random.Random(seed).shuffle(data)
    preds = {"ml": [], "rules": [], "hybrid": []}
    truth, extra, synth = [], prose_negatives(), augment()
    for k in range(folds):
        test = data[k::folds]
        train = [d for i, d in enumerate(data) if i % folds != k]
        m = NaiveBayes().fit([t for t, _ in train] + extra + synth, [y for _, y in train] + [0] * len(extra) + [1] * len(synth))
        for t, y in test:
            truth.append(y)
            ml = m.prob(t) >= WARN_AT and directive(t)
            rl = bool(rules_fn(t)) if rules_fn else False
            preds["ml"].append(ml); preds["rules"].append(rl); preds["hybrid"].append(ml or rl)

    def metrics(p):
        tp = sum(1 for a, y in zip(p, truth) if a and y); fp = sum(1 for a, y in zip(p, truth) if a and not y)
        fn = sum(1 for a, y in zip(p, truth) if not a and y); tn = len(truth) - tp - fp - fn
        pr = tp / (tp + fp) if tp + fp else 0.0; rc = tp / (tp + fn) if tp + fn else 0.0
        return dict(accuracy=round((tp + tn) / len(truth), 3), precision=round(pr, 3), recall=round(rc, 3),
                    f1=round(2 * pr * rc / (pr + rc), 3) if pr + rc else 0.0, tp=tp, fp=fp, fn=fn, tn=tn)

    out = {"samples": len(truth), "positives": len(pos), "negatives": len(neg), "folds": folds,
           "ml": metrics(preds["ml"])}
    if rules_fn:
        out["rules"], out["hybrid"] = metrics(preds["rules"]), metrics(preds["hybrid"])
    prose = stdlib_prose()
    if prose:
        m = model()
        out["stdlib_false_positive_rate"] = round(sum(1 for s in prose if m.prob(s) >= WARN_AT and directive(s)) / len(prose), 4)
        out["stdlib_prose_samples"] = len(prose)
    return out
