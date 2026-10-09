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
