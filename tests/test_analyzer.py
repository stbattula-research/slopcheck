"""Tests for the SlopCheck analyzer engine."""

import pytest

from app.analyzer import (
    Analysis,
    analyze,
    apply_fixes,
    auto_fixable_ids,
    grade_for,
)


def pad(code: str) -> str:
    """Pad a snippet past the 15-line honesty threshold with neutral lines."""
    filler = "\n".join(f"<p>Filler paragraph number {i} with ordinary words.</p>" for i in range(16))
    return code + "\n" + filler


def ids(analysis: Analysis) -> set[str]:
    return {f.marker_id for f in analysis.findings}


def test_clean_code_scores_100():
    code = """
    <html><head><style>
    body { font-family: Georgia, serif; background: #faf6ef; color: #2b2620; }
    .btn { background: #C13B2B; border-radius: 6px; }
    </style></head>
    <body><h1>Our menu</h1><p>We serve noodles on Tuesdays.</p><button class="btn">Order</button></body></html>
    """
    a = analyze(pad(code))
    assert a.score == 100
    assert a.grade == "Human-grade"
    assert a.findings == []


def test_signature_purple_gradient_detected():
    code = '<div style="background: linear-gradient(135deg, #667eea 0%, #764ba2 100%)">x</div>'
    a = analyze(pad(code))
    assert "ai-purple-gradient" in ids(a)
    assert a.score < 100


def test_custom_purple_blue_gradient_detected():
    code = "<style>.h { background: linear-gradient(to right, #7a5af8, #3b82f6); }</style>"
    a = analyze(pad(code))
    assert "generic-purple-gradient" in ids(a)


def test_pastel_gradient_not_flagged():
    code = "<style>.h { background: linear-gradient(135deg, #ffd6e0, #ffe9d6, #d6ecff); }</style>"
    a = analyze(pad(code))
    assert "ai-purple-gradient" not in ids(a)
    assert "generic-purple-gradient" not in ids(a)


def test_slop_words_detected():
    code = "<p>In today's fast-paced world, our revolutionary platform will elevate your workflow. Delve into a vibrant tapestry of features.</p>"
    a = analyze(pad(code))
    found = ids(a)
    assert any(i.startswith("slop-word-") for i in found)
    assert a.score < 90


def test_lorem_ipsum_detected():
    a = analyze(pad("<p>Lorem ipsum dolor sit amet, consectetur adipiscing elit.</p>"))
    assert "lorem-ipsum" in ids(a)


def test_emoji_icons_detected():
    a = analyze(pad('<button>🚀 Launch</button><span>✨ New</span>'))
    assert "emoji-icons" in ids(a)


def test_generic_hero_detected():
    a = analyze(pad("<h1>Welcome to our platform</h1><button>Get Started</button>"))
    assert "generic-hero" in ids(a)


def test_placeholder_images_detected():
    a = analyze(pad('<img src="https://via.placeholder.com/300">'))
    assert "placeholder-images" in ids(a)


def test_emdash_soup_detected_and_fixed():
    code = "<p>" + "word — " * 12 + "end of a long paragraph with many words here.</p>"
    a = analyze(pad(code))
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
    a = analyze(pad(code))
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
    a = analyze(pad(code))
    assert 0 <= a.score <= 100


def test_findings_sorted_by_severity():
    code = (
        "<p>Lorem ipsum dolor sit amet.</p>"
        '<img src="https://picsum.photos/200">'
        '<div style="background: linear-gradient(135deg, #667eea, #764ba2)">x</div>'
    )
    a = analyze(pad(code))
    order = {"high": 0, "medium": 1, "low": 2}
    keys = [order[f.severity] for f in a.findings]
    assert keys == sorted(keys)


def test_tailwind_indigo_detected():
    code = '<button class="bg-indigo-600 text-white rounded">Get Started</button>'
    a = analyze(pad(code))
    assert "default-indigo" in ids(a)


# --- v2: new slop-pattern markers ----------------------------------------------


def test_important_soup_detected():
    code = "<style>" + "\n".join(f".a{i} {{ color: red !important; }}" for i in range(6)) + "</style>"
    a = analyze(pad(code))
    assert "important-soup" in ids(a)


def test_div_soup_detected():
    code = "<body>" + "".join(f"<div class='x{i}'>content</div>" for i in range(12)) + "</body>"
    a = analyze(pad(code))
    assert "div-soup" in ids(a)


def test_div_soup_not_flagged_with_semantics():
    code = "<body><header>x</header><main>" + "".join(f"<div class='x{i}'>c</div>" for i in range(12)) + "</main></body>"
    a = analyze(pad(code))
    assert "div-soup" not in ids(a)


def test_todo_left_detected():
    code = "<script>\n// TODO: fix this later\n// FIXME: broken\nvar x = 1;\n</script>"
    a = analyze(pad(code))
    assert "todo-left" in ids(a)


def test_placeholder_text_detected():
    code = "<p>Hi, Your Name Here! Contact us at info@example.com</p>"
    a = analyze(pad(code))
    assert "placeholder-text" in ids(a)


def test_fake_buttons_detected():
    code = '<div onclick="doThing()" class="btn">Click me</div>'
    a = analyze(pad(code))
    assert "fake-buttons" in ids(a)


def test_missing_alt_detected():
    code = '<img src="photo.jpg"><img src="logo.png" alt="Logo">'
    a = analyze(pad(code))
    assert "missing-alt" in ids(a)


def test_dead_css_detected():
    code = "<style>.used { color: red; } .ghost { color: blue; }</style><p class='used'>hi</p>"
    a = analyze(pad(code))
    assert "dead-css" in ids(a)


def test_over_commented_detected():
    code = "<body>\n<!-- header -->\n<!-- main -->\n<!-- footer -->\n<p>hi</p>\n</body>"
    a = analyze(pad(code))
    assert "over-commented" in ids(a)


def test_every_finding_has_valid_category():
    from app.analyzer import CATEGORIES
    code = pad("<p>Lorem ipsum. Your Name Here. TODO fix. \U0001F680</p>"
               "<style>.a{color:red!important}.b{color:red!important}.c{color:red!important}"
               ".d{color:red!important}.e{color:red!important}</style>"
               "<div style='background:linear-gradient(135deg,#667eea,#764ba2)'>x</div>")
    a = analyze(code)
    assert a.findings, "expected findings"
    for f in a.findings:
        assert f.category in CATEGORIES, f.marker_id


def test_category_scores_sum_to_total():
    from app.analyzer import CATEGORIES
    code = pad("<p>Lorem ipsum dolor.</p><div style='background:linear-gradient(135deg,#667eea,#764ba2)'>x</div>")
    a = analyze(code)
    total = sum(v["score"] for v in a.category_scores.values())
    assert total == a.score
    for c, v in a.category_scores.items():
        assert v["score"] <= v["weight"] == CATEGORIES[c]["weight"]


def test_insufficient_input_refused():
    a = analyze("<p>hi</p>")
    assert a.insufficient is True
    assert a.findings == []
    assert "15" in a.summary


def test_fifteen_lines_is_enough():
    code = "\n".join(f"<p>line {i}</p>" for i in range(15))
    a = analyze(code)
    assert a.insufficient is False


def test_summary_clean():
    code = pad("<article><h1>Our team</h1><p>We build furniture in Austin.</p></article>")
    a = analyze(code)
    assert "Clean" in a.summary or "human-grade" in a.summary


def test_summary_lists_top_hits():
    code = pad("<p>Lorem ipsum dolor sit amet.</p><div style='background:linear-gradient(135deg,#667eea,#764ba2)'>x</div>")
    a = analyze(code)
    assert "Lorem ipsum" in a.summary or "purple gradient" in a.summary
