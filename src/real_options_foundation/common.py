"""Exact units, immutable metadata, canonical serialization and bounded work."""

from dataclasses import dataclass, fields, is_dataclass
from decimal import Decimal, InvalidOperation, localcontext
import hashlib
import json
from types import MappingProxyType
from typing import Any, Mapping, Optional
import time


class FoundationError(ValueError):
    """A contract, causal, resource or integrity requirement failed."""


def as_decimal(value: Any) -> Decimal:
    if isinstance(value, (bool, float)) or not isinstance(value, (str, int, Decimal)):
        raise FoundationError("Contract values must be Decimal, integer or decimal string")
    try:
        result = Decimal(value)
    except (InvalidOperation, ValueError) as exc:
        raise FoundationError("Invalid decimal value") from exc
    if not result.is_finite():
        raise FoundationError("Nonfinite contract value")
    return result


def integer(value: Any, name: str, minimum: int = 0) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < minimum:
        raise FoundationError("{} must be an integer >= {}".format(name, minimum))
    return value


def decimal_text(value: Decimal) -> str:
    value = as_decimal(value)
    if value == 0:
        return "0"
    text = format(value, "f")
    return text.rstrip("0").rstrip(".") if "." in text else text


def ordinary(value: Any) -> Any:
    """Normalize recursive read-only mappings without copying through asdict."""
    if isinstance(value, Mapping):
        if any(not isinstance(key, str) for key in value):
            raise FoundationError("JSON mapping keys must be strings")
        return {key: ordinary(child) for key, child in value.items()}
    if is_dataclass(value) and not isinstance(value, type):
        return {field.name: ordinary(getattr(value, field.name)) for field in fields(value)}
    if isinstance(value, (tuple, list)):
        return [ordinary(child) for child in value]
    if isinstance(value, Decimal):
        return decimal_text(value)
    if value is None or isinstance(value, (str, bool, int)):
        return value
    raise FoundationError("Unsupported or inexact JSON value: {}".format(type(value).__name__))


def freeze(value: Any) -> Any:
    normalized = ordinary(value)
    if isinstance(normalized, dict):
        return MappingProxyType({key: freeze(child) for key, child in normalized.items()})
    if isinstance(normalized, list):
        return tuple(freeze(child) for child in normalized)
    return normalized


def canonical_json_bytes(value: Any) -> bytes:
    return json.dumps(ordinary(value), ensure_ascii=False, sort_keys=True,
                      separators=(",", ":"), allow_nan=False).encode("utf-8")


def content_hash(value: Any) -> str:
    return hashlib.sha256(canonical_json_bytes(value)).hexdigest()


@dataclass
class WorkBudget:
    max_events: int = 20000
    max_cpu_seconds: int = 60
    operations: int = 0
    started_cpu: float = 0.0

    def __post_init__(self) -> None:
        integer(self.max_events, "max_events", 1)
        integer(self.max_cpu_seconds, "max_cpu_seconds", 1)
        self.started_cpu = time.process_time()

    def check(self) -> None:
        if self.operations > self.max_events:
            raise FoundationError("Event operation budget exceeded")
        if time.process_time() - self.started_cpu > self.max_cpu_seconds:
            raise FoundationError("CPU budget exceeded")


_budget: Optional[WorkBudget] = None


def set_work_budget(budget: Optional[WorkBudget]) -> None:
    global _budget
    _budget = budget


def note_event() -> None:
    if _budget is not None:
        _budget.operations += 1
        _budget.check()


@dataclass(frozen=True)
class InstrumentSpec:
    instrument_id: str
    kind: str
    quote_currency: str
    amount_unit: str
    contract_size: Decimal
    min_amount: Decimal
    amount_step: Decimal
    tick_size: Decimal
    expiration_ms: int
    metadata_version: str
    source_payload: Mapping[str, Any]
    underlying: str = "BTC"
    settlement_currency: str = "BTC"
    strike: Optional[Decimal] = None
    option_type: Optional[str] = None

    def __post_init__(self) -> None:
        for name in ("instrument_id", "metadata_version"):
            value = getattr(self, name)
            if not isinstance(value, str) or not value.strip():
                raise FoundationError("Missing {}".format(name))
        if self.underlying != "BTC" or self.settlement_currency != "BTC":
            raise FoundationError("RO-01 supports BTC-settled inverse instruments only")
        if self.kind not in {"option", "future"}:
            raise FoundationError("Unsupported instrument family")
        native = "BTC" if self.kind == "option" else "USD"
        if self.quote_currency != native or self.amount_unit != native:
            raise FoundationError("Inconsistent quote/amount units for inverse instrument")
        for name in ("contract_size", "min_amount", "amount_step", "tick_size"):
            value = as_decimal(getattr(self, name))
            if value <= 0:
                raise FoundationError("{} must be positive".format(name))
            object.__setattr__(self, name, value)
        integer(self.expiration_ms, "expiration_ms", 1)
        if self.kind == "option":
            if self.option_type not in {"call", "put"} or self.strike is None:
                raise FoundationError("Option strike/type are mandatory")
            strike = as_decimal(self.strike)
            if strike <= 0 or self.contract_size != Decimal(1):
                raise FoundationError("Invalid inverse option strike/multiplier")
            object.__setattr__(self, "strike", strike)
        elif self.strike is not None or self.option_type is not None:
            raise FoundationError("Future metadata must not carry option strike/type")
        if not isinstance(self.source_payload, Mapping) or not self.source_payload:
            raise FoundationError("Original instrument metadata must be preserved")
        object.__setattr__(self, "source_payload", freeze(self.source_payload))

    def validate_amount(self, amount: Any) -> Decimal:
        result = as_decimal(amount)
        try:
            with localcontext() as context:
                context.prec = 50
                if result < self.min_amount or result % self.amount_step:
                    raise FoundationError("Amount violates minimum/step")
        except InvalidOperation as exc:
            raise FoundationError("Amount exceeds technical decimal precision") from exc
        return result

    def validate_price(self, price: Any) -> Decimal:
        result = as_decimal(price)
        try:
            with localcontext() as context:
                context.prec = 50
                if result <= 0 or result % self.tick_size:
                    raise FoundationError("Price violates positive tick grid")
        except InvalidOperation as exc:
            raise FoundationError("Price exceeds technical decimal precision") from exc
        return result
