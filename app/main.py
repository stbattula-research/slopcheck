"""SlopCheck — local-first AI-slop detector for UI code.

Upload or paste HTML/CSS/JS, get a slop score with concrete findings and
human-grade fix suggestions. Auto-fix applies the safe ones.
"""

from __future__ import annotations

import html as html_lib
import json
from dataclasses import asdict
from urllib.parse import urlparse

import httpx
from fastapi import FastAPI, File, Form, Request, UploadFile
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from . import analyzer, db

app = FastAPI(title="SlopCheck")
app.mount("/static", StaticFiles(directory="app/static"), name="static")
templates = Jinja2Templates(directory="app/templates")

db.init_db()

MAX_UPLOAD_BYTES = 500_000
ALLOWED_EXTS = {".html", ".htm", ".css", ".js", ".jsx", ".tsx", ".vue"}


def _finding_dict(f: analyzer.Finding) -> dict:
    return asdict(f)


@app.get("/", response_class=HTMLResponse)
def index(request: Request):
    recent = db.list_checks(limit=6)
    s = db.stats()
    return templates.TemplateResponse(
        request=request, name="index.html",
        context={"recent": recent, "stats": s},
    )


def _run_analysis(name: str, kind: str, code: str) -> int | None:
    """Run analysis and save. Returns check id, or None if insufficient input."""
    analysis = analyzer.analyze(code)
    if analysis.insufficient:
        return None
    findings = [_finding_dict(f) for f in analysis.findings]
    return db.save_check(
        name=name, kind=kind, score=analysis.score,
        grade=analysis.grade, findings=findings, code=code,
    )


def _analysis_payload(analysis: analyzer.Analysis) -> dict:
    return {
        "score": analysis.score,
        "grade": analysis.grade,
        "insufficient": analysis.insufficient,
        "summary": analysis.summary,
        "categories": analysis.category_scores,
        "findings": [_finding_dict(f) for f in analysis.findings],
        "auto_fixable": analyzer.auto_fixable_ids(analysis),
    }


def fetch_url(url: str) -> tuple[str, str]:
    """Fetch a page's HTML. Returns (final_url, html). Raises ValueError on problems."""
    url = url.strip()
    if not url:
        raise ValueError("Enter a URL first.")
    if "://" not in url:
        url = "https://" + url
    parsed = urlparse(url)
    if parsed.scheme not in ("http", "https") or not parsed.netloc:
        raise ValueError("That doesn't look like a valid http(s) URL.")
    try:
        # trust_env=False: sandbox proxy vars break localhost fetches and
        # aren't relevant for a local-first tool fetching public pages.
        resp = httpx.get(
            url,
            timeout=15.0,
            follow_redirects=True,
            trust_env=False,
            headers={"User-Agent": "SlopCheck/1.0 (local UI analyzer)"},
        )
        resp.raise_for_status()
    except httpx.HTTPError as exc:
        raise ValueError(f"Couldn't fetch that page: {exc}") from exc
    content_type = resp.headers.get("content-type", "")
    if "html" not in content_type and "text" not in content_type:
        raise ValueError(f"That URL returned {content_type or 'an unknown type'} — SlopCheck needs an HTML page.")
    html = resp.text[:MAX_UPLOAD_BYTES]
    if not html.strip():
        raise ValueError("That page came back empty.")
    return str(resp.url), html


@app.post("/check")
async def check(
    request: Request,
    file: UploadFile | None = File(default=None),
    pasted: str = Form(default=""),
    filename: str = Form(default=""),
    page_url: str = Form(default=""),
):
    def _index(error: str):
        return templates.TemplateResponse(
            request=request, name="index.html",
            context={"recent": db.list_checks(limit=6),
                     "stats": db.stats(), "error": error},
            status_code=400,
        )

    code = ""
    name = "pasted snippet"
    kind = "paste"
    if file is not None and file.filename:
        raw = await file.read()
        code = raw[:MAX_UPLOAD_BYTES].decode("utf-8", errors="replace")
        name = file.filename
        kind = "upload"
    elif page_url.strip():
        try:
            final_url, code = fetch_url(page_url)
        except ValueError as exc:
            return _index(str(exc))
        name = final_url
        kind = "url"
    elif pasted.strip():
        code = pasted[:MAX_UPLOAD_BYTES]
        name = filename.strip() or "pasted snippet"
    if not code.strip():
        return _index("Upload a file, paste some code, or enter a page URL first.")
    # Honesty guardrail: refuse to score tiny snippets.
    probe = analyzer.analyze(code)
    if probe.insufficient:
        return _index(probe.summary)
    check_id = _run_analysis(name, kind, code)
    return RedirectResponse(f"/results/{check_id}", status_code=303)


@app.get("/results/{check_id}", response_class=HTMLResponse)
def results(request: Request, check_id: int, fixed: int = 0):
    row = db.get_check(check_id)
    if not row:
        return HTMLResponse("Check not found.", status_code=404)
    findings: list[dict] = json.loads(row["findings_json"])
    auto_ids = [f["marker_id"] for f in findings if f["auto_fixable"]]
    fixed_code = None
    applied: list[str] = []
    fixed_score = None
    score_delta = None
    if fixed and auto_ids:
        fixed_code, applied = analyzer.apply_fixes(row["code"], auto_ids)
        if applied:
            re_analysis = analyzer.analyze(fixed_code)
            if not re_analysis.insufficient:
                fixed_score = re_analysis.score
                score_delta = fixed_score - row["score"]
    # severity ordering for display
    order = {"high": 0, "medium": 1, "low": 2}
    findings.sort(key=lambda f: (order.get(f["severity"], 3), -f["weight"]))
    # category sub-scores + executive summary (recomputed for stored checks)
    analysis = analyzer.analyze(row["code"])
    category_scores = analysis.category_scores
    summary = analysis.summary
    # code viewer: line numbers + flagged lines (capped at 1000 lines)
    code_lines = row["code"].splitlines()[:1000]
    flagged: dict[int, list[str]] = {}
    for f in findings:
        for ln in f.get("lines", []) or []:
            if 1 <= ln <= len(code_lines):
                flagged.setdefault(ln, []).append(f["name"])
    return templates.TemplateResponse(
        request=request, name="results.html",
        context={
            "check": row,
            "findings": findings,
            "auto_ids": auto_ids,
            "fixed_code": fixed_code,
            "applied": applied,
            "show_fixed": bool(fixed),
            "fixed_score": fixed_score,
            "score_delta": score_delta,
            "category_scores": category_scores,
            "summary": summary,
            "code_lines": code_lines,
            "flagged": flagged,
            "code_truncated": len(row["code"].splitlines()) > 1000,
        },
    )


@app.get("/history", response_class=HTMLResponse)
def history(request: Request):
    return templates.TemplateResponse(
        request=request, name="history.html",
        context={"checks": db.list_checks(limit=100),
         "stats": db.stats()},
    )


# --- JSON API (for the future website / mobile app) --------------------------


@app.post("/api/check")
async def api_check(payload: dict):
    code = str(payload.get("code", ""))[:MAX_UPLOAD_BYTES]
    if not code.strip():
        return JSONResponse({"error": "code is required"}, status_code=400)
    analysis = analyzer.analyze(code)
    return _analysis_payload(analysis)


@app.post("/api/fix")
async def api_fix(payload: dict):
    code = str(payload.get("code", ""))[:MAX_UPLOAD_BYTES]
    marker_ids = list(payload.get("marker_ids", []))
    fixed, applied = analyzer.apply_fixes(code, marker_ids)
    return {"fixed_code": fixed, "applied": applied}


@app.post("/api/fetch")
async def api_fetch(payload: dict):
    """Fetch a URL's HTML and score it. Powers the future website/mobile app."""
    url = str(payload.get("url", ""))
    try:
        final_url, html = fetch_url(url)
    except ValueError as exc:
        return JSONResponse({"error": str(exc)}, status_code=400)
    analysis = analyzer.analyze(html)
    out = _analysis_payload(analysis)
    out["url"] = final_url
    return out


# --- Exportable reports -------------------------------------------------------


def _report_markdown(row: dict, findings: list[dict], summary: str,
                     category_scores: dict) -> str:
    lines = [
        f"# SlopCheck report — {row['name']}",
        "",
        f"**Score:** {row['score']}/100 — {row['grade']}",
        f"**Checked:** {row['created_at'][:16].replace('T', ' ')} ({row['kind']})",
        "",
        f"> {summary}",
        "",
        "## Category scores",
        "",
    ]
    for c, v in category_scores.items():
        lines.append(f"- {v['label']}: {v['score']}/{v['weight']}")
    lines += ["", "## Findings", ""]
    if not findings:
        lines.append("No slop patterns detected — human-grade.")
    for f in findings:
        lines.append(f"### [{f['severity'].upper()}] {f['name']} (−{f['weight']})")
        lines.append("")
        lines.append(f["description"])
        if f.get("excerpt"):
            lines.append("")
            lines.append(f"`{f['excerpt']}`")
        lines.append("")
        lines.append(f"**Fix:** {f['suggestion']}")
        lines.append("")
    lines += ["", "---",
              "Generated locally by SlopCheck. Findings are pattern matches, not proof of authorship."]
    return "\n".join(lines)


@app.get("/results/{check_id}/export.md")
def export_md(check_id: int):
    from fastapi.responses import PlainTextResponse
    row = db.get_check(check_id)
    if not row:
        return HTMLResponse("Check not found.", status_code=404)
    findings = json.loads(row["findings_json"])
    analysis = analyzer.analyze(row["code"])
    md = _report_markdown(row, findings, analysis.summary, analysis.category_scores)
    return PlainTextResponse(
        md,
        headers={"Content-Disposition": f"attachment; filename=slopcheck-{check_id}.md"},
    )


@app.get("/results/{check_id}/export.json")
def export_json(check_id: int):
    row = db.get_check(check_id)
    if not row:
        return HTMLResponse("Check not found.", status_code=404)
    findings = json.loads(row["findings_json"])
    analysis = analyzer.analyze(row["code"])
    payload = {
        "name": row["name"], "kind": row["kind"],
        "score": row["score"], "grade": row["grade"],
        "summary": analysis.summary,
        "categories": analysis.category_scores,
        "findings": findings,
        "created_at": row["created_at"],
    }
    return JSONResponse(
        payload,
        headers={"Content-Disposition": f"attachment; filename=slopcheck-{check_id}.json"},
    )
