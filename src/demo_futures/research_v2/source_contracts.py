"""Historical source metadata validation ONLY: no loader, paths, SQL or hashing."""
from dataclasses import dataclass
from datetime import datetime, timezone
from enum import Enum
import re
from .config import HOUR, STEP, SYMBOLS
from .contracts import EvidenceIdentity, result, valid_evidence, valid_identity, valid_time


def _utc_ms(iso):
    return int(datetime.fromisoformat(iso).replace(tzinfo=timezone.utc).timestamp() * 1000)


TARGET_START = _utc_ms("2026-05-03T00:00:00")
TARGET_END = _utc_ms("2026-08-31T00:00:00")
PROTECTED = ((TARGET_END, _utc_ms("2026-09-15T00:00:00")),
             (_utc_ms("2026-09-15T00:00:00"), _utc_ms("2026-10-09T06:50:00")))
PROJECTION = ("open_time", "open", "high", "low", "close", "volume",
              "close_time", "quote_volume", "trades")


class AvailabilityMode(str, Enum):
    REQUIRE_VERIFIED_ASOF = "REQUIRE_VERIFIED_ASOF"
    EXPLORATORY_CLOSED_BAR_APPROXIMATION = "EXPLORATORY_CLOSED_BAR_APPROXIMATION"


class OriginalAvailability(str, Enum):
    UNKNOWN = "UNKNOWN"
    VERIFIED = "VERIFIED"


@dataclass(frozen=True)
class ScopedHashMetadata:
    digest: str
    source_id: str
    revision: str
    symbol: str
    interval: str
    start: int
    end: int
    projection: tuple[str, ...] = PROJECTION
    algorithm: str = "sha256"
    scope: str = "SYNTHETIC_ROWS_ONLY"


@dataclass(frozen=True)
class SourceExpectation:
    scope_id: str
    source_id: str
    revision: str
    start: int = TARGET_START
    end: int = TARGET_END
    evidence: str = "SYNTHETIC_ONLY"


@dataclass(frozen=True)
class SourceMetadata:
    scope_id: str
    source_id: str
    revision: str
    symbol: str
    interval: str
    start: int
    end: int
    decision_time: int
    retrieved_at: int
    mode: AvailabilityMode
    original_availability: OriginalAvailability
    source_evidence: EvidenceIdentity | None
    scope_evidence: EvidenceIdentity | None
    scoped_hash: ScopedHashMetadata | None
    original_receipt: int | None = None
    availability_evidence: EvidenceIdentity | None = None
    origin: str = "https://demo-fapi.binance.com"
    path: str = "/fapi/v1/klines"
    evidence: str = "SYNTHETIC_ONLY"


def assess_source(metadata, expected):
    """Acceptance is internal metadata consistency, NOT permission or as-of proof."""
    invalid, insufficient = [], []
    if type(metadata) is not SourceMetadata or type(expected) is not SourceExpectation:
        return result(("INVALID_SCHEMA_OR_TIME",))
    m, e = metadata, expected
    if (m.evidence != "SYNTHETIC_ONLY" or e.evidence != "SYNTHETIC_ONLY"
            or not valid_identity(e.scope_id) or m.scope_id != e.scope_id):
        invalid.append("UNAPPROVED_SCOPE")
    if (not all(valid_identity(v) for v in (m.source_id, e.source_id))
            or m.source_id != e.source_id or m.origin != "https://demo-fapi.binance.com"
            or m.path != "/fapi/v1/klines"):
        invalid.append("SOURCE_IDENTITY_MISMATCH")
    if not all(valid_identity(v) for v in (m.revision, e.revision)) or m.revision != e.revision:
        invalid.append("REVISION_MISMATCH")
    if m.symbol not in SYMBOLS:
        invalid.append("WRONG_SYMBOL")
    if m.interval != "5m":
        invalid.append("WRONG_INTERVAL")
    times = (m.start, m.end, e.start, e.end, m.decision_time, m.retrieved_at)
    if not all(valid_time(t) for t in times):
        return result(invalid + ["INVALID_SCHEMA_OR_TIME"])
    if any(m.start < end and m.end > start for start, end in PROTECTED):
        invalid.append("PROTECTED_PERIOD")
    if (not TARGET_START <= e.start < e.end <= TARGET_END
            or (m.start, m.end) != (e.start, e.end)
            or m.start % STEP or m.end % STEP or e.start % STEP or e.end % STEP):
        invalid.append("UNAUTHORIZED_DATES")
    if (not m.start <= m.decision_time < m.end or (m.decision_time + 1) % HOUR
            or m.retrieved_at < m.end
            or type(m.mode) is not AvailabilityMode
            or type(m.original_availability) is not OriginalAvailability):
        invalid.append("INVALID_SCHEMA_OR_TIME")
    for evidence, assertion in ((m.source_evidence, "SOURCE_IDENTITY"), (m.scope_evidence, "APPROVED_SYNTHETIC_SCOPE")):
        if not valid_evidence(evidence, assertion, m.source_id, m.revision):
            invalid.append("INVALID_EVIDENCE")
    h = m.scoped_hash
    if (type(h) is not ScopedHashMetadata or not isinstance(h.digest, str)
            or re.fullmatch("[0-9a-f]{64}", h.digest) is None
            or h.algorithm != "sha256" or h.scope != "SYNTHETIC_ROWS_ONLY"
            or h.projection != PROJECTION
            or (h.source_id, h.revision, h.symbol, h.interval, h.start, h.end)
               != (m.source_id, m.revision, m.symbol, m.interval, m.start, m.end)):
        invalid.append("SCOPED_HASH_INVALID")
    if m.original_receipt is not None:
        if (not valid_time(m.original_receipt) or m.original_receipt > m.retrieved_at
                or m.original_receipt < m.decision_time + 1):
            invalid.append("INVALID_SCHEMA_OR_TIME")
    verified = (m.original_receipt is not None and
                valid_evidence(m.availability_evidence, "ORIGINAL_ASOF_RECEIPT", m.source_id, m.revision))
    if m.availability_evidence is not None and not valid_evidence(
            m.availability_evidence, "ORIGINAL_ASOF_RECEIPT", m.source_id, m.revision):
        invalid.append("INVALID_EVIDENCE")
    if m.original_availability == OriginalAvailability.VERIFIED and not verified:
        invalid.append("ORIGINAL_AVAILABILITY_UNSUPPORTED")
    if (m.original_availability == OriginalAvailability.VERIFIED and verified
            and valid_time(m.original_receipt) and m.original_receipt > m.decision_time + 1):
        insufficient.append("RECEIPT_LATE")
    if m.mode == AvailabilityMode.REQUIRE_VERIFIED_ASOF:
        if m.original_availability != OriginalAvailability.VERIFIED or not verified:
            insufficient.append("ORIGINAL_RECEIPT_UNKNOWN")
    # Approximation preserves UNKNOWN and all receipt values; it changes no consumer.
    return result(invalid, insufficient)
