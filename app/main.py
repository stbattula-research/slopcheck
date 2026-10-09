"""SlopCheck — local-first AI-slop detector for UI code.

Upload or paste HTML/CSS/JS, get a slop score with concrete findings and
human-grade fix suggestions. Auto-fix applies the safe ones.
"""

from __future__ import annotations

import html as html_lib
import json
from dataclasses import asdict

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


def _run_analysis(name: str, kind: str, code: str) -> int:
    analysis = analyzer.analyze(code)
    findings = [_finding_dict(f) for f in analysis.findings]
    return db.save_check(
        name=name, kind=kind, score=analysis.score,
        grade=analysis.grade, findings=findings, code=code,
    )


@app.post("/check")
async def check(
    request: Request,
    file: UploadFile | None = File(default=None),
    pasted: str = Form(default=""),
    filename: str = Form(default=""),
):
    code = ""
    name = "pasted snippet"
    kind = "paste"
    if file is not None and file.filename:
        raw = await file.read()
        code = raw[:MAX_UPLOAD_BYTES].decode("utf-8", errors="replace")
        name = file.filename
        kind = "upload"
    elif pasted.strip():
        code = pasted[:MAX_UPLOAD_BYTES]
        name = filename.strip() or "pasted snippet"
    if not code.strip():
        return templates.TemplateResponse(
            request=request, name="index.html",
            context={"recent": db.list_checks(limit=6),
             "stats": db.stats(), "error": "Upload a file or paste some code first."},
            status_code=400,
        )
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
    if fixed and auto_ids:
        fixed_code, applied = analyzer.apply_fixes(row["code"], auto_ids)
    # severity ordering for display
    order = {"high": 0, "medium": 1, "low": 2}
    findings.sort(key=lambda f: (order.get(f["severity"], 3), -f["weight"]))
    return templates.TemplateResponse(
        request=request, name="results.html",
        context={
            "request": request,
            "check": row,
            "findings": findings,
            "auto_ids": auto_ids,
            "fixed_code": fixed_code,
            "applied": applied,
            "show_fixed": bool(fixed),
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
    return {
        "score": analysis.score,
        "grade": analysis.grade,
        "findings": [_finding_dict(f) for f in analysis.findings],
        "auto_fixable": analyzer.auto_fixable_ids(analysis),
    }


@app.post("/api/fix")
async def api_fix(payload: dict):
    code = str(payload.get("code", ""))[:MAX_UPLOAD_BYTES]
    marker_ids = list(payload.get("marker_ids", []))
    fixed, applied = analyzer.apply_fixes(code, marker_ids)
    return {"fixed_code": fixed, "applied": applied}
