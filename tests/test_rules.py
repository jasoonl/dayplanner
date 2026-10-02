"""Port of tests/rules.test.ts — same 3 cases."""
from __future__ import annotations

from app.ai.rules import parse_free_text, rule_estimate

TODAY = "2026-09-24"  # Thursday
TZ = "America/New_York"


def test_pulls_out_durations_priority_due_dates():
    items = parse_free_text(
        "StudyScribes login bug 1.5h high priority\n"
        "Email Sergey about NAC registration must today 10 min\n"
        "read Gatsby ch 5 by tomorrow\n"
        "clean room whenever",
        TODAY, TZ,
    )
    assert len(items) == 4
    assert items[0].title == "StudyScribes login bug"
    assert items[0].minutes == 90
    assert items[0].priority == 3
    assert items[0].category == "personal"
    assert items[1].minutes == 10
    assert items[1].priority == 4
    assert items[1].title.startswith("Email Sergey about NAC registration")
    assert items[2].due == "2026-09-25"
    assert items[2].where == "portable"
    assert items[3].priority == 1
    assert items[3].title == "Clean room"


def test_resolves_weekday_names():
    [a] = parse_free_text("physics lab writeup due Monday 2 hours", TODAY, TZ)
    assert a.due == "2026-09-28"
    assert a.minutes == 120


def test_rule_estimates():
    t = rule_estimate("Unit 3 Test", "school")
    assert t.minutes == 180 and t.kind == "test" and t.priority == 3
    assert rule_estimate("Read chapter 4", "school").where == "portable"
    p = rule_estimate("Bruch mvt 3 practice log", "music")
    assert p.where == "home" and p.splittable is False
