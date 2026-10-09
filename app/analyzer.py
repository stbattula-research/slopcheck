"""SlopCheck analyzer: deterministic detection of AI-generated UI fingerprints.

No ML, no API calls, no guesswork. Each marker is a concrete pattern that
shows up disproportionately in AI-generated frontends, with a human-grade
suggestion attached. The score is 100 minus deducted weights, clamped 0-100.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field


@dataclass
class Finding:
    marker_id: str
    name: str
    severity: str  # "high" | "medium" | "low"
    weight: int  # points deducted from 100
    count: int
    lines: list[int] = field(default_factory=list)
    excerpt: str = ""
    description: str = ""
    suggestion: str = ""
    auto_fixable: bool = False


@dataclass
class Analysis:
    score: int
    grade: str
    findings: list[Finding]

    @property
    def total_deductions(self) -> int:
        return sum(f.weight for f in self.findings)


def grade_for(score: int) -> str:
    if score >= 90:
        return "Human-grade"
    if score >= 70:
        return "Mostly human"
    if score >= 40:
        return "Slop detected"
    return "Pure slop"


# ---------------------------------------------------------------------------
# Marker definitions
# ---------------------------------------------------------------------------

# The infamous AI purple-blue gradient, in its many hex/rgb disguises.
_PURPLE_GRADIENT = re.compile(
    r"linear-gradient\([^)]*(?:"
    r"#667eea|#764ba2|#6a5af9|#7c6cf5|#8b5cf6|#a78bfa|#4f46e5|#6366f1"
    r"|102,\s*126,\s*234|118,\s*75,\s*162"
    r")[^)]*\)",
    re.IGNORECASE,
)

# Any linear-gradient(), so we can hue-check its stops.
_ANY_GRADIENT = re.compile(r"linear-gradient\(([^)]*)\)", re.IGNORECASE)
_HEX_COLOR = re.compile(r"#([0-9a-f]{6}|[0-9a-f]{3})", re.IGNORECASE)


def _hex_to_hue(hexcode: str) -> float:
    """Hue in degrees (0-360) for a hex color."""
    h = hexcode.lstrip("#")
    if len(h) == 3:
        h = "".join(c * 2 for c in h)
    r, g, b = (int(h[i : i + 2], 16) / 255 for i in (0, 2, 4))
    mx, mn = max(r, g, b), min(r, g, b)
    if mx == mn:
        return 0.0
    d = mx - mn
    if mx == r:
        hue = (g - b) / d + (6 if g < b else 0)
    elif mx == g:
        hue = (b - r) / d + 2
    else:
        hue = (r - g) / d + 4
    return hue * 60


def _is_purplish_blue(hexcode: str) -> bool:
    """True for blue/indigo/violet/purple hues (200-300 degrees)."""
    return 200 <= _hex_to_hue(hexcode) <= 300


def _gradient_line_hits(code: str, want_signature: bool) -> tuple[int, list[int], str]:
    """Find gradients whose stops are purplish-blue.

    want_signature=True  -> only the infamous signature colors.
    want_signature=False -> any purplish-blue gradient (broader net).
    """
    lines = code.splitlines()
    hits: list[int] = []
    excerpt = ""
    for i, line in enumerate(lines, start=1):
        for m in _ANY_GRADIENT.finditer(line):
            stops = _HEX_COLOR.findall(m.group(1))
            if not stops:
                continue
            if want_signature:
                hit = bool(_PURPLE_GRADIENT.search(m.group(0)))
            else:
                hit = sum(1 for s in stops if _is_purplish_blue("#" + s)) >= 2
            if hit:
                hits.append(i)
                if not excerpt:
                    excerpt = line.strip()[:160]
                break
    return len(hits), hits, excerpt

_TAILWIND_INDIGO = re.compile(
    r"\b(?:bg|text|border|from|via|to)-(indigo|violet|purple)-(?:400|500|600)\b"
)

_SLOP_WORDS = [
    # (pattern, label)
    (r"\bdelve\b", "delve"),
    (r"\btapestry\b", "tapestry"),
    (r"\belevate\b", "elevate"),
    (r"\bseamless(ly)?\b", "seamless"),
    (r"\bcutting[-\s]?edge\b", "cutting-edge"),
    (r"\brevolutioniz\w*\b", "revolutionize"),
    (r"\bunlock\b", "unlock"),
    (r"\bsupercharge\w*\b", "supercharge"),
    (r"\bgame[-\s]?changer\b", "game-changer"),
    (r"\bnestled\b", "nestled"),
    (r"\bbustling\b", "bustling"),
    (r"\bvibrant\b", "vibrant"),
    (r"\blook no further\b", "look no further"),
    (r"\bin today'?s fast[-\s]?paced world\b", "in today's fast-paced world"),
    (r"\bembark on\b", "embark on"),
    (r"\bharness the power\b", "harness the power"),
    (r"\bat the forefront\b", "at the forefront"),
    (r"\btestament to\b", "testament to"),
]

_LOREM = re.compile(r"lorem\s+ipsum", re.IGNORECASE)

# Emoji commonly used as stand-in icons in AI mockups.
_EMOJI_ICON = re.compile(
    "["
    "\U0001F680\U0001F3A8\U0001F31F\U00002728\U0001F4A1\U0001F525\U0001F389"
    "\U0001F4AA\U0001F3AF\U00002B50\U0001F680\U0001F916\U0001F4C8\U0001F4CA"
    "\U0001F50D\U000023F1\U0001F4DD\U0001F4AC\U0001F465\U0001F30D\U0001F3E0"
    "\U0001F6E0\U0001F511\U0001F4B3\U0001F4B0\U0001F911\U0001F60D"
    "]"
)

_GENERIC_HERO = re.compile(
    r"(welcome to|everything you need|get started|learn more|discover the (power|future)|transform your|the ultimate)",
    re.IGNORECASE,
)

_PLACEHOLDER_IMG = re.compile(
    r"(via\.placeholder\.com|placehold\.co|picsum\.photos|dummyimage\.com|placekitten\.com)",
    re.IGNORECASE,
)

_FAKE_TESTIMONIAL = re.compile(
    r"\b(John|Jane|Sarah|Michael|Emily|David|Alex)\s+[A-Z]\.",
)

_EMDASH = re.compile(r"—")

_BACKDROP_BLUR = re.compile(r"backdrop-(?:blur|filter)")

_INLINE_STYLE = re.compile(r'style\s*=\s*"')


def _line_hits(code: str, pattern: re.Pattern) -> tuple[int, list[int], str]:
    """Return (count, 1-based line numbers, first matched line excerpt)."""
    lines = code.splitlines()
    hits: list[int] = []
    excerpt = ""
    for i, line in enumerate(lines, start=1):
        if pattern.search(line):
            hits.append(i)
            if not excerpt:
                excerpt = line.strip()[:160]
    return len(hits), hits, excerpt


def _strip_code_tags(code: str) -> str:
    """Return visible text: strip <script>/<style> blocks and tags."""
    text = re.sub(r"<script.*?</script>", " ", code, flags=re.DOTALL | re.IGNORECASE)
    text = re.sub(r"<style.*?</style>", " ", text, flags=re.DOTALL | re.IGNORECASE)
    text = re.sub(r"<[^>]+>", " ", text)
    return re.sub(r"\s+", " ", text)


def analyze(code: str) -> Analysis:
    """Analyze source code and return score, grade, and findings."""
    findings: list[Finding] = []
    text = _strip_code_tags(code)

    # 1. The infamous AI purple gradient -------------------------------------
    count, lines, excerpt = _gradient_line_hits(code, want_signature=True)
    if count:
        findings.append(
            Finding(
                marker_id="ai-purple-gradient",
                name="Signature AI purple gradient",
                severity="high",
                weight=min(20, 8 + 4 * count),
                count=count,
                lines=lines[:10],
                excerpt=excerpt,
                description=(
                    "The #667eea → #764ba2 purple-blue gradient (and its close "
                    "cousins) is the single most recognizable AI-mockup fingerprint."
                ),
                suggestion=(
                    "Pick a palette with intent. Try a warm pastel wash "
                    "(peach → cream), a deep ink with one accent, or a duotone "
                    "drawn from your brand — never the default AI purple."
                ),
                auto_fixable=True,
            )
        )
    else:
        # Fall back: any purplish-blue gradient is still suspicious.
        count2, lines2, excerpt2 = _gradient_line_hits(code, want_signature=False)
        if count2:
            findings.append(
                Finding(
                    marker_id="generic-purple-gradient",
                    name="Generic purple-to-blue gradient",
                    severity="medium",
                    weight=min(10, 4 + 2 * count2),
                    count=count2,
                    lines=lines2[:10],
                    excerpt=excerpt2,
                    description="A purple-to-blue wash with no clear reason behind it.",
                    suggestion="Gradients should earn their place — tie them to your palette or drop them.",
                    auto_fixable=True,
                )
            )

    # 2. Default Tailwind indigo/violet --------------------------------------
    count, lines, excerpt = _line_hits(code, _TAILWIND_INDIGO)
    if count:
        findings.append(
            Finding(
                marker_id="default-indigo",
                name="Untouched Tailwind indigo/violet",
                severity="medium",
                weight=min(10, 3 + count),
                count=count,
                lines=lines[:10],
                excerpt=excerpt,
                description="Stock indigo-500/600 as the primary color, straight from the default palette.",
                suggestion="Define your own color tokens (e.g. a warm paper + brand red like #C13B2B) instead of shipping defaults.",
                auto_fixable=False,
            )
        )

    # 3. Slop vocabulary ------------------------------------------------------
    for pattern, label in _SLOP_WORDS:
        rx = re.compile(pattern, re.IGNORECASE)
        count, lines, excerpt = _line_hits(text, rx)
        if count:
            findings.append(
                Finding(
                    marker_id=f"slop-word-{label.replace(' ', '-').replace(chr(39), '')}",
                    name=f"AI tell-word: “{label}”",
                    severity="high" if count > 2 else "medium",
                    weight=min(12, 3 + 2 * count),
                    count=count,
                    lines=[],
                    excerpt=excerpt,
                    description=f"The word “{label}” appears far more often in AI-generated copy than in human writing.",
                    suggestion="Rewrite the sentence the way you'd say it out loud to a friend. Specific beats grand.",
                    auto_fixable=False,
                )
            )

    # 4. Lorem ipsum -----------------------------------------------------------
    count, lines, excerpt = _line_hits(text, _LOREM)
    if count:
        findings.append(
            Finding(
                marker_id="lorem-ipsum",
                name="Lorem ipsum placeholder",
                severity="high",
                weight=10,
                count=count,
                lines=[],
                excerpt=excerpt,
                description="Placeholder Latin shipped as if it were content.",
                suggestion="Write one real sentence about what this section actually says. Even a rough draft beats lorem.",
                auto_fixable=False,
            )
        )

    # 5. Emoji as icons ---------------------------------------------------------
    count, lines, excerpt = _line_hits(code, _EMOJI_ICON)
    if count:
        findings.append(
            Finding(
                marker_id="emoji-icons",
                name="Emoji used as icons",
                severity="medium",
                weight=min(10, 3 + 2 * count),
                count=count,
                lines=lines[:10],
                excerpt=excerpt,
                description="🚀✨ in place of real iconography is a classic AI-mockup shortcut.",
                suggestion="Swap in a proper icon set (Lucide, Ionicons, Heroicons) — consistent stroke width, real semantics.",
                auto_fixable=False,
            )
        )

    # 6. Generic hero copy -------------------------------------------------------
    count, lines, excerpt = _line_hits(text, _GENERIC_HERO)
    if count:
        findings.append(
            Finding(
                marker_id="generic-hero",
                name="Generic hero copy",
                severity="medium",
                weight=min(8, 3 + 2 * count),
                count=count,
                lines=[],
                excerpt=excerpt,
                description="“Welcome to…”, “Everything you need…”, “Get Started” — the AI hero starter pack.",
                suggestion="Say the one specific thing this page does, in under ten words. Steal from your user's vocabulary, not a template.",
                auto_fixable=False,
            )
        )

    # 7. Placeholder images -------------------------------------------------------
    count, lines, excerpt = _line_hits(code, _PLACEHOLDER_IMG)
    if count:
        findings.append(
            Finding(
                marker_id="placeholder-images",
                name="Placeholder image services",
                severity="medium",
                weight=min(8, 4 + 2 * count),
                count=count,
                lines=lines[:10],
                excerpt=excerpt,
                description="via.placeholder.com / picsum URLs left in the markup.",
                suggestion="Replace with real imagery, or design the layout so it doesn't need images at all.",
                auto_fixable=False,
            )
        )

    # 8. Fake testimonials ----------------------------------------------------------
    count, lines, excerpt = _line_hits(text, _FAKE_TESTIMONIAL)
    if count:
        findings.append(
            Finding(
                marker_id="fake-testimonials",
                name="Suspicious testimonial names",
                severity="low",
                weight=min(6, 2 + 2 * count),
                count=count,
                lines=[],
                excerpt=excerpt,
                description="“Sarah M.” style first-name-last-initial quotes read as invented.",
                suggestion="Use real quotes with real names and roles — or cut testimonials until you have them.",
                auto_fixable=False,
            )
        )

    # 9. Em-dash soup ---------------------------------------------------------------
    em_count = len(_EMDASH.findall(text))
    words = max(1, len(text.split()))
    if em_count >= 3 and em_count / words > 0.004:
        findings.append(
            Finding(
                marker_id="emdash-soup",
                name="Em-dash overuse",
                severity="low",
                weight=min(6, 2 + em_count // 3),
                count=em_count,
                lines=[],
                excerpt="",
                description=f"{em_count} em-dashes — a stylistic tic LLMs lean on heavily.",
                suggestion="Most em-dashes can become commas or periods. Keep one per page, maximum, and only where the pause earns it.",
                auto_fixable=True,
            )
        )

    # 10. Backdrop-blur everywhere ------------------------------------------------------
    count, lines, excerpt = _line_hits(code, _BACKDROP_BLUR)
    if count >= 5:
        findings.append(
            Finding(
                marker_id="blur-everywhere",
                name="Glassmorphism overuse",
                severity="low",
                weight=min(6, count // 2),
                count=count,
                lines=lines[:10],
                excerpt=excerpt,
                description=f"{count} frosted-glass surfaces — trendy, but AI reaches for it by default.",
                suggestion="Use blur sparingly for actual layering (modals, floating bars). Flat surfaces can just be flat.",
                auto_fixable=False,
            )
        )

    # 11. Inline style soup ----------------------------------------------------------------
    count, lines, excerpt = _line_hits(code, _INLINE_STYLE)
    if count >= 10:
        findings.append(
            Finding(
                marker_id="inline-style-soup",
                name="Inline style soup",
                severity="low",
                weight=min(6, count // 4),
                count=count,
                lines=lines[:10],
                excerpt=excerpt,
                description=f"{count} inline style attributes — AI writes CSS one element at a time instead of designing a system.",
                suggestion="Extract repeated declarations into classes or design tokens. If three elements share a style, it's a component.",
                auto_fixable=False,
            )
        )

    total = sum(f.weight for f in findings)
    score = max(0, 100 - total)
    # Sort: severity then weight.
    order = {"high": 0, "medium": 1, "low": 2}
    findings.sort(key=lambda f: (order[f.severity], -f.weight))
    return Analysis(score=score, grade=grade_for(score), findings=findings)


# ---------------------------------------------------------------------------
# Auto-fix
# ---------------------------------------------------------------------------

# A warm pastel replacement for the AI purple — glossy, not generic.
_PASTEL_REPLACEMENT = "linear-gradient(135deg, #ffd6e0 0%, #ffe9d6 50%, #d6ecff 100%)"

_EMDASH_FIX = re.compile(r"\s*—\s*")


def _replace_purplish_gradients(code: str) -> tuple[str, int]:
    """Swap purplish-blue gradients for the pastel replacement. Returns (code, n)."""

    def _swap(m: re.Match) -> str:
        stops = _HEX_COLOR.findall(m.group(1))
        if _PURPLE_GRADIENT.search(m.group(0)) or (
            stops and sum(1 for s in stops if _is_purplish_blue("#" + s)) >= 2
        ):
            return _PASTEL_REPLACEMENT
        return m.group(0)

    n = 0

    def _counting_swap(m: re.Match) -> str:
        nonlocal n
        out = _swap(m)
        if out != m.group(0):
            n += 1
        return out

    return _ANY_GRADIENT.sub(_counting_swap, code), n


def apply_fixes(code: str, marker_ids: list[str]) -> tuple[str, list[str]]:
    """Apply safe automatic fixes. Returns (fixed_code, applied_marker_ids)."""
    applied: list[str] = []
    fixed = code
    if "ai-purple-gradient" in marker_ids or "generic-purple-gradient" in marker_ids:
        new, n = _replace_purplish_gradients(fixed)
        if n:
            fixed = new
            applied += [m for m in ("ai-purple-gradient", "generic-purple-gradient") if m in marker_ids]
    if "emdash-soup" in marker_ids:
        new, n = _EMDASH_FIX.subn(", ", fixed)
        if n:
            fixed, applied = new, applied + ["emdash-soup"]
    return fixed, applied


def auto_fixable_ids(analysis: Analysis) -> list[str]:
    return [f.marker_id for f in analysis.findings if f.auto_fixable]
