"""Deterministic fallback rule engine — used automatically when Gemini is
unavailable, unset or fails. Faithful port of src/lib/ai/rules.ts.

This is the arithmetic backbone of the check-in parser and estimate guesser;
it MUST stay deterministic, dependency-free and match the TS original.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Optional
from zoneinfo import ZoneInfo


@dataclass
class Rule:
    re: re.Pattern
    kind: str
    minutes: int
    priority: Optional[int] = None
    where: Optional[str] = None
    splittable: Optional[bool] = None


RULES: list[Rule] = [
    Rule(re.compile(r"\b(final exam|midterm|exam|unit test|test)\b", re.I), "test", 180, priority=3),
    Rule(re.compile(r"\bquiz\b", re.I), "quiz", 60, priority=3),
    Rule(re.compile(r"\b(research paper|essay|paper)\b", re.I), "essay", 240, priority=3),
    Rule(re.compile(r"\b(project|portfolio)\b", re.I), "project", 300, priority=3),
    Rule(re.compile(r"\b(presentation|slides)\b", re.I), "presentation", 120),
    Rule(re.compile(r"\blab\b", re.I), "lab", 90),
    Rule(re.compile(r"\b(draft|outline)\b", re.I), "draft", 90),
    Rule(re.compile(r"\b(vocab|flashcards?|memori[sz]e)\b", re.I), "memorize", 30, where="portable"),
    Rule(re.compile(r"\b(read|reading|chapters?|ch\.|pages?|pp\.)\b", re.I), "reading", 45, where="portable"),
    Rule(re.compile(r"\b(scales|etude|practice log|repertoire|practice)\b", re.I), "practice", 45, where="home", splittable=False),
    Rule(re.compile(r"\b(response|reflection|journal|annotation)\b", re.I), "writing", 40),
    Rule(re.compile(r"\b(problem set|pset|worksheet|homework|hw|exercises?|#\s?\d|problems?)\b", re.I), "homework", 45),
    Rule(re.compile(r"\b(form|sign|email|register|submit|upload)\b", re.I), "admin", 15, splittable=False),
]


@dataclass
class Guess:
    minutes: int
    priority: int
    where: str
    splittable: bool
    kind: str


def rule_estimate(title: str, category: str) -> Guess:
    for r in RULES:
        if r.re.search(title):
            return Guess(
                minutes=r.minutes,
                kind=r.kind,
                priority=r.priority if r.priority is not None else 2,
                where=r.where if r.where is not None else ("home" if category == "music" else "anywhere"),
                splittable=r.splittable if r.splittable is not None else True,
            )
    minutes = 45 if category == "school" else 30
    return Guess(minutes=minutes, kind="other", priority=2, where=("home" if category == "music" else "anywhere"), splittable=True)


@dataclass
class ParsedItem:
    title: str
    minutes: int
    priority: int
    due: Optional[str]
    dueTime: Optional[str]
    where: str
    category: str


WEEKDAYS = ["monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday"]

_H_RE = re.compile(r"(\d+(?:\.\d+)?)\s*(?:h|hr|hrs|hours?)\b", re.I)
_M_RE = re.compile(r"(\d+)\s*(?:m|min|mins|minutes?)\b", re.I)
_HALF_RE = re.compile(r"half an hour", re.I)
_MUST_RE = re.compile(r"\b(must|have to|need to) (?:do |finish )?(?:it )?today\b|\bmust\b|\basap\b", re.I)
_HIGH_RE = re.compile(r"\b(urgent|important|high(?: priority)?|priority)\b", re.I)
_LOW_RE = re.compile(r"\b(low(?: priority)?|whenever|if (?:i have )?time|optional|maybe)\b", re.I)
_PRIORITY_WORDS_RE = re.compile(
    r"\b(must|asap|urgent|important|high priority|low priority|priority|whenever|if (?:i have )?time|optional|maybe)\b",
    re.I,
)
_TODAY_RE = re.compile(r"\btoday|tonight\b", re.I)
_TOMORROW_RE = re.compile(r"\btomorrow\b", re.I)
_WEEKDAY_RE = re.compile(r"\b(?:by |due |on )?(mon|tue|tues|wed|thu|thur|thurs|fri|sat|sun)[a-z]*\b")
_DUE_WORDS_RE = re.compile(
    r"\b(?:by|due|on|for)?\s*(today|tonight|tomorrow|(?:mon|tue|tues|wed|thu|thur|thurs|fri|sat|sun)[a-z]*)\b", re.I
)
_TRAILING_RE = re.compile(r"\b(for|about|around|~|takes?|need(?:s)?|spend)\b\s*$", re.I)
_TRAILING2_RE = re.compile(r"\s+(for|about|around|takes?)$", re.I)
_MUSIC_RE = re.compile(r"\b(violin|music|theory|orchestra|etude|scales|msm)\b", re.I)
_ACTIVITY_RE = re.compile(r"\b(fencing|workout|club|practice|shp|columbia)\b", re.I)
_PERSONAL_RE = re.compile(r"\b(app|website|studyscribes|code|build)\b", re.I)


def parse_free_text(text: str, today: str, tz: str) -> list[ParsedItem]:
    pieces = [p.strip() for p in re.split(r"\n|;|•|(?:^|\s)-\s", text) if len(p.strip()) > 1]
    y, m, d = (int(x) for x in today.split("-"))
    base = datetime(y, m, d, tzinfo=ZoneInfo(tz))

    items: list[ParsedItem] = []
    for raw in pieces:
        s = f" {raw} "
        minutes = 0.0

        h = _H_RE.search(s)
        if h:
            minutes += float(h.group(1)) * 60
            s = s.replace(h.group(0), " ")
        mm = _M_RE.search(s)
        if mm:
            minutes += int(mm.group(1))
            s = s.replace(mm.group(0), " ")
        if _HALF_RE.search(s):
            minutes += 30
            s = _HALF_RE.sub(" ", s)

        priority = 2
        if _MUST_RE.search(s):
            priority = 4
        elif _HIGH_RE.search(s):
            priority = 3
        elif _LOW_RE.search(s):
            priority = 1
        s = _PRIORITY_WORDS_RE.sub(" ", s)

        due: Optional[str] = None
        if _TODAY_RE.search(s):
            due = today
        elif _TOMORROW_RE.search(s):
            due = (base + timedelta(days=1)).strftime("%Y-%m-%d")
        else:
            wd = _WEEKDAY_RE.search(s.lower())
            if wd:
                prefix = wd.group(1)[:3]
                idx = next((i for i, w in enumerate(WEEKDAYS) if w.startswith(prefix)), -1)
                if idx >= 0:
                    diff = (idx + 1) - base.isoweekday()
                    if diff <= 0:
                        diff += 7
                    due = (base + timedelta(days=diff)).strftime("%Y-%m-%d")

        s = _DUE_WORDS_RE.sub(" ", s)
        s = _TRAILING_RE.sub(" ", s)

        title = re.sub(r"\s{2,}", " ", s)
        title = re.sub(r"^[\s,.:-]+|[\s,.:-]+$", "", title)
        title = _TRAILING2_RE.sub("", title)

        category = (
            "music" if _MUSIC_RE.search(raw) else
            "activity" if _ACTIVITY_RE.search(raw) else
            "personal" if _PERSONAL_RE.search(raw) else
            "school"
        )
        guess = rule_estimate(title, category)
        if due == today and priority == 2:
            priority = 3

        final_title = (title[:1].upper() + title[1:]) if title else raw
        items.append(ParsedItem(
            title=final_title,
            minutes=round(minutes / 5) * 5 if minutes > 0 else guess.minutes,
            priority=priority,
            due=due,
            dueTime=None,
            where=guess.where,
            category=category,
        ))
    return items
