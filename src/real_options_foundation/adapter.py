"""Public API normalization with injected offline transport, never a live client.

Wire conventions: https://docs.deribit.com/articles/options-data-collection-best-practices
Consulted 2026-10-21. RO-02 must verify the then-current provider specification.
"""

import json
from decimal import Decimal
from typing import Any, Callable, Mapping, Optional

from .common import FoundationError, content_hash, freeze, integer, note_event
from .events import EventEnvelope


class RateLimited(FoundationError):
    pass


class OfflinePublicAdapter:
    """Allowlisted requests to a supplied fixture transport; no network default."""

    METHODS = {
        "public/get_instruments": {"currency", "kind", "expired"},
        "public/get_instrument": {"instrument_name"},
        "public/get_order_book": {"instrument_name", "depth"},
        "public/ticker": {"instrument_name"},
        "public/get_index_price": {"index_name"},
    }

    def __init__(self, transport: Optional[Callable] = None, *, max_attempts: int = 2,
                 pause: Optional[Callable] = None):
        integer(max_attempts, "max_attempts", 1)
        if max_attempts > 3:
            raise FoundationError("Offline retries are bounded at three attempts")
        self._transport = transport
        self._pause = pause if pause is not None else lambda seconds: None
        self.max_attempts = max_attempts
        self.request_count = 0
        self._faults = []

    @property
    def faults(self):
        return tuple(self._faults)

    def request(self, method: str, params: Mapping[str, Any]):
        if method not in self.METHODS or not isinstance(params, Mapping):
            raise FoundationError("Method outside public offline allowlist")
        if set(params) - self.METHODS[method]:
            raise FoundationError("Unexpected or credential-bearing request field")
        if self._transport is None:
            raise FoundationError("No offline fixture transport; production network disabled")
        request_params = freeze(params)
        if "instrument_name" in params and (not isinstance(params["instrument_name"], str)
                                           or not params["instrument_name"].startswith("BTC-")):
            raise FoundationError("Only BTC instruments in initial scope")
        if "currency" in params and params["currency"] != "BTC":
            raise FoundationError("Only BTC instrument metadata in initial scope")
        for attempt in range(self.max_attempts):
            note_event()
            self.request_count += 1
            try:
                response = self._transport(method, request_params)
                if not isinstance(response, Mapping):
                    raise FoundationError("Malformed public API response")
                if response.get("error") is not None:
                    error = response["error"]
                    if isinstance(error, Mapping) and error.get("code") == 10028:
                        raise RateLimited("Public API rate limit")
                    raise FoundationError("Public API error")
                if "result" not in response:
                    raise FoundationError("Public API response has no result")
                return freeze(response["result"])
            except (TimeoutError, RateLimited) as exc:
                self._faults.append(freeze({"attempt": attempt + 1, "method": method,
                                           "fault": type(exc).__name__, "retry": attempt + 1 < self.max_attempts}))
                if attempt + 1 == self.max_attempts:
                    raise FoundationError("Bounded offline retry budget exhausted") from exc
                self._pause(2 ** attempt)
            except (OSError, FoundationError) as exc:
                self._faults.append(freeze({"attempt": attempt + 1, "method": method,
                                           "fault": type(exc).__name__, "retry": False}))
                raise FoundationError("Public adapter stopped on non-retryable error") from exc
        raise FoundationError("Unreachable retry state")


def decode_message(raw: Any) -> Mapping[str, Any]:
    def unique_object(pairs):
        result = {}
        for key, value in pairs:
            if key in result:
                raise FoundationError("Duplicate wire JSON key")
            result[key] = value
        return result
    if isinstance(raw, (bytes, str)):
        try:
            value = json.loads(raw, parse_float=Decimal,
                               object_pairs_hook=unique_object,
                               parse_constant=lambda value: (_ for _ in ()).throw(FoundationError("Nonfinite JSON")))
        except (ValueError, UnicodeError) as exc:
            raise FoundationError("Malformed wire JSON") from exc
    else:
        value = raw
    if not isinstance(value, Mapping):
        raise FoundationError("Wire event must be an object")
    # Reject injected binary floats, recursively, before immutable normalization.
    return freeze(value)


def normalize_book_message(raw, *, connection_id: str, ingest_sequence: int,
                           receive_timestamp_ms: int, receive_monotonic_ns: int) -> EventEnvelope:
    message = decode_message(raw)
    if message.get("method") != "subscription":
        raise FoundationError("Not a subscription notification")
    params = message.get("params")
    if not isinstance(params, Mapping):
        raise FoundationError("Missing subscription params")
    data = params.get("data")
    channel = params.get("channel")
    if not isinstance(data, Mapping) or not isinstance(channel, str):
        raise FoundationError("Missing subscription channel/data")
    instrument = data.get("instrument_name")
    if not isinstance(instrument, str) or not instrument.startswith("BTC-"):
        raise FoundationError("Unknown or unsupported instrument")
    if channel not in {"book." + instrument + ".100ms", "book." + instrument + ".agg2"}:
        raise FoundationError("Only complete public L2 book channels are normalized here")
    kind = {"snapshot": "book_snapshot", "change": "book_change"}.get(data.get("type"))
    if kind is None:
        raise FoundationError("Unknown book notification type")
    change = integer(data.get("change_id"), "change_id")
    exchange = integer(data.get("timestamp"), "exchange timestamp")
    payload = {"change_id": change, "bids": data.get("bids"), "asks": data.get("asks")}
    if kind == "book_change":
        payload["prev_change_id"] = integer(data.get("prev_change_id"), "prev_change_id")
    event_id = content_hash({"connection_id": connection_id, "channel": channel,
                             "change_id": change, "event_type": kind})
    return EventEnvelope(source="deribit", connection_id=connection_id,
                         ingest_sequence=ingest_sequence, channel=channel,
                         instrument_id=instrument, exchange_timestamp_ms=exchange,
                         receive_timestamp_ms=receive_timestamp_ms,
                         receive_monotonic_ns=receive_monotonic_ns,
                         event_id=event_id, event_type=kind, payload=payload)
