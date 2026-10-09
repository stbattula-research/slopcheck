"""Tests for SlopCheck routes (uses a temp DB)."""

import os
import tempfile

import pytest
from fastapi.testclient import TestClient

_tmp = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
_tmp.close()
os.environ["SLOPCHECK_DB"] = _tmp.name

from app import db  # noqa: E402
from app.main import app  # noqa: E402

client = TestClient(app)

SLOPPY = """
<html><body>
<div style="background: linear-gradient(135deg, #667eea 0%, #764ba2 100%)">
<h1>Welcome to our revolutionary platform</h1>
<p>Lorem ipsum dolor sit amet. 🚀</p>
<p>Filler paragraph number 1 with ordinary words.</p>
<p>Filler paragraph number 2 with ordinary words.</p>
<p>Filler paragraph number 3 with ordinary words.</p>
<p>Filler paragraph number 4 with ordinary words.</p>
<p>Filler paragraph number 5 with ordinary words.</p>
<p>Filler paragraph number 6 with ordinary words.</p>
<p>Filler paragraph number 7 with ordinary words.</p>
<p>Filler paragraph number 8 with ordinary words.</p>
<p>Filler paragraph number 9 with ordinary words.</p>
</div></body></html>
"""


def test_index_loads():
    r = client.get("/")
    assert r.status_code == 200
    assert "SlopCheck" in r.text


def test_check_paste_flow():
    r = client.post("/check", data={"pasted": SLOPPY}, follow_redirects=False)
    assert r.status_code == 303
    loc = r.headers["location"]
    assert loc.startswith("/results/")
    page = client.get(loc)
    assert page.status_code == 200
    assert "slop score" in page.text
    assert "Signature AI purple gradient" in page.text


def test_check_empty_rejected():
    r = client.post("/check", data={"pasted": "   "})
    assert r.status_code == 400


def test_check_upload_flow():
    r = client.post(
        "/check",
        files={"file": ("page.html", SLOPPY.encode(), "text/html")},
        follow_redirects=False,
    )
    assert r.status_code == 303
    page = client.get(r.headers["location"])
    assert page.status_code == 200
    assert "page.html" in page.text


def test_results_autofix_view():
    r = client.post("/check", data={"pasted": SLOPPY}, follow_redirects=False)
    loc = r.headers["location"]
    page = client.get(loc + "?fixed=1")
    assert page.status_code == 200
    assert "Auto-fixed code" in page.text
    # the purple gradient should be gone from the fixed block
    assert "#667eea" not in page.text.split("Auto-fixed code")[1].split("</pre>")[0]


def test_history_lists_checks():
    client.post("/check", data={"pasted": "<p>hello</p>"})
    r = client.get("/history")
    assert r.status_code == 200
    assert "Check history" in r.text


def test_results_404():
    r = client.get("/results/999999")
    assert r.status_code == 404


def test_api_check():
    r = client.post("/api/check", json={"code": SLOPPY})
    assert r.status_code == 200
    body = r.json()
    assert body["score"] < 100
    assert "findings" in body
    assert isinstance(body["auto_fixable"], list)


def test_api_check_requires_code():
    r = client.post("/api/check", json={"code": "   "})
    assert r.status_code == 400


def test_api_fix():
    r = client.post(
        "/api/fix",
        json={"code": SLOPPY, "marker_ids": ["ai-purple-gradient"]},
    )
    assert r.status_code == 200
    body = r.json()
    assert "ai-purple-gradient" in body["applied"]
    assert "#667eea" not in body["fixed_code"]


# --- URL checks ---------------------------------------------------------------

import threading  # noqa: E402
from http.server import BaseHTTPRequestHandler, HTTPServer  # noqa: E402

from app.main import fetch_url  # noqa: E402


class _Handler(BaseHTTPRequestHandler):
    def do_GET(self):
        body = SLOPPY.encode()
        self.send_response(200)
        self.send_header("Content-Type", "text/html")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *args):
        pass


@pytest.fixture(scope="module")
def local_page():
    server = HTTPServer(("127.0.0.1", 0), _Handler)
    port = server.server_address[1]
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    yield f"http://127.0.0.1:{port}/"
    server.shutdown()


def test_fetch_url_rejects_bad_scheme():
    with pytest.raises(ValueError):
        fetch_url("ftp://example.com/x")


def test_fetch_url_rejects_empty():
    with pytest.raises(ValueError):
        fetch_url("   ")


def test_fetch_url_fetches_page(local_page):
    final_url, html = fetch_url(local_page)
    assert "667eea" in html
    assert final_url.startswith("http://127.0.0.1")


def test_check_url_flow(local_page):
    r = client.post("/check", data={"page_url": local_page}, follow_redirects=False)
    assert r.status_code == 303
    page = client.get(r.headers["location"])
    assert page.status_code == 200
    assert "Signature AI purple gradient" in page.text
    assert local_page.rstrip("/") in page.text or "127.0.0.1" in page.text


def test_check_bad_url_shows_error():
    r = client.post("/check", data={"page_url": "not a url at all !!!"})
    assert r.status_code == 400
    assert "URL" in r.text or "url" in r.text


# --- v2 routes ----------------------------------------------------------------

def test_results_shows_categories_and_summary():
    r = client.post("/check", data={"pasted": SLOPPY}, follow_redirects=False)
    page = client.get(r.headers["location"])
    assert page.status_code == 200
    assert "Visual design" in page.text
    assert "Code hygiene" in page.text
    assert "Summary" in page.text
    assert "honesty-note" in page.text or "doesn" in page.text


def test_results_shows_code_viewer_with_flagged_lines():
    r = client.post("/check", data={"pasted": SLOPPY}, follow_redirects=False)
    page = client.get(r.headers["location"])
    assert "Code under review" in page.text
    assert "flagged" in page.text


def test_insufficient_input_rejected_with_notice():
    r = client.post("/check", data={"pasted": "<p>tiny</p>"})
    assert r.status_code == 400
    assert "15" in r.text


def test_export_markdown():
    r = client.post("/check", data={"pasted": SLOPPY}, follow_redirects=False)
    check_id = r.headers["location"].rsplit("/", 1)[-1]
    e = client.get(f"/results/{check_id}/export.md")
    assert e.status_code == 200
    assert "SlopCheck report" in e.text
    assert "Category scores" in e.text
    assert "attachment" in e.headers.get("content-disposition", "")


def test_export_json():
    r = client.post("/check", data={"pasted": SLOPPY}, follow_redirects=False)
    check_id = r.headers["location"].rsplit("/", 1)[-1]
    e = client.get(f"/results/{check_id}/export.json")
    assert e.status_code == 200
    body = e.json()
    assert body["score"] < 100
    assert "categories" in body
    assert "summary" in body
    assert "attachment" in e.headers.get("content-disposition", "")


def test_export_404():
    assert client.get("/results/999999/export.md").status_code == 404
    assert client.get("/results/999999/export.json").status_code == 404


def test_rescore_delta_shown():
    r = client.post("/check", data={"pasted": SLOPPY}, follow_redirects=False)
    page = client.get(r.headers["location"] + "?fixed=1")
    assert page.status_code == 200
    assert "re-scored" in page.text


def test_api_check_includes_categories_and_summary():
    code = SLOPPY
    r = client.post("/api/check", json={"code": code})
    body = r.json()
    assert "categories" in body
    assert "summary" in body
    assert body["insufficient"] is False


def test_api_check_insufficient():
    r = client.post("/api/check", json={"code": "<p>x</p>"})
    body = r.json()
    assert body["insufficient"] is True


def test_api_fetch_url(local_page):
    r = client.post("/api/fetch", json={"url": local_page})
    assert r.status_code == 200
    body = r.json()
    assert body["score"] < 100
    assert body["url"].startswith("http://127.0.0.1")


def test_api_fetch_bad_url():
    r = client.post("/api/fetch", json={"url": "not a url!!!"})
    assert r.status_code == 400
