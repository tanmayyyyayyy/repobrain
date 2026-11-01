"""Runs in a SUBPROCESS (resource-limited). Reads a JSON job on stdin, writes a JSON result on stdout.
Executes only pure-looking function definitions, with a restricted builtins table."""
import builtins, copy, json, random, signal, sys

SAFE = {n: getattr(builtins, n) for n in
        "abs all any bool dict divmod enumerate filter float int isinstance len list map max min pow range reversed round set sorted str sum tuple zip repr ord chr TypeError ValueError KeyError IndexError ZeroDivisionError AttributeError Exception".split()}
BOOLISH = {"flag", "express", "member", "enabled", "active", "verbose", "strict", "debug", "ok", "valid", "premium", "vip", "paid", "admin"}
NUMISH = {"n", "x", "y", "i", "j", "k", "age", "count", "qty", "quantity", "price", "total", "amount", "weight", "value", "size", "num", "limit", "score", "rate", "level", "index", "idx", "width", "height", "a", "b", "c", "distance", "days", "hours", "balance", "stock"}
STRISH = {"s", "text", "name", "email", "country", "code", "key", "msg", "message", "path", "word", "label", "title", "kind", "type", "mode", "status", "currency", "tier", "region", "city", "category"}
LISTISH = {"items", "xs", "users", "data", "values", "rows", "lst", "lines", "words", "records", "nums", "numbers", "entries", "orders", "products", "names", "emails", "scores"}
DICTISH = {"d", "config", "params", "options", "mapping", "user", "item", "row", "record", "person", "order", "product", "customer"}


class TO(Exception): pass
def _alarm(*a): raise TO()


def make_gen(rng, consts):
    nums = [0, 1, -1, 2, 3, 4, 5, 6, 10, 17, 18, 19, 50, 99, 100, 101, 150, 200, 0.5, -0.5, 1.5, 4.999, 5.0, 1e6]
    for c in consts["nums"]:
        nums += [c, c - 1, c + 1] + ([c + 0.5, c - 0.5] if isinstance(c, (int, float)) else [])
    strs = ["", "a", "A", " ", "IN", "US", "x@y.com", "bad", "none", " A@X.com ", "@"] + consts["strs"] + [s.upper() for s in consts["strs"][:3]]
    keys = consts["strs"] or ["k"]

    def num(): return rng.choice(nums)
    def st(): return rng.choice(strs)
    def mixed():
        return rng.choice([num, st, lambda: rng.choice([True, False]), lambda: None, lambda: [], lambda: {}, lambda: [1, 2], lambda: "0"])()
    def dct():
        return {k: (num() if rng.random() < .5 else st()) for k in rng.sample(keys, min(len(keys), rng.randint(0, 3)))}
    def lst():
        out = []
        for _ in range(rng.randint(0, 4)):
            out.append(rng.choice([num, st, dct, lambda: None, dct, dct])())
        return out

    def gen(p):
        name, default = p["name"], p.get("default")
        if rng.random() < .08: return mixed()
        low = name.lower()
        if low in BOOLISH or low.startswith(("is_", "has_", "can_", "should_")) or isinstance(default, bool):
            return rng.choice([True, False, 0, 1, None])
        if low in LISTISH or isinstance(default, list): return lst()
        if low in DICTISH or isinstance(default, dict): return dct() if rng.random() > .1 else None
        if low in STRISH or isinstance(default, str): return st()
        if low in NUMISH or isinstance(default, (int, float)): return num() if rng.random() > .05 else None
        return mixed()
    return gen


def outcome(fn, args):
    signal.setitimer(signal.ITIMER_REAL, 0.25)
    try:
        r = fn(*args)
        return ("ok", repr(r), repr(args))
    except TO:
        return ("timeout",)
    except BaseException as e:
        return ("exc", type(e).__name__, repr(args))
    finally:
        signal.setitimer(signal.ITIMER_REAL, 0)


def main():
    job = json.load(sys.stdin)
    signal.signal(signal.SIGALRM, _alarm)
    ns = []
    for key in ("old", "new"):
        g = {"__builtins__": dict(SAFE)}
        exec(compile(job[key], key, "exec"), g)
        ns.append(g)
    res = {}
    for t in job["targets"]:
        rng = random.Random(job["seed"] + sum(map(ord, t["name"])))
        gen, div, ex = make_gen(rng, t["consts"]), 0, None
        for _ in range(job["n"]):
            args = [gen(p) for p in t["params"]]
            a, b = outcome(ns[0][t["name"]], copy.deepcopy(args)), outcome(ns[1][t["name"]], copy.deepcopy(args))
            if a != b:
                div += 1
                ex = ex or {"input": repr(args)[:160], "old": repr(a)[:100], "new": repr(b)[:100]}
        res[t["name"]] = {"checked": job["n"], "diverged": div, "example": ex}
    json.dump(res, sys.stdout)

main()
