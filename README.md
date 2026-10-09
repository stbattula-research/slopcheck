# SlopCheck ✨

**Is this AI slop?** Drop in HTML, CSS, or JS and get a slop score with
concrete findings — every flag comes with a human-grade fix suggestion.

SlopCheck is a local-first web app (FastAPI + SQLite, server-side Jinja UI).
Your code never leaves your machine. It also ships a JSON API
(`POST /api/check`, `POST /api/fix`) so a future hosted website or mobile
app can reuse the same engine.

## How it works

No ML, no API calls, no black box. The analyzer runs ~15 deterministic
checks against known AI-design fingerprints:

| Check | Example |
|---|---|
| Signature AI purple gradient | `linear-gradient(135deg, #667eea, #764ba2)` |
| Purplish-blue gradients | any gradient with 2+ blue/violet stops |
| Untouched Tailwind indigo | `bg-indigo-600` straight from defaults |
| AI tell-words | delve, tapestry, seamless, revolutionize, … |
| Lorem ipsum | placeholder Latin shipped as content |
| Emoji as icons | 🚀 ✨ in place of iconography |
| Generic hero copy | "Welcome to…", "Get Started" |
| Placeholder images | via.placeholder.com, picsum, … |
| Fake testimonials | "Sarah M."-style invented quotes |
| Em-dash overuse | stylistic tic LLMs lean on |
| Glassmorphism overuse | backdrop-blur on everything |
| Inline style soup | CSS written one element at a time |

Score starts at 100; each finding deducts its weight. Grades:
**Human-grade** (90+) · **Mostly human** (70+) · **Slop detected** (40+) · **Pure slop** (<40).

Safe issues (gradients, em-dashes) can be **auto-fixed** with one click —
the app shows the fixed code for review before you copy it out.

## Quickstart

```bash
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
.venv/bin/python -m uvicorn app.main:app --port 8123
```

Open http://127.0.0.1:8123 — upload a file or paste code, hit
**Check for slop**.

## Tests

```bash
.venv/bin/python -m pytest tests/ -q
```

## API

```bash
# Score code
curl -X POST localhost:8123/api/check \
  -H 'Content-Type: application/json' \
  -d '{"code":"<h1>Welcome to our revolutionary platform</h1>"}'

# Auto-fix safe issues
curl -X POST localhost:8123/api/fix \
  -H 'Content-Type: application/json' \
  -d '{"code":"...","marker_ids":["ai-purple-gradient"]}'
```

## Roadmap

- [ ] macOS double-click app (like Ledger.app)
- [ ] More markers: div-soup depth check, AI-image artifacts, font-stack audit
- [ ] Per-project config (`.slopcheckrc` to tune weights)
- [ ] Hosted website + mobile app on the same engine
