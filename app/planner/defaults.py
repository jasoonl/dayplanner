from .types import DayWindowConfig, MealConfig, PlannerSettings

_weekday = DayWindowConfig(wake="06:45", bedtime="23:00")
_weekend = DayWindowConfig(wake="08:00", bedtime="23:30")


def default_settings(timezone: str = "America/New_York") -> PlannerSettings:
    return PlannerSettings(
        timezone=timezone,
        days={
            "1": _weekday,
            "2": _weekday,
            "3": _weekday,
            "4": _weekday,
            "5": DayWindowConfig(wake=_weekday.wake, bedtime="23:30"),
            "6": _weekend,
            "7": DayWindowConfig(wake=_weekend.wake, bedtime="23:00"),
        },
        morningRoutineMin=40,
        windDownMin=30,
        focusMin=50,
        breakMin=10,
        minChunkMin=20,
        arriveEarlyMin=10,
        goHomeThresholdMin=45,
        maxWorkMinPerDay=300,
        lookaheadDays=7,
        travelMode="TRANSIT",
        meals=[
            MealConfig(title="Dinner", earliest="17:30", latest="20:45", preferred="18:30", minutes=30, days=[1, 2, 3, 4, 5, 6, 7]),
            MealConfig(title="Lunch", earliest="11:45", latest="14:00", preferred="12:30", minutes=30, days=[6, 7]),
        ],
    )
