"""Tests for the SlopCheck analyzer engine."""

import pytest

from app.analyzer import (
    Analysis,
    analyze,
    apply_fixes,
    auto_fixable_ids,
    grade_for,
)


def ids(analysis: Analysis) -> set[str]:
    return {f.marker_id for f in analysis.findings}


def test_clean_code_scores_100():
    code = """
    <html><head><style>
    body { font-family: Georgia, serif; background: #faf6ef; color: #2b2620; }
    .btn { background: #C13B2B; border-radius: 6px; }
    </style></head>
    <body><h1>Our menu</h1><p>We serve noodles on Tuesdays.</p></body></html>
    """
    a = analyze(code)
    assert a.score == 100
    assert a.grade == "Human-grade"
    assert a.findings == []


def test_signature_purple_gradient_detected():
    code = '<div style="background: linear-gradient(135deg, #667eea 0%, #764ba2 100%)">x</div>'
    a = analyze(code)
    assert "ai-purple-gradient" in ids(a)
    assert a.score < 100


def test_custom_purple_blue_gradient_detected():
    code = "<style>.h { background: linear-gradient(to right, #7a5af8, #3b82f6); }</style>"
    a = analyze(code)
    assert "generic-purple-gradient" in ids(a)


def test_pastel_gradient_not_flagged():
    code = "<style>.h { background: linear-gradient(135deg, #ffd6e0, #ffe9d6, #d6ecff); }</style>"
    a = analyze(code)
    assert "ai-purple-gradient" not in ids(a)
    assert "generic-purple-gradient" not in ids(a)


def test_slop_words_detected():
    code = "<p>In today's fast-paced world, our revolutionary platform will elevate your workflow. Delve into a vibrant tapestry of features.</p>"
    a = analyze(code)
    found = ids(a)
    assert any(i.startswith("slop-word-") for i in found)
    assert a.score < 90


def test_lorem_ipsum_detected():
    a = analyze("<p>Lorem ipsum dolor sit amet, consectetur adipiscing elit.</p>")
    assert "lorem-ipsum" in ids(a)


def test_emoji_icons_detected():
    a = analyze('<button>🚀 Launch</button><span>✨ New</span>')
    assert "emoji-icons" in ids(a)


def test_generic_hero_detected():
    a = analyze("<h1>Welcome to our platform</h1><button>Get Started</button>")
    assert "generic-hero" in ids(a)


def test_placeholder_images_detected():
    a = analyze('<img src="https://via.placeholder.com/300">')
    assert "placeholder-images" in ids(a)


def test_emdash_soup_detected_and_fixed():
    code = "<p>" + "word — " * 12 + "end of a long paragraph with many words here.</p>"
    a = analyze(code)
    assert "emdash-soup" in ids(a)
    fixed, applied = apply_fixes(code, ["emdash-soup"])
    assert "emdash-soup" in applied
    assert "—" not in fixed


def test_autofix_replaces_purple_gradient():
    code = '<div style="background: linear-gradient(135deg, #667eea, #764ba2)">x</div>'
    fixed, applied = apply_fixes(code, ["ai-purple-gradient"])
    assert "ai-purple-gradient" in applied
    assert "#667eea" not in fixed
    assert "linear-gradient(135deg, #ffd6e0" in fixed


def test_autofix_leaves_clean_code_alone():
    code = "<p>Hello world.</p>"
    fixed, applied = apply_fixes(code, ["ai-purple-gradient", "emdash-soup"])
    assert fixed == code
    assert applied == []


def test_auto_fixable_ids_only_lists_fixable():
    code = "<p>Lorem ipsum. 🚀</p>"
    a = analyze(code)
    for mid in auto_fixable_ids(a):
        f = next(f for f in a.findings if f.marker_id == mid)
        assert f.auto_fixable


def test_grade_boundaries():
    assert grade_for(100) == "Human-grade"
    assert grade_for(90) == "Human-grade"
    assert grade_for(89) == "Mostly human"
    assert grade_for(70) == "Mostly human"
    assert grade_for(69) == "Slop detected"
    assert grade_for(40) == "Slop detected"
    assert grade_for(39) == "Pure slop"
    assert grade_for(0) == "Pure slop"


def test_score_never_negative():
    code = "<p>Lorem ipsum</p>" * 5 + "delve " * 20 + "🚀" * 10
    code += '<div style="background: linear-gradient(135deg, #667eea, #764ba2)">x</div>' * 5
    a = analyze(code)
    assert 0 <= a.score <= 100


def test_findings_sorted_by_severity():
    code = (
        "<p>Lorem ipsum dolor sit amet.</p>"
        '<img src="https://picsum.photos/200">'
        '<div style="background: linear-gradient(135deg, #667eea, #764ba2)">x</div>'
    )
    a = analyze(code)
    order = {"high": 0, "medium": 1, "low": 2}
    keys = [order[f.severity] for f in a.findings]
    assert keys == sorted(keys)


def test_tailwind_indigo_detected():
    code = '<button class="bg-indigo-600 text-white rounded">Get Started</button>'
    a = analyze(code)
    assert "default-indigo" in ids(a)
