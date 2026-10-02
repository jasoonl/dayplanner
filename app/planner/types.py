"""Core planner types. All instants are epoch milliseconds; all wall-clock
strings ("HH:mm", "yyyy-MM-dd") are interpreted in settings.timezone.

This is a faithful, dependency-free port of src/lib/planner/types.ts.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Callable, Literal, Optional

Priority = int  # 1 low, 2 medium, 3 high, 4 must-do-today
Where = Literal["home", "anywhere", "portable"]
Category = Literal["school", "music", "activity", "personal", "work", "routine"]
TravelMode = Literal["TRANSIT", "DRIVE", "WALK", "BICYCLE"]
Energy = Literal["low", "ok", "high"]

BlockKind = Literal["event", "travel", "task", "routine", "break", "meal", "prep", "buffer"]
WarningKind = Literal[
    "conflict", "late", "atRisk", "overdue", "didntFit", "noMeal", "pastBedtime", "overload"
]


@dataclass
class Place:
    id: str
    name: str
    address: str
    aliases: list[str] = field(default_factory=list)
    isHome: bool = False


@dataclass
class FixedEvent:
    id: str
    title: str
    start: int
    end: int
    placeId: Optional[str]  # None -> no travel implication
    sourceId: str
    sourceLabel: str
    allDay: bool = False
    location: Optional[str] = None


@dataclass
class Task:
    id: str
    title: str
    category: Category
    estimateMin: int
    spentMin: int = 0
    priority: Priority = 2
    where: Where = "anywhere"
    splittable: bool = True
    done: bool = False
    sourceLabel: Optional[str] = None
    dueAt: Optional[int] = None
    dueAllDay: bool = False
    notBefore: Optional[int] = None


@dataclass
class Routine:
    id: str
    title: str
    minutes: int
    days: list[int]  # 1=Mon..7=Sun
    where: Where
    category: Category
    priority: Priority
    active: bool = True
    windowStart: Optional[str] = None
    windowEnd: Optional[str] = None


@dataclass
class MealConfig:
    title: str
    earliest: str
    latest: str
    preferred: str
    minutes: int
    days: list[int]


@dataclass
class DayWindowConfig:
    wake: str
    bedtime: str


@dataclass
class PlannerSettings:
    timezone: str
    days: dict[str, DayWindowConfig]  # keys "1".."7"
    morningRoutineMin: int
    windDownMin: int
    focusMin: int
    breakMin: int
    minChunkMin: int
    arriveEarlyMin: int
    goHomeThresholdMin: int
    maxWorkMinPerDay: int
    lookaheadDays: int
    travelMode: TravelMode
    meals: list[MealConfig]


# (fromPlaceId, toPlaceId, arriveByMs) -> minutes
TravelLookup = Callable[[str, str, int], float]


@dataclass
class PlanBlock:
    id: str
    kind: BlockKind
    start: int
    end: int
    title: str
    subtitle: Optional[str] = None
    placeId: Optional[str] = None
    taskId: Optional[str] = None
    routineId: Optional[str] = None
    eventId: Optional[str] = None
    sourceLabel: Optional[str] = None
    category: Optional[Category] = None
    priority: Optional[Priority] = None
    fromPlaceId: Optional[str] = None
    toPlaceId: Optional[str] = None
    mode: Optional[TravelMode] = None
    late: Optional[bool] = None
    onTransit: Optional[bool] = None


@dataclass
class PlanWarning:
    kind: WarningKind
    message: str
    taskId: Optional[str] = None
    eventId: Optional[str] = None
    minutes: Optional[float] = None


@dataclass
class FreeWindow:
    start: int
    end: int
    where: Literal["home", "away", "transit"]
    placeId: Optional[str]


@dataclass
class DaySkeleton:
    date: str
    dayStart: int
    dayEnd: int
    blocks: list[PlanBlock]
    windows: list[FreeWindow]
    warnings: list[PlanWarning]


@dataclass
class DayOverrides:
    energy: Optional[Energy] = None
    skippedEventIds: Optional[list[str]] = None


@dataclass
class PlanInput:
    date: str
    events: list[FixedEvent]
    tasks: list[Task]
    routines: list[Routine]
    places: list[Place]
    settings: PlannerSettings
    travel: TravelLookup
    now: Optional[int] = None
    overrides: Optional[DayOverrides] = None
    pastBlocks: Optional[list[PlanBlock]] = None


@dataclass
class DayLoad:
    date: str
    eventMin: float
    travelMin: float
    capacityMin: float
    allocatedMin: float


@dataclass
class PlanStats:
    focusMin: float
    travelMin: float
    eventMin: float
    freeMin: float
    dayMin: float


@dataclass
class AtRiskItem:
    taskId: str
    shortfallMin: float


@dataclass
class UnplacedItem:
    taskId: str
    minutes: float


@dataclass
class PlanResult:
    date: str
    generatedAt: int
    blocks: list[PlanBlock]
    warnings: list[PlanWarning]
    stats: PlanStats
    quotas: dict[str, float]
    atRisk: list[AtRiskItem]
    week: list[DayLoad]
    unplaced: list[UnplacedItem]
    dueSoon: list[str] = field(default_factory=list)
