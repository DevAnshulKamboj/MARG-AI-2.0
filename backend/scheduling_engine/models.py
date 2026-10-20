"""Plain data classes shared by the steps. No database code lives here."""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta


@dataclass(frozen=True)
class Request:
    block_id: str
    dept: str | None
    reason: str | None
    sub_section: str | None
    direction: str            # "UP" or "DOWN"
    line: int                 # 1 = Up line, 2 = Down line
    lo: float                 # stretch start, chainage km (lower end)
    hi: float                 # stretch end, chainage km (higher end)
    preferred_start: datetime
    preferred_end: datetime | None
    duration: timedelta
    score: float              # TOPSIS score from the priority engine
    rank: int | None


@dataclass(frozen=True)
class Rejection:
    block_id: str
    step: int                 # 1 = invalid request, 2 = no train-free window
    reason: str


@dataclass(frozen=True)
class Stop:
    seq: int
    station_id: int
    chainage: float
    stop_type: str            # "STOP" or "PASS"
    arrival: timedelta | None
    departure: timedelta | None


@dataclass
class Train:
    train_id: str
    name: str
    priority: int
    is_active: bool
    valid_from: object        # date | None
    valid_to: object          # date | None
    running_days: set[int]    # ISO weekdays: Mon=1 ... Sun=7
    stops: list[Stop] = field(default_factory=list)

    @property
    def direction(self) -> str | None:
        """UP if chainage rises along the timetable, DOWN if it falls."""
        if len(self.stops) < 2:
            return None
        first, last = self.stops[0].chainage, self.stops[-1].chainage
        if last > first:
            return "UP"
        if last < first:
            return "DOWN"
        return None


@dataclass(frozen=True)
class GrantedBlock:
    """A block already granted for the day (used to keep new blocks clear of it)."""
    lo: float
    hi: float
    line: int
    start: datetime
    end: datetime


@dataclass
class FeasibleRequest:
    request: Request
    busy: list[tuple[datetime, datetime]]   # merged busy intervals incl. margins
    starts: list[datetime]                  # start times where the full duration fits
