"""Immutable observation envelopes with independent availability clocks."""

from dataclasses import dataclass
from typing import Any, Mapping, Optional

from .common import FoundationError, content_hash, freeze, integer


@dataclass(frozen=True)
class EventEnvelope:
    source: str
    connection_id: str
    ingest_sequence: int
    channel: str
    instrument_id: str
    exchange_timestamp_ms: Optional[int]
    receive_timestamp_ms: int
    receive_monotonic_ns: int
    event_id: str
    event_type: str
    payload: Mapping[str, Any]
    schema_version: int = 1

    def __post_init__(self) -> None:
        for field in ("source", "connection_id", "channel", "instrument_id", "event_id"):
            value = getattr(self, field)
            if not isinstance(value, str) or not value:
                raise FoundationError("Missing event {}".format(field))
        if self.schema_version != 1 or isinstance(self.schema_version, bool):
            raise FoundationError("Unsupported envelope version")
        integer(self.ingest_sequence, "ingest_sequence")
        integer(self.receive_timestamp_ms, "receive_timestamp_ms")
        integer(self.receive_monotonic_ns, "receive_monotonic_ns")
        if self.exchange_timestamp_ms is not None:
            integer(self.exchange_timestamp_ms, "exchange_timestamp_ms")
        if self.event_type not in {"book_snapshot", "book_change", "heartbeat", "disconnect",
                                   "trade", "mark", "provider_greeks", "index", "quote", "technical_error"}:
            raise FoundationError("Unknown observation event type")
        if not isinstance(self.payload, Mapping):
            raise FoundationError("Event payload must be a mapping")
        object.__setattr__(self, "payload", freeze(self.payload))

    @property
    def payload_hash(self) -> str:
        return content_hash(self.payload)

    @property
    def identity_hash(self) -> str:
        return content_hash({"source": self.source, "instrument_id": self.instrument_id,
                             "event_type": self.event_type, "payload": self.payload})

    @property
    def event_hash(self) -> str:
        return content_hash(self)


def causal_latest(events, *, decision_timestamp_ms: int, decision_monotonic_ns: int,
                  max_age_ms: int, event_type: str, instrument_id: str,
                  max_exchange_age_ms: Optional[int] = None) -> EventEnvelope:
    """Latest received event of one semantic type; never mix estimate and quote."""
    integer(decision_timestamp_ms, "decision_timestamp_ms")
    integer(decision_monotonic_ns, "decision_monotonic_ns")
    integer(max_age_ms, "max_age_ms")
    if max_exchange_age_ms is not None:
        integer(max_exchange_age_ms, "max_exchange_age_ms")
    available = [event for event in events if event.event_type == event_type
                 and event.instrument_id == instrument_id
                 and event.receive_timestamp_ms <= decision_timestamp_ms
                 and event.receive_monotonic_ns <= decision_monotonic_ns
                 and (event.exchange_timestamp_ms is None or event.exchange_timestamp_ms <= decision_timestamp_ms)]
    if not available:
        raise FoundationError("No causally available event")
    latest = max(available, key=lambda event: event.receive_monotonic_ns)
    if decision_monotonic_ns - latest.receive_monotonic_ns > max_age_ms * 1000000:
        raise FoundationError("Observation exceeds configured age")
    if max_exchange_age_ms is not None and (latest.exchange_timestamp_ms is None or
            decision_timestamp_ms - latest.exchange_timestamp_ms > max_exchange_age_ms):
        raise FoundationError("Missing or stale exchange-time observation")
    return latest
