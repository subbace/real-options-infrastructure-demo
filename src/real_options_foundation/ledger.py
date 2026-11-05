"""Offline, BTC-denominated journal for the RO-01 artificial fixtures.

Contract references checked on 2026-10-21:
https://support.deribit.com/hc/en-us/articles/31424939096093-Inverse-Options
https://support.deribit.com/hc/en-us/articles/31424938981533-Inverse-Futures

Native option amounts are BTC; inverse-future amounts are USD, not contracts.
For signed USD size Q, inverse PnL is Q * (1 / entry - 1 / exit) BTC.
Additional entries use a quantity-weighted reciprocal entry price. Since
2026-08-01, an ITM option first creates Q = signed BTC size * strike USD
(opposite sign for puts), then the expiry future settles in BTC. The generated
future has no second delivery fee. These operations must not also book an
option intrinsic-value cashflow.

This is an offline accounting component, not Deribit's margin/liquidation
engine. Fees, optional cash quantization and timestamps are explicit fixture
inputs. There is no assumed venue fee, exchange rounding or execution model.
Decimal arithmetic uses a fixed 50-digit local context; optional quantization
uses ROUND_HALF_EVEN. No binary floats, data acquisition or trading are used.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from decimal import Decimal, DecimalException, ROUND_HALF_EVEN, localcontext
from types import MappingProxyType
from typing import Any, Dict, Iterable, Mapping, Optional, Tuple

from .common import FoundationError, InstrumentSpec, as_decimal, content_hash, note_event


ZERO = Decimal("0")
ONE = Decimal("1")
PRECISION = 50
TWO_STAGE_START_MS = int(datetime(2026, 8, 1, tzinfo=timezone.utc).timestamp() * 1000)
SETTLEMENT_CONVENTION = "inverse_option_two_stage_from_20260801"


def _decimal(value: Any, name: str, positive: bool = False) -> Decimal:
    result = as_decimal(value)
    if positive and result <= ZERO:
        raise FoundationError("{} must be positive".format(name))
    return result


def _fee(value: Any) -> Decimal:
    result = _decimal(value, "fee_btc")
    if result < ZERO:
        raise FoundationError("Fees must be nonnegative explicit BTC amounts")
    return result


def _timestamp(payload: Mapping[str, Any]) -> int:
    value = payload.get("timestamp_ms")
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise FoundationError("A nonnegative integer timestamp_ms is required")
    return value


def _freeze(value: Any) -> Any:
    """Detach caller-owned payloads and reject values outside canonical JSON."""
    if isinstance(value, Mapping):
        if any(not isinstance(key, str) for key in value):
            raise FoundationError("Event payload keys must be strings")
        return MappingProxyType({key: _freeze(item) for key, item in value.items()})
    if isinstance(value, (list, tuple)):
        return tuple(_freeze(item) for item in value)
    if isinstance(value, Decimal):
        return as_decimal(value)
    if value is None or isinstance(value, (str, int, bool)):
        return value
    raise FoundationError("Event payload contains an unsupported value")


def _plain(value: Any) -> Any:
    if isinstance(value, Mapping):
        return {key: _plain(item) for key, item in value.items()}
    if isinstance(value, tuple):
        return [_plain(item) for item in value]
    return value


@dataclass(frozen=True)
class LedgerEvent:
    event_id: str
    event_type: str
    payload: Mapping[str, Any]

    def __post_init__(self) -> None:
        if not isinstance(self.event_id, str) or not self.event_id.strip():
            raise FoundationError("event_id must be a nonempty string")
        if not isinstance(self.event_type, str) or not self.event_type:
            raise FoundationError("event_type must be a nonempty string")
        if not isinstance(self.payload, Mapping):
            raise FoundationError("Event payload must be a mapping")
        object.__setattr__(self, "payload", _freeze(self.payload))

    def as_dict(self) -> Dict[str, Any]:
        return {"event_id": self.event_id, "event_type": self.event_type,
                "payload": _plain(self.payload)}

    @property
    def payload_hash(self) -> str:
        return content_hash({"event_type": self.event_type, "payload": _plain(self.payload)})


@dataclass(frozen=True)
class FuturePosition:
    amount_usd: Decimal
    inverse_entry: Decimal

    @property
    def entry_price_usd(self) -> Decimal:
        with localcontext() as context:
            context.prec = PRECISION
            return ONE / self.inverse_entry


@dataclass(frozen=True)
class JournalRecord:
    event: LedgerEvent
    payload_hash: str
    state_hash: str


@dataclass
class _State:
    cash: Decimal
    margin: Decimal = ZERO
    option_positions: Dict[str, Decimal] = field(default_factory=dict)
    future_positions: Dict[str, FuturePosition] = field(default_factory=dict)
    expired: set = field(default_factory=set)
    fees: Decimal = ZERO
    external_cashflow: Decimal = ZERO
    realized_future_pnl: Decimal = ZERO
    last_timestamp_ms: Optional[int] = None
    generated_futures: Dict[str, Decimal] = field(default_factory=dict)

    def copy(self) -> "_State":
        return _State(self.cash, self.margin, dict(self.option_positions),
                      dict(self.future_positions), set(self.expired), self.fees,
                      self.external_cashflow, self.realized_future_pnl, self.last_timestamp_ms,
                      dict(self.generated_futures))


class Ledger:
    """Append-only journal; each apply_batch publishes all changes or none.

    initial_cash_btc is explicit initial endowment, not a reported return.
    enforce_available_cash only applies a fixture cash-minus-reservation check;
    it does not certify actual derivatives margin or collateral sufficiency.
    """

    def __init__(self, specs: Mapping[str, InstrumentSpec], initial_cash_btc: Any = ZERO,
                 enforce_available_cash: bool = False, cash_quantum_btc: Any = None,
                 max_events: int = 20000) -> None:
        if not isinstance(specs, Mapping):
            raise FoundationError("specs must be an instrument-ID mapping")
        if isinstance(max_events, bool) or not isinstance(max_events, int) or not 1 <= max_events <= 20000:
            raise FoundationError("max_events must be an integer in [1, 20000]")
        if not isinstance(enforce_available_cash, bool):
            raise FoundationError("enforce_available_cash must be boolean")
        self._specs = dict(specs)
        for name, spec in self._specs.items():
            if not isinstance(spec, InstrumentSpec) or name != spec.instrument_id:
                raise FoundationError("Instrument mapping identity mismatch")
            if spec.underlying != "BTC" or spec.settlement_currency != "BTC":
                raise FoundationError("RO-01 ledger supports BTC inverse instruments only")
            expected = "BTC" if spec.kind == "option" else "USD"
            if spec.kind not in ("option", "future") or spec.amount_unit != expected or spec.quote_currency != expected:
                raise FoundationError("Unsupported inverse amount or quote currency")
        cash = _decimal(initial_cash_btc, "initial_cash_btc")
        if cash < ZERO:
            raise FoundationError("Initial endowment must be nonnegative")
        self._quantum = None if cash_quantum_btc is None else _decimal(cash_quantum_btc, "cash_quantum_btc", True)
        if self._quantum is not None and self._quantum != Decimal(1).scaleb(self._quantum.as_tuple().exponent):
            raise FoundationError("Cash quantum must be a positive power of ten")
        self._enforce_cash = enforce_available_cash
        self._metadata_hashes = {name: content_hash(spec) for name, spec in self._specs.items()}
        self._max_events = max_events
        self._state = _State(cash)
        self._journal = []  # type: list
        self._seen = {}  # type: Dict[str, str]

    @property
    def cash_btc(self) -> Decimal:
        return self._state.cash

    @property
    def reserved_margin_btc(self) -> Decimal:
        return self._state.margin

    @property
    def available_cash_btc(self) -> Decimal:
        with localcontext() as context:
            context.prec = PRECISION
            return self._state.cash - self._state.margin

    @property
    def option_positions_btc(self) -> Mapping[str, Decimal]:
        return MappingProxyType(dict(self._state.option_positions))

    @property
    def future_positions(self) -> Mapping[str, FuturePosition]:
        return MappingProxyType(dict(self._state.future_positions))

    @property
    def journal(self) -> Tuple[JournalRecord, ...]:
        return tuple(self._journal)

    @property
    def replay_events(self) -> Tuple[LedgerEvent, ...]:
        return tuple(record.event for record in self._journal)

    @property
    def state_hash(self) -> str:
        return content_hash(self.snapshot())

    @property
    def journal_hash(self) -> str:
        return content_hash([{"event": record.event.as_dict(), "payload_hash": record.payload_hash,
                              "state_hash": record.state_hash} for record in self._journal])

    def _snapshot(self, state: _State) -> Dict[str, Any]:
        return {"schema_version": 1, "cash_btc": state.cash,
                "reserved_margin_btc": state.margin,
                "option_positions_btc": dict(sorted(state.option_positions.items())),
                "future_positions": {name: {"amount_usd": position.amount_usd,
                                             "inverse_entry": position.inverse_entry}
                                     for name, position in sorted(state.future_positions.items())},
                "expired_instruments": sorted(state.expired), "fees_paid_btc": state.fees,
                "pending_exercise_future_ids": sorted(state.generated_futures),
                "exercise_settlement_prices_usd": dict(sorted(state.generated_futures.items())),
                "external_cashflow_btc": state.external_cashflow,
                "realized_future_pnl_btc": state.realized_future_pnl,
                "last_timestamp_ms": state.last_timestamp_ms,
                "cash_quantum_btc": self._quantum,
                "instrument_metadata_versions": {name: spec.metadata_version
                                                  for name, spec in sorted(self._specs.items())},
                "instrument_metadata_hashes": dict(sorted(self._metadata_hashes.items()))}

    def snapshot(self) -> Dict[str, Any]:
        return self._snapshot(self._state)

    def apply(self, event: LedgerEvent) -> bool:
        return bool(self.apply_batch((event,)))

    def apply_batch(self, events: Iterable[LedgerEvent]) -> int:
        staged = self._state.copy()
        pending = []
        seen = {}  # type: Dict[str, str]
        attempts = 0
        try:
            with localcontext() as context:
                context.prec = PRECISION
                context.rounding = ROUND_HALF_EVEN
                for event in events:
                    note_event()
                    attempts += 1
                    if attempts > self._max_events or not isinstance(event, LedgerEvent):
                        raise FoundationError("Invalid event or bounded batch size exceeded")
                    payload_hash = event.payload_hash
                    previous = seen.get(event.event_id, self._seen.get(event.event_id))
                    if previous is not None:
                        if previous != payload_hash:
                            raise FoundationError("Conflicting duplicate event_id: {}".format(event.event_id))
                        continue
                    if len(self._journal) + len(pending) >= self._max_events:
                        raise FoundationError("Journal event budget exceeded")
                    self._apply_to(staged, event)
                    pending.append(JournalRecord(event, payload_hash, content_hash(self._snapshot(staged))))
                    seen[event.event_id] = payload_hash
                if self._enforce_cash and staged.cash - staged.margin < ZERO:
                    raise FoundationError("Fixture available cash constraint violated")
        except DecimalException as error:
            raise FoundationError("Decimal ledger operation failed") from error
        self._state = staged
        self._journal.extend(pending)
        self._seen.update(seen)
        return len(pending)

    def _spec(self, instrument_id: Any, kind: str) -> InstrumentSpec:
        if not isinstance(instrument_id, str) or instrument_id not in self._specs:
            raise FoundationError("Unknown instrument")
        spec = self._specs[instrument_id]
        if spec.kind != kind:
            raise FoundationError("Instrument kind mismatch")
        return spec

    def _cash(self, state: _State, amount: Decimal) -> Decimal:
        if self._quantum is not None:
            amount = amount.quantize(self._quantum, rounding=ROUND_HALF_EVEN)
        state.cash += amount
        return amount

    def _charge(self, state: _State, amount: Decimal) -> None:
        if self._quantum is not None:
            amount = amount.quantize(self._quantum, rounding=ROUND_HALF_EVEN)
        self._cash(state, -amount)
        state.fees += amount

    def _trade_future(self, state: _State, name: str, delta: Decimal, price: Decimal) -> None:
        old = state.future_positions.get(name)
        inverse = ONE / price
        if old is None:
            state.future_positions[name] = FuturePosition(delta, inverse)
            return
        if (old.amount_usd > ZERO) == (delta > ZERO):
            total = old.amount_usd + delta
            state.future_positions[name] = FuturePosition(
                total, (old.amount_usd * old.inverse_entry + delta * inverse) / total)
            return
        closed = min(abs(old.amount_usd), abs(delta))
        signed_closed = closed if old.amount_usd > ZERO else -closed
        realized = signed_closed * (old.inverse_entry - inverse)
        state.realized_future_pnl += self._cash(state, realized)
        remaining = old.amount_usd + delta
        if remaining == ZERO:
            del state.future_positions[name]
        elif (remaining > ZERO) == (old.amount_usd > ZERO):
            state.future_positions[name] = FuturePosition(remaining, old.inverse_entry)
        else:
            state.future_positions[name] = FuturePosition(remaining, inverse)

    def _apply_to(self, state: _State, event: LedgerEvent) -> None:
        payload = event.payload
        kind = event.event_type
        timestamp = _timestamp(payload)
        if state.last_timestamp_ms is not None and timestamp < state.last_timestamp_ms:
            raise FoundationError("Ledger timestamps must not move backwards")
        if kind == "CASHFLOW":
            amount = _decimal(payload.get("amount_btc"), "amount_btc")
            state.external_cashflow += self._cash(state, amount)
        elif kind == "RESERVE_MARGIN":
            amount = _decimal(payload.get("amount_btc"), "amount_btc")
            if amount < ZERO:
                raise FoundationError("Reserved margin cannot be negative")
            state.margin = amount
        elif kind in ("OPTION_FILL", "FUTURE_FILL"):
            spec = self._spec(payload.get("instrument_id"), "option" if kind == "OPTION_FILL" else "future")
            timestamp = _timestamp(payload)
            if spec.instrument_id in state.expired or timestamp >= spec.expiration_ms:
                raise FoundationError("Trading an expired instrument is forbidden")
            side = payload.get("side")
            if side not in ("buy", "sell"):
                raise FoundationError("Fill side must be buy or sell")
            quantity = spec.validate_amount(payload.get("amount"))
            price = spec.validate_price(payload.get("price"))
            fee = _fee(payload.get("fee_btc"))
            delta = quantity if side == "buy" else -quantity
            if kind == "OPTION_FILL":
                total = state.option_positions.get(spec.instrument_id, ZERO) + delta
                if total == ZERO:
                    state.option_positions.pop(spec.instrument_id, None)
                else:
                    state.option_positions[spec.instrument_id] = total
                self._cash(state, -delta * price)
            else:
                self._trade_future(state, spec.instrument_id, delta, price)
            self._charge(state, fee)
        elif kind in ("OPTION_EXPIRY_OTM", "OPTION_EXERCISE_INTO_FUTURE"):
            self._expire_option(state, event)
        elif kind in ("FUTURE_DAILY_SETTLEMENT", "FUTURE_SETTLEMENT"):
            spec = self._spec(payload.get("instrument_id"), "future")
            timestamp = _timestamp(payload)
            if spec.instrument_id in state.expired:
                raise FoundationError("Future already expired")
            final = kind == "FUTURE_SETTLEMENT"
            if (final and timestamp < spec.expiration_ms) or (not final and timestamp >= spec.expiration_ms):
                raise FoundationError("Future settlement timestamp conflicts with its role")
            price = _decimal(payload.get("settlement_price"), "settlement_price", True)
            fee = _fee(payload.get("fee_btc"))
            if final and spec.instrument_id in state.generated_futures and fee != ZERO:
                raise FoundationError("No second delivery fee on an exercise-generated future; mixed fee schedules are outside V1")
            if final and spec.instrument_id in state.generated_futures and price != state.generated_futures[spec.instrument_id]:
                raise FoundationError("Exercise and net future must use the same settlement price")
            position = state.future_positions.get(spec.instrument_id)
            if position is not None:
                realized = position.amount_usd * (position.inverse_entry - ONE / price)
                state.realized_future_pnl += self._cash(state, realized)
                if final:
                    del state.future_positions[spec.instrument_id]
                else:
                    state.future_positions[spec.instrument_id] = FuturePosition(position.amount_usd, ONE / price)
            elif fee != ZERO:
                raise FoundationError("Cannot charge settlement fee without a position")
            self._charge(state, fee)
            if final:
                state.expired.add(spec.instrument_id)
                state.generated_futures.pop(spec.instrument_id, None)
        else:
            raise FoundationError("Unsupported ledger event type: {}".format(kind))
        if timestamp is not None:
            state.last_timestamp_ms = timestamp

    def _expire_option(self, state: _State, event: LedgerEvent) -> None:
        payload = event.payload
        option = self._spec(payload.get("option_id"), "option")
        if _timestamp(payload) < option.expiration_ms or option.expiration_ms < TWO_STAGE_START_MS:
            raise FoundationError("Unsupported or premature option settlement")
        if payload.get("settlement_convention") != SETTLEMENT_CONVENTION:
            raise FoundationError("Explicit supported settlement convention is required")
        quantity = state.option_positions.get(option.instrument_id, ZERO)
        if option.instrument_id in state.expired or quantity == ZERO:
            raise FoundationError("No unexpired option position to settle")
        price = _decimal(payload.get("settlement_price"), "settlement_price", True)
        strike = _decimal(option.strike, "strike", True)
        itm = price > strike if option.option_type == "call" else price < strike
        if option.option_type not in ("call", "put"):
            raise FoundationError("Unsupported option type")
        expected = "OPTION_EXERCISE_INTO_FUTURE" if itm else "OPTION_EXPIRY_OTM"
        if event.event_type != expected:
            raise FoundationError("Option expiry event disagrees with intrinsic value")
        fee = _fee(payload.get("fee_btc"))
        if not itm and fee != ZERO:
            raise FoundationError("OTM expiry cannot carry an ITM delivery fee")
        if itm:
            future = self._spec(payload.get("future_id"), "future")
            if future.expiration_ms != option.expiration_ms or future.instrument_id in state.expired:
                raise FoundationError("Option exercise requires an unexpired same-expiry future")
            if future.instrument_id in state.generated_futures and price != state.generated_futures[future.instrument_id]:
                raise FoundationError("Same-expiry exercises must use the same settlement price")
            delta = quantity * strike * (ONE if option.option_type == "call" else -ONE)
            # Exercise-generated quantities/prices are contractual, not order-lot/tick constrained.
            self._trade_future(state, future.instrument_id, delta, strike)
            state.generated_futures[future.instrument_id] = price
        del state.option_positions[option.instrument_id]
        state.expired.add(option.instrument_id)
        self._charge(state, fee)

    def settle_option_expiry(self, event_id: str, option_id: str, future_id: str,
                             settlement_price: Any, *, timestamp_ms: int,
                             option_delivery_fee_btc: Any = ZERO,
                             future_delivery_fee_btc: Any = ZERO) -> int:
        """Atomically expire one option and settle its net expiry future.

        Both helper event IDs and payloads are deterministic, allowing a retry
        after the position has been removed. This fixture helper charges the
        explicitly supplied option delivery fee once. A second delivery fee on
        the generated future is rejected; it does not implement the venue fee
        schedule for a separately pre-existing residual futures hedge. For
        several options of one expiry, apply_batch must contain every exercise
        first, followed by one settlement of the net future; this single-option
        helper refuses to strand other open options of the same expiry.
        """
        option = self._spec(option_id, "option")
        price = _decimal(settlement_price, "settlement_price", True)
        fee = _fee(option_delivery_fee_btc)
        if _fee(future_delivery_fee_btc) != ZERO:
            raise FoundationError("Exercise-generated future must not pay a second delivery fee")
        if not isinstance(event_id, str) or not event_id.strip():
            raise FoundationError("Settlement event_id must be nonempty")
        strike = _decimal(option.strike, "strike", True)
        itm = price > strike if option.option_type == "call" else price < strike
        if itm and event_id + ":option" not in self._seen:
            others = [name for name in self._state.option_positions
                      if name != option_id and self._specs[name].expiration_ms == option.expiration_ms]
            if others:
                raise FoundationError("Use a batch of all same-expiry exercises before net future settlement")
        payload = {"option_id": option_id, "future_id": future_id, "settlement_price": price,
                   "timestamp_ms": timestamp_ms, "fee_btc": fee,
                   "settlement_convention": SETTLEMENT_CONVENTION}
        first = LedgerEvent(event_id + ":option", "OPTION_EXERCISE_INTO_FUTURE" if itm else "OPTION_EXPIRY_OTM", payload)
        if not itm:
            return self.apply_batch((first,))
        second = LedgerEvent(event_id + ":future", "FUTURE_SETTLEMENT",
                             {"instrument_id": future_id, "settlement_price": price,
                              "timestamp_ms": timestamp_ms, "fee_btc": ZERO})
        return self.apply_batch((first, second))

    def equity_btc(self, option_marks_btc: Mapping[str, Any],
                   future_marks_usd: Mapping[str, Any]) -> Decimal:
        """Value every open position; missing marks fail instead of becoming zero."""
        if not isinstance(option_marks_btc, Mapping) or not isinstance(future_marks_usd, Mapping):
            raise FoundationError("Marks must be instrument-ID mappings")
        with localcontext() as context:
            context.prec = PRECISION
            total = self._state.cash
            for name, quantity in self._state.option_positions.items():
                if name not in option_marks_btc:
                    raise FoundationError("Missing option mark: {}".format(name))
                mark = _decimal(option_marks_btc[name], "option mark")
                if mark < ZERO:
                    raise FoundationError("Option marks cannot be negative")
                total += quantity * mark
            for name, position in self._state.future_positions.items():
                if name not in future_marks_usd:
                    raise FoundationError("Missing future mark: {}".format(name))
                mark = _decimal(future_marks_usd[name], "future mark", True)
                total += position.amount_usd * (position.inverse_entry - ONE / mark)
            return total
