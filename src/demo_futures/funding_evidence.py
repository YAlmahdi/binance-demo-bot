"""Pure diagnostics for caller-supplied funding observations; never proves completeness.

This module neither collects evidence nor integrates with the financial engine.
The timestamp contract must be established externally, not inferred from magnitude.
Duplicate groups retain every observation. Interval references identify groups,
so overlapping intervals never manufacture additional unique events.
"""

from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from decimal import Decimal, InvalidOperation
import re


UTC_UNIX_MILLISECONDS = "UTC_UNIX_MILLISECONDS"
MAX_TIMESTAMP = 253402300799999
MAX_RECORDS = 10000
MAX_INTERVALS = 128
MAX_RECORD_FIELDS = 32
_EPOCH = datetime(1970, 1, 1, tzinfo=timezone.utc)
_DECIMAL = re.compile(r"[+-]?(?:[0-9]+(?:\.[0-9]*)?|\.[0-9]+)(?:[eE][+-]?[0-9]{1,4})?\Z")


def _timestamp(value):
    if type(value) is not int or not 0 <= value <= MAX_TIMESTAMP:
        raise ValueError("timestamp must be an exact nonnegative UTC millisecond integer")
    return value


def utc_milliseconds(value):
    """Convert an explicit UTC datetime exactly; reject sub-millisecond precision."""
    if (type(value) is not datetime or type(value.tzinfo) is not timezone
            or value.utcoffset() != timedelta(0) or value.microsecond % 1000):
        raise ValueError("an explicit UTC datetime with millisecond precision is required")
    delta = value - _EPOCH
    return _timestamp(delta.days * 86400000 + delta.seconds * 1000 + delta.microseconds // 1000)


def _text(value, name):
    if type(value) is not str or not 1 <= len(value) <= 128:
        raise ValueError(name + " must be bounded nonempty text")
    return value


def _number(value, name, positive=False):
    _text(value, name)
    if not _DECIMAL.fullmatch(value):
        raise ValueError(name + " must be a finite decimal string")
    try:
        number = Decimal(value)
    except InvalidOperation:
        raise ValueError(name + " must be a finite decimal string") from None
    if not number.is_finite() or (positive and number <= 0):
        raise ValueError(name + " is outside its domain")
    return number


@dataclass(frozen=True)
class FundingObservation:
    timestamp: int
    funding_rate: str
    mark_price: str | None
    rate_type: str | None
    event_id: str | int | None


@dataclass(frozen=True)
class FundingGroup:
    timestamp: int
    observations: tuple[FundingObservation, ...]
    source_indices: tuple[int, ...]
    conflicting: bool


@dataclass(frozen=True)
class EvidenceIssue:
    code: str
    source_indices: tuple[int, ...]


@dataclass(frozen=True)
class IntervalEvidence:
    interval_id: str
    timestamps: tuple[int, ...]


@dataclass(frozen=True)
class FundingEvidence:
    groups: tuple[FundingGroup, ...]
    intervals: tuple[IntervalEvidence, ...]
    issues: tuple[EvidenceIssue, ...]
    completeness: str = field(default="NOT_VERIFIED", init=False)
    authority: str = field(default="LOCAL_OBSERVATIONS_ONLY", init=False)


def validate_funding_evidence(records, intervals, *, symbol, timestamp_unit):
    """Diagnose one symbol and (id, entry, exit) intervals with entry < event <= exit.

    Accept only plain containers and decimal strings. Invalid schemas reject the
    whole input; missing marks remain explicit, without a price fallback. Results
    preserve original number strings and all conflicting alternatives. There is
    no implicit schedule, authenticity check, financial calculation or I/O.
    Reused explicit event IDs at different times are diagnosed, never silently
    merged or interpreted as authenticated correction lineage.
    """
    if type(timestamp_unit) is not str or timestamp_unit != UTC_UNIX_MILLISECONDS:
        raise ValueError("an established UTC_UNIX_MILLISECONDS contract is required")
    if type(symbol) is not str or symbol not in ("BTCUSDT", "ETHUSDT"):
        raise ValueError("unsupported evidence symbol")
    if type(records) not in (list, tuple) or len(records) > MAX_RECORDS:
        raise ValueError("records must be a bounded plain sequence")
    if type(intervals) not in (list, tuple) or len(intervals) > MAX_INTERVALS:
        raise ValueError("intervals must be a bounded plain sequence")
    checked_intervals = []
    interval_ids = set()
    for interval in intervals:
        if type(interval) not in (tuple, list) or len(interval) != 3:
            raise ValueError("interval must contain id, entry and exit")
        identity, entry, exit_time = interval
        _text(identity, "interval id")
        _timestamp(entry)
        _timestamp(exit_time)
        if entry >= exit_time or identity in interval_ids:
            raise ValueError("intervals need unique ids and entry before exit")
        interval_ids.add(identity)
        checked_intervals.append((identity, entry, exit_time))

    grouped = {}
    identities = {}
    issues = []
    previous = None
    for index, record in enumerate(records):
        if type(record) is not dict:
            raise ValueError("funding record must be a plain dictionary")
        if len(record) > MAX_RECORD_FIELDS or any(type(key) is not str for key in record):
            raise ValueError("funding record requires bounded plain string keys")
        if type(record.get("symbol")) is not str or record["symbol"] != symbol:
            raise ValueError("funding record symbol differs from scope")
        timestamp = _timestamp(record.get("fundingTime"))
        rate = record.get("fundingRate")
        rate_value = _number(rate, "funding rate")
        mark = record.get("markPrice")
        if mark is None or (type(mark) is str and mark == ""):
            mark = None
            mark_value = None
            issues.append(EvidenceIssue("MISSING_MARK", (index,)))
        else:
            mark_value = _number(mark, "mark price", positive=True)
        rate_type = record.get("rateType")
        if rate_type is not None:
            _text(rate_type, "rate type")
        event_id = record.get("eventId")
        if event_id is not None:
            if type(event_id) is int:
                if not 0 <= event_id < 2**64:
                    raise ValueError("event id integer is outside its domain")
            else:
                _text(event_id, "event id")
        observation = FundingObservation(timestamp, rate, mark, rate_type, event_id)
        if event_id is not None:
            identities.setdefault((type(event_id), event_id), []).append((index, timestamp))
        # Numerical comparison is exact; original encodings remain in observations.
        signature = (rate_value, mark_value, rate_type, event_id)
        grouped.setdefault(timestamp, []).append((index, observation, signature))
        if previous is not None and timestamp < previous:
            issues.append(EvidenceIssue("OUT_OF_ORDER", (index - 1, index)))
        previous = timestamp

    groups = []
    for timestamp, members in sorted(grouped.items()):
        indices = tuple(member[0] for member in members)
        conflict = any(member[2] != members[0][2] for member in members[1:])
        if len(members) > 1:
            issues.append(EvidenceIssue("CONFLICTING_EVENT" if conflict else "DUPLICATE_EVENT", indices))
        groups.append(FundingGroup(timestamp, tuple(m[1] for m in members), indices, conflict))
    for members in identities.values():
        if len({timestamp for _, timestamp in members}) > 1:
            issues.append(EvidenceIssue("REUSED_EVENT_ID", tuple(index for index, _ in members)))
    memberships = tuple(IntervalEvidence(identity, tuple(g.timestamp for g in groups
                        if entry < g.timestamp <= exit_time))
                        for identity, entry, exit_time in checked_intervals)
    return FundingEvidence(tuple(groups), memberships, tuple(issues))
