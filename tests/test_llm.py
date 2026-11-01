"""AI-suggested rewrites must be verified like any other change. Uses a local mock OpenAI-compatible server."""
import json, pathlib, sys, threading
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))
from http.server import BaseHTTPRequestHandler, HTTPServer
from repobrain import optimizer, policy

SRC = '''def grade(score):
    if score >= 90:
        return "A"
    elif score >= 80:
        return "B"
    elif score >= 70:
        return "C"
    elif score >= 60:
        return "D"
    elif score >= 50:
        return "E"
    else:
        return "F"
'''
TEST = 'from calc import grade\n\ndef test_grade():\n    assert grade(95) == "A" and grade(80) == "B" and grade(10) == "F" and grade(60) == "D"\n'
GOOD = '''def grade(score):
    for limit, letter in ((90, "A"), (80, "B"), (70, "C"), (60, "D"), (50, "E")):
        if score >= limit:
            return letter
    return "F"
'''
BAD = GOOD.replace("(90, \"A\")", "(91, \"A\")")          # off-by-one: looks fine, silently changes behaviour
REPLY = {"text": GOOD}


class Mock(BaseHTTPRequestHandler):
    def do_POST(self):
        self.rfile.read(int(self.headers["content-length"]))
        body = json.dumps({"choices": [{"message": {"content": "```python\n" + REPLY["text"] + "```"}}]}).encode()
        self.send_response(200); self.send_header("content-type", "application/json"); self.send_header("content-length", str(len(body))); self.end_headers(); self.wfile.write(body)
    def log_message(self, *a): pass


def _setup(tmp_path, monkeypatch):
    srv = HTTPServer(("127.0.0.1", 0), Mock); threading.Thread(target=srv.serve_forever, daemon=True).start()
    monkeypatch.setenv("REPOBRAIN_LLM", "openai"); monkeypatch.setenv("REPOBRAIN_LLM_URL", f"http://127.0.0.1:{srv.server_address[1]}/v1")
    (tmp_path / "calc.py").write_text(SRC); (tmp_path / "test_calc.py").write_text(TEST)
    pol = dict(policy.DEFAULT); pol["max_complexity"] = 5
    return srv, pol


def test_ai_rewrite_that_changes_behaviour_is_rejected(tmp_path, monkeypatch):
    srv, pol = _setup(tmp_path, monkeypatch); REPLY["text"] = BAD
    r = optimizer.run(tmp_path, pol, tmp_path / "home", files=["calc.py"], ai=True)
    srv.shutdown()
    assert r["status"].startswith("rejected"), r["status"]
    assert (tmp_path / "calc.py").read_text() == SRC


def test_correct_ai_rewrite_is_accepted_and_verified(tmp_path, monkeypatch):
    srv, pol = _setup(tmp_path, monkeypatch); REPLY["text"] = GOOD
    r = optimizer.run(tmp_path, pol, tmp_path / "home", files=["calc.py"], ai=True)
    srv.shutdown()
    assert r["status"].startswith("proposed") and r["tests"]["ok"] is True
    assert r["fuzz"]["diverged"] == 0 and r["fuzz"]["inputs"] > 0
    assert r["files"][0]["after"]["max_complexity"] < r["files"][0]["before"]["max_complexity"]
