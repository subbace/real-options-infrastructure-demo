"""Offline, fail-closed Deribit L2 replay and conservative taker fills.

The public 100ms/agg2 feed represents price levels, not order identities or
queue priority. A simulated taker order claims the observed liquidity once:
only a fresh complete snapshot enables another order on this book instance.
No network, credentials, maker fills or scientific evaluation live here.
"""

from dataclasses import dataclass
from decimal import (Context, Decimal, DivisionByZero, InvalidOperation,
                     Overflow, ROUND_HALF_EVEN, localcontext)
from typing import Any, Dict, Optional, Tuple

from .common import FoundationError, InstrumentSpec, as_decimal, content_hash, note_event


Levels = Tuple[Tuple[Decimal, Decimal], ...]
_FILL_CONTEXT = Context(prec=50, rounding=ROUND_HALF_EVEN,
                        Emin=-999999, Emax=999999, capitals=1, clamp=0,
                        traps=[InvalidOperation, DivisionByZero, Overflow])


def _integer(value: Any, name: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise FoundationError("%s must be a non-negative integer" % name)
    return value


@dataclass(frozen=True)
class BookSnapshot:
    instrument_id: str
    connection_id: Optional[str]
    status: str
    invalid_reason: Optional[str]
    change_id: Optional[int]
    bids: Levels
    asks: Levels
    exchange_timestamp_ms: Optional[int]
    receive_timestamp_ms: Optional[int]
    receive_monotonic_ns: Optional[int]
    transport_receive_timestamp_ms: Optional[int]
    transport_receive_monotonic_ns: Optional[int]
    consumed: bool

    def as_dict(self) -> Dict[str, Any]:
        return {name: getattr(self, name) for name in self.__dataclass_fields__}


@dataclass(frozen=True)
class BookQuote:
    instrument_id: str
    connection_id: str
    change_id: int
    bids: Levels
    asks: Levels
    exchange_timestamp_ms: int
    receive_timestamp_ms: int
    receive_monotonic_ns: int
    transport_receive_monotonic_ns: int
    decision_timestamp_ms: int
    decision_monotonic_ns: int
    book_hash: str

    @property
    def best_bid(self) -> Optional[Decimal]:
        return self.bids[0][0] if self.bids else None

    @property
    def best_ask(self) -> Optional[Decimal]:
        return self.asks[0][0] if self.asks else None


@dataclass(frozen=True)
class TakerFill:
    instrument_id: str
    side: str
    requested_amount: Decimal
    filled_amount: Decimal
    unfilled_amount: Decimal
    levels: Levels
    quote_amount: Optional[Decimal]
    average_price: Decimal
    partial: bool
    source_book_hash: str
    liquidity_model: str = "one_taker_claim_per_full_snapshot"
    spread_included: bool = True


class L2Book:
    """A single instrument's observed L2 state, separate from simulated fills.

    ``apply`` returns False for an identical intrinsic event identity, even if
    its receive time differs. Corruption raises FoundationError and disables
    quotes until a valid new snapshot. UTC rollback is allowed; receive
    monotonic time may not decrease within one connection.
    """

    def __init__(self, spec: InstrumentSpec) -> None:
        self.spec = spec
        self._bids: Dict[Decimal, Decimal] = {}
        self._asks: Dict[Decimal, Decimal] = {}
        self._connection: Optional[str] = None
        self._retired_connections = set()
        self._seen: Dict[str, str] = {}
        self._last_monotonic: Dict[str, int] = {}
        self._change_id: Optional[int] = None
        self._exchange_ms: Optional[int] = None
        self._receive_ms: Optional[int] = None
        self._receive_ns: Optional[int] = None
        self._transport_ms: Optional[int] = None
        self._transport_ns: Optional[int] = None
        self._valid = False
        self._reason: Optional[str] = "snapshot_required"
        self._consumed = False

    def _fail(self, reason: str) -> None:
        self._valid = False
        self._reason = reason
        raise FoundationError(reason)

    @property
    def valid(self) -> bool:
        return self._valid

    @property
    def state_hash(self) -> str:
        return content_hash(self.snapshot().as_dict())

    def snapshot(self) -> BookSnapshot:
        return BookSnapshot(
            self.spec.instrument_id, self._connection,
            "valid" if self._valid else "invalid", self._reason,
            self._change_id, tuple(sorted(self._bids.items(), reverse=True)),
            tuple(sorted(self._asks.items())), self._exchange_ms,
            self._receive_ms, self._receive_ns, self._transport_ms,
            self._transport_ns, self._consumed,
        )

    def apply(self, event: Any) -> bool:
        try:
            note_event()
            return self._apply(event)
        except FoundationError:
            self._valid = False
            if self._reason is None:
                self._reason = "invalid_event"
            raise
        except (AttributeError, KeyError, TypeError, ValueError, ArithmeticError) as exc:
            self._fail("malformed event: %s" % type(exc).__name__)
        return False  # unreachable, retained for static checkers

    def _apply(self, event: Any) -> bool:
        event_id = event.event_id
        if not isinstance(event_id, str) or not event_id:
            self._fail("event_id_required")
        identity = event.identity_hash
        if event_id in self._seen:
            if self._seen[event_id] == identity:
                return False
            self._fail("conflicting_event_identity")
        self._seen[event_id] = identity
        event_type = event.event_type
        if event_type not in ("book_snapshot", "book_change", "heartbeat", "disconnect"):
            self._fail("unsupported_event_type")
        if event.source != "deribit":
            self._fail("unsupported_source")
        if event.instrument_id not in (self.spec.instrument_id, "*"):
            self._fail("wrong_instrument")
        if event_type.startswith("book_") and event.instrument_id != self.spec.instrument_id:
            self._fail("wrong_book_instrument")
        if event_type.startswith("book_"):
            if event.channel not in (
                "book.%s.100ms" % self.spec.instrument_id,
                "book.%s.agg2" % self.spec.instrument_id,
            ):
                self._fail("public_full_depth_channel_required")
        elif event.channel not in ("heartbeat", "transport"):
            self._fail("transport_channel_required")
        connection = event.connection_id
        if not isinstance(connection, str) or not connection:
            self._fail("connection_id_required")
        receive_ms = _integer(event.receive_timestamp_ms, "receive_timestamp_ms")
        receive_ns = _integer(event.receive_monotonic_ns, "receive_monotonic_ns")
        exchange_ms = event.exchange_timestamp_ms
        if exchange_ms is not None:
            _integer(exchange_ms, "exchange_timestamp_ms")
        elif event_type.startswith("book_"):
            self._fail("book_exchange_timestamp_required")
        previous_ns = self._last_monotonic.get(connection)
        if previous_ns is not None and receive_ns < previous_ns:
            self._fail("receive_monotonic_decreased")
        self._last_monotonic[connection] = receive_ns
        if connection in self._retired_connections:
            self._fail("retired_connection_event")
        connection_changed = connection != self._connection
        if connection_changed:
            if self._connection is not None:
                self._retired_connections.add(self._connection)
            self._connection = connection
            self._valid = False
            self._reason = "connection_snapshot_required"
        self._transport_ms, self._transport_ns = receive_ms, receive_ns
        if event_type == "disconnect":
            self._valid = False
            self._reason = "disconnected"
            return True
        if event_type == "heartbeat":
            return True
        payload = event.payload
        change_id = _integer(payload["change_id"], "change_id")
        is_snapshot = event_type == "book_snapshot"
        if (is_snapshot and self._change_id is not None
                and not connection_changed
                and self._receive_ns is not None
                and receive_ns >= self._receive_ns
                and change_id < self._change_id):
            self._fail("snapshot_sequence_moved_backwards")
        if not is_snapshot:
            if not self._valid:
                self._fail("snapshot_required_before_change")
            previous = _integer(payload["prev_change_id"], "prev_change_id")
            if previous != self._change_id or change_id <= previous:
                self._fail("book_sequence_gap_or_out_of_order")
        elif payload.get("prev_change_id") is not None:
            self._fail("snapshot_prev_change_id_must_be_null")
        bids = {} if is_snapshot else dict(self._bids)
        asks = {} if is_snapshot else dict(self._asks)
        self._apply_levels(bids, payload["bids"], is_snapshot)
        self._apply_levels(asks, payload["asks"], is_snapshot)
        if bids and asks and max(bids) >= min(asks):
            self._fail("crossed_or_locked_book")
        self._bids, self._asks = bids, asks
        self._change_id = change_id
        self._exchange_ms = exchange_ms
        self._receive_ms, self._receive_ns = receive_ms, receive_ns
        self._valid, self._reason = True, None
        if is_snapshot:
            self._consumed = False
        return True

    def _apply_levels(self, levels: Dict[Decimal, Decimal], updates: Any,
                      is_snapshot: bool) -> None:
        if not isinstance(updates, (list, tuple)):
            self._fail("levels_must_be_sequence")
        touched = set()
        for update in updates:
            if not isinstance(update, (list, tuple)) or len(update) != 3:
                self._fail("level_requires_action_price_amount")
            action, raw_price, raw_amount = update
            if action not in ("new", "change", "delete"):
                self._fail("unknown_level_action")
            if is_snapshot and action != "new":
                self._fail("snapshot_requires_new_levels")
            price = as_decimal(raw_price)
            self.spec.validate_price(price)
            amount = as_decimal(raw_amount)
            if is_snapshot and price in touched:
                self._fail("duplicate_price_in_message")
            touched.add(price)
            if action == "delete":
                if amount < 0 or price not in levels:
                    self._fail("invalid_delete")
                if amount:
                    self.spec.validate_amount(amount)
                del levels[price]
                continue
            self.spec.validate_amount(amount)
            if action == "new" and price in levels:
                self._fail("new_level_already_exists")
            if action == "change" and price not in levels:
                self._fail("changed_level_missing")
            levels[price] = amount

    def quote(self, *, decision_timestamp_ms: int, decision_monotonic_ns: int,
              max_transport_age_ms: int,
              max_book_age_ms: Optional[int] = None) -> BookQuote:
        decision_ms = _integer(decision_timestamp_ms, "decision_timestamp_ms")
        decision_ns = _integer(decision_monotonic_ns, "decision_monotonic_ns")
        transport_limit = _integer(max_transport_age_ms, "max_transport_age_ms")
        if max_book_age_ms is not None:
            _integer(max_book_age_ms, "max_book_age_ms")
        if not self._valid:
            raise FoundationError("book_invalid: %s" % self._reason)
        if self._consumed:
            raise FoundationError("snapshot_liquidity_already_claimed")
        if (decision_ms < self._receive_ms or decision_ms < self._transport_ms
                or decision_ms < self._exchange_ms
                or decision_ns < self._receive_ns or decision_ns < self._transport_ns):
            raise FoundationError("future_information_unavailable_at_decision")
        if decision_ns - self._transport_ns > transport_limit * 1000000:
            raise FoundationError("stale_transport")
        if (max_book_age_ms is not None
                and decision_ns - self._receive_ns > max_book_age_ms * 1000000):
            raise FoundationError("book_age_limit_exceeded")
        snap = self.snapshot()
        return BookQuote(
            self.spec.instrument_id, self._connection, self._change_id, snap.bids, snap.asks,
            self._exchange_ms, self._receive_ms, self._receive_ns,
            self._transport_ns, decision_ms, decision_ns, self.state_hash,
        )

    def execute_taker(self, side: str, amount: Any, *,
                      decision_timestamp_ms: int, decision_monotonic_ns: int,
                      max_transport_age_ms: int,
                      max_book_age_ms: Optional[int] = None,
                      allow_partial: bool = False) -> TakerFill:
        note_event()
        if side not in ("buy", "sell"):
            raise FoundationError("side_must_be_buy_or_sell")
        if not isinstance(allow_partial, bool):
            raise FoundationError("allow_partial_must_be_bool")
        requested = as_decimal(amount)
        self.spec.validate_amount(requested)
        quote = self.quote(
            decision_timestamp_ms=decision_timestamp_ms,
            decision_monotonic_ns=decision_monotonic_ns,
            max_transport_age_ms=max_transport_age_ms,
            max_book_age_ms=max_book_age_ms,
        )
        with localcontext(_FILL_CONTEXT):
            remaining = requested
            fills = []
            total = Decimal("0")
            for price, available in (quote.asks if side == "buy" else quote.bids):
                taken = min(remaining, available)
                if taken:
                    fills.append((price, taken))
                    total += price * taken
                    remaining -= taken
                if remaining == 0:
                    break
            if not fills or (remaining and not allow_partial):
                raise FoundationError("insufficient_displayed_liquidity")
            filled = requested - remaining
            average_price = total / filled
        self._consumed = True
        return TakerFill(
            self.spec.instrument_id, side, requested, filled, remaining, tuple(fills),
            total if self.spec.kind == "option" else None,
            average_price, remaining != 0, quote.book_hash,
        )
