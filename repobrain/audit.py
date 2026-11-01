"""Append-only, hash-chained audit log.

Every record commits to the previous one (sha256), so editing history is detectable.
If REPOBRAIN_AUDIT_KEY is set, each record is also HMAC-signed: someone who rewrites the whole
chain still cannot forge valid signatures without the key.
"""
import hashlib, hmac, json, os, pathlib, time

GENESIS = "0" * 64


def _path(home): return pathlib.Path(home) / "audit.jsonl"
def _hash(rec): return hashlib.sha256(json.dumps(rec, sort_keys=True).encode()).hexdigest()
def _key(): return (os.environ.get("REPOBRAIN_AUDIT_KEY") or "").encode()
def _sig(h):
    return hmac.new(_key(), h.encode(), hashlib.sha256).hexdigest()


def read(home):
    p = _path(home)
    return [json.loads(l) for l in p.read_text().splitlines() if l.strip()] if p.exists() else []


def log(home, event, decision, actor, detail):
    rows = read(home)
    rec = {"seq": len(rows), "ts": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()), "event": event,
           "decision": decision, "actor": actor, "detail": detail,
           "prev": rows[-1]["hash"] if rows else GENESIS}
    rec["hash"] = _hash(rec)
    if _key():
        rec["sig"] = _sig(rec["hash"])
    pathlib.Path(home).mkdir(parents=True, exist_ok=True)
    with _path(home).open("a") as f:
        f.write(json.dumps(rec) + "\n")
    return rec


def verify_detail(home):
    """Return {ok, bad_index, reason, signed, records}. reason explains what failed."""
    prev, rows = GENESIS, read(home)
    signed = bool(_key())
    for i, r in enumerate(rows):
        r = dict(r)
        h, sig = r.pop("hash", None), r.pop("sig", None)
        if r.get("prev") != prev:
            return dict(ok=False, bad_index=i, reason="chain broken: record does not link to its predecessor", signed=signed, records=len(rows))
        if _hash(r) != h:
            return dict(ok=False, bad_index=i, reason="record contents do not match their hash (edited)", signed=signed, records=len(rows))
        if signed and (sig is None or not hmac.compare_digest(sig, _sig(h))):
            return dict(ok=False, bad_index=i, reason="signature missing or invalid (wrong key, or chain was rewritten)", signed=signed, records=len(rows))
        prev = h
    return dict(ok=True, bad_index=None, reason="", signed=signed, records=len(rows))


def verify(home):
    d = verify_detail(home)
    return d["ok"], d["bad_index"]
