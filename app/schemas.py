"""Pydantic request models, mirroring src/lib/schemas.ts (zod)."""
from __future__ import annotations

import re
from typing import Literal, Optional

from pydantic import BaseModel, Field, field_validator

HHMM_RE = re.compile(r"^([01]\d|2[0-3]):[0-5]\d$")
ISO_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")

Where = Literal["home", "anywhere", "portable"]
Category = Literal["school", "music", "activity", "personal", "work", "routine"]


def _check_hhmm(v: Optional[str]) -> Optional[str]:
    if v is not None and not HHMM_RE.match(v):
        raise ValueError("must be HH:mm")
    return v


def _check_date(v: Optional[str]) -> Optional[str]:
    if v is not None and not ISO_DATE_RE.match(v):
        raise ValueError("must be yyyy-mm-dd")
    return v


class NewTask(BaseModel):
    title: str = Field(min_length=1, max_length=160)
    minutes: int = Field(ge=5, le=1200)
    priority: int = Field(ge=1, le=4)
    due: Optional[str] = None
    dueTime: Optional[str] = None
    where: Where = "anywhere"
    category: Category = "personal"
    splittable: bool = True
    notes: Optional[str] = Field(default=None, max_length=2000)

    _v1 = field_validator("due")(_check_date)
    _v2 = field_validator("dueTime")(_check_hhmm)


class TaskPatch(BaseModel):
    title: Optional[str] = Field(default=None, min_length=1, max_length=160)
    estimateMin: Optional[int] = Field(default=None, ge=5, le=1200)
    spentMin: Optional[int] = Field(default=None, ge=0, le=5000)
    priority: Optional[int] = Field(default=None, ge=1, le=4)
    where: Optional[Where] = None
    category: Optional[Category] = None
    splittable: Optional[bool] = None
    done: Optional[bool] = None
    due: Optional[str] = None
    dueTime: Optional[str] = None
    notes: Optional[str] = Field(default=None, max_length=2000)
    notBefore: Optional[str] = None

    _v1 = field_validator("due")(_check_date)
    _v2 = field_validator("dueTime")(_check_hhmm)
    _v3 = field_validator("notBefore")(_check_date)


class SourceInput(BaseModel):
    kind: Literal["ics", "google", "canvas_api"]
    label: str = Field(min_length=1, max_length=60)
    url: Optional[str] = Field(default=None, max_length=2000)
    role: Literal["events", "assignments", "auto"] = "auto"
    category: Category = "school"
    defaultPlaceId: Optional[str] = None
    token: Optional[str] = Field(default=None, max_length=400)
    calendarIds: Optional[list[str]] = None
    enabled: Optional[bool] = None


class PlaceInput(BaseModel):
    name: str = Field(min_length=1, max_length=80)
    address: str = Field(min_length=3, max_length=300)
    aliases: list[str] = Field(default_factory=list, max_length=20)
    isHome: bool = False


class RoutineInput(BaseModel):
    title: str = Field(min_length=1, max_length=120)
    minutes: int = Field(ge=5, le=480)
    days: list[int] = Field(min_length=1)
    where: Where = "home"
    category: Category = "routine"
    priority: int = Field(default=3, ge=1, le=4)
    windowStart: Optional[str] = None
    windowEnd: Optional[str] = None
    active: bool = True

    _v1 = field_validator("windowStart")(_check_hhmm)
    _v2 = field_validator("windowEnd")(_check_hhmm)


class CheckinBody(BaseModel):
    text: str = ""
    energy: Optional[Literal["low", "ok", "high"]] = None
