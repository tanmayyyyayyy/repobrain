"""Client-ready HTML audit report: who did what, what was allowed or blocked, and whether the log is intact."""
import html, json, pathlib
from . import audit


def build(home):
    home = pathlib.Path(home)
    rows, chain = audit.read(home), audit.verify_detail(home)
    status = ("<b style='color:#2e7d32'>Chain verified</b>" + (" (HMAC-signed)" if chain["signed"] else "")) if chain["ok"] else \
        f"<b style='color:#c62828'>TAMPERING DETECTED at record #{chain['bad_index']}: {html.escape(chain['reason'])}</b>"
    body = "".join(
        f"<tr><td>{r.get('seq', '')}</td><td>{html.escape(r['ts'])}</td><td>{html.escape(r['event'])}</td><td class='d-{html.escape(r['decision'].split('+')[0])}'>{html.escape(r['decision'])}</td>"
        f"<td>{html.escape(r['actor'])}</td><td><code>{html.escape(json.dumps(r['detail']))[:300]}</code></td><td><code>{r['hash'][:10]}</code></td></tr>"
        for r in reversed(rows))
    page = f"""<!doctype html><meta charset=utf-8><title>RepoBrain audit report</title>
<style>body{{font:14px system-ui;margin:40px auto;max-width:1000px;color:#16161d}}table{{border-collapse:collapse;width:100%}}
td,th{{border-bottom:1px solid #e3e3ea;padding:6px 8px;text-align:left;vertical-align:top}}th{{background:#f4f2fb}}code{{font-size:12px}}
.d-block,.d-rejected,.d-invalidated{{color:#c62828;font-weight:600}}.d-approved,.d-allow{{color:#2e7d32;font-weight:600}}</style>
<h1>RepoBrain audit report</h1><p>{status}. {len(rows)} records. Each record commits to the previous one with SHA-256.</p>
<table><tr><th>#</th><th>Time (UTC)</th><th>Event</th><th>Decision</th><th>Actor</th><th>Detail</th><th>Hash</th></tr>{body}</table>"""
    out = home / "report.html"
    home.mkdir(parents=True, exist_ok=True)
    out.write_text(page)
    return out
