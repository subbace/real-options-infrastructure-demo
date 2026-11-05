"""Artificial requirement tests; no acquired data, models or network."""

from dataclasses import replace
from decimal import Decimal
import io
import json
from pathlib import Path
import tempfile
from types import MappingProxyType
import unittest

from src.real_options_foundation.adapter import OfflinePublicAdapter, decode_message, normalize_book_message
from src.real_options_foundation.common import FoundationError, InstrumentSpec, canonical_json_bytes, content_hash
from src.real_options_foundation.events import EventEnvelope, causal_latest
from src.real_options_foundation.journal import DurableJournal, validate_journal


def fixture_spec():
    return InstrumentSpec(instrument_id="BTC-FIXTURE-C", kind="option", quote_currency="BTC",
        amount_unit="BTC", contract_size="1", min_amount="0.1", amount_step="0.1",
        tick_size="0.001", expiration_ms=4000000000000, metadata_version="artificial-v1",
        source_payload={"artificial_fixture": True}, strike="100000", option_type="call")


def fixture_event(**updates):
    defaults = dict(source="deribit", connection_id="fixture-connection", ingest_sequence=1,
        channel="book.BTC-FIXTURE-C.100ms", instrument_id="BTC-FIXTURE-C",
        exchange_timestamp_ms=1000, receive_timestamp_ms=1001,
        receive_monotonic_ns=1001000000, event_id="fixture-1", event_type="book_snapshot",
        payload={"change_id": 1, "bids": [["new", "0.01", "1"]], "asks": [["new", "0.02", "1"]]})
    defaults.update(updates)
    return EventEnvelope(**defaults)


class FoundationTests(unittest.TestCase):
    def test_d11_metadata_hash_binds_provenance_and_immutable_source(self):
        original = {"artificial_fixture": True, "source_version": "example-only"}
        spec = replace(fixture_spec(), source_payload=original)
        before = content_hash(spec)
        original["source_version"] = "modified"
        self.assertEqual(content_hash(spec), before)
        changed = replace(spec, source_payload=original)
        self.assertNotEqual(content_hash(changed), before)
        self.assertTrue(spec.source_payload["artificial_fixture"])

    def test_d06_d07_d08_integrated_fill_hedge_expiry_reconciles(self):
        from src.real_options_foundation.book import L2Book
        from src.real_options_foundation.ledger import Ledger, LedgerEvent
        expiry = 4000000000000
        option = replace(fixture_spec(), strike=Decimal("100"))
        future = InstrumentSpec(instrument_id="BTC-FIXTURE-F", kind="future", quote_currency="USD",
            amount_unit="USD", contract_size="10", min_amount="10", amount_step="10",
            tick_size="1", expiration_ms=expiry, metadata_version="artificial-v1",
            source_payload={"artificial_fixture": True})
        books = {option.instrument_id: L2Book(option), future.instrument_id: L2Book(future)}
        books[option.instrument_id].apply(fixture_event())
        # Artificial premium 0.02 BTC, one unit; no real data or strategy gain.
        option_fill = books[option.instrument_id].execute_taker("buy", "1", decision_timestamp_ms=1002,
            decision_monotonic_ns=1002000000, max_transport_age_ms=2)
        books[future.instrument_id].apply(fixture_event(instrument_id=future.instrument_id,
            channel="book.BTC-FIXTURE-F.100ms", event_id="future-book", payload={"change_id": 1,
            "bids": [["new", "100", "100"]], "asks": [["new", "101", "100"]]}))
        hedge = books[future.instrument_id].execute_taker("sell", "100", decision_timestamp_ms=1002,
            decision_monotonic_ns=1002000000, max_transport_age_ms=2)
        ledger = Ledger({option.instrument_id: option, future.instrument_id: future}, initial_cash_btc="1")
        for identity, kind, fill, fee in (("option", "OPTION_FILL", option_fill, "0.001"),
                                         ("hedge", "FUTURE_FILL", hedge, "0.001")):
            # Send each depth level to the ledger, not arithmetic VWAP as inverse basis.
            for index, (price, amount) in enumerate(fill.levels):
                ledger.apply(LedgerEvent(identity + str(index), kind, {"instrument_id": fill.instrument_id,
                    "side": fill.side, "amount": amount, "price": price, "fee_btc": fee, "timestamp_ms": 1002}))
        ledger.settle_option_expiry("expiry", option.instrument_id, future.instrument_id, "200",
            timestamp_ms=expiry, option_delivery_fee_btc="0.002")
        self.assertEqual(ledger.cash_btc, Decimal("0.976"))
        self.assertEqual(dict(ledger.option_positions_btc), {})
        self.assertEqual(dict(ledger.future_positions), {})
        self.assertEqual(ledger.equity_btc({}, {}), ledger.cash_btc)
        replay = Ledger({option.instrument_id: option, future.instrument_id: future}, initial_cash_btc="1")
        replay.apply_batch(ledger.replay_events)
        self.assertEqual(replay.state_hash, ledger.state_hash)
        self.assertEqual(replay.journal_hash, ledger.journal_hash)

    def test_d01_units_and_contract_metadata(self):
        spec = fixture_spec()
        for changes in ({"kind": "perpetual"}, {"amount_unit": "USD"}, {"quote_currency": "USD"},
                        {"source_payload": {}}, {"strike": None}, {"contract_size": "2"}):
            with self.assertRaises(FoundationError):
                replace(spec, **changes)
        for amount in (True, 0.1, "NaN", "0", "0.15"):
            with self.assertRaises(FoundationError):
                spec.validate_amount(amount)

    def test_d09_recursive_readonly_payload_canonicalization(self):
        payload = MappingProxyType({"nested": MappingProxyType({"decimal": Decimal("1.00"), "items": (1, 2)})})
        self.assertEqual(json.loads(canonical_json_bytes(payload)), {"nested": {"decimal": "1", "items": [1, 2]}})
        original = {"levels": [["new", "0.1", "1"]]}
        event = fixture_event(payload=original)
        before = event.event_hash
        original["levels"][0][1] = "999"
        self.assertEqual(event.event_hash, before)
        with self.assertRaises(TypeError):
            event.payload["new"] = "corrupt"

    def test_d04_availability_type_instrument_and_staleness(self):
        now = fixture_event(event_type="provider_greeks")
        future = replace(now, event_id="future", receive_timestamp_ms=1010, receive_monotonic_ns=1010000000)
        other = replace(now, event_id="other", instrument_id="BTC-OTHER", receive_monotonic_ns=1001500000)
        args = dict(decision_timestamp_ms=1002, decision_monotonic_ns=1002000000,
                    max_age_ms=1, event_type="provider_greeks", instrument_id=now.instrument_id)
        self.assertEqual(causal_latest([now, future, other], **args), now)
        with self.assertRaises(FoundationError):
            causal_latest([now], **dict(args, max_age_ms=0))
        with self.assertRaises(FoundationError):
            causal_latest([replace(now, exchange_timestamp_ms=None)], **dict(args, max_exchange_age_ms=2))
        with self.assertRaises(FoundationError):
            causal_latest([now], **dict(args, event_type="trade"))
        with self.assertRaises(FoundationError):
            causal_latest([replace(now, exchange_timestamp_ms=1003)], **args)

    def test_d05_decode_decimal_without_binary_float_and_strict_keys(self):
        decoded = decode_message('{"price": 0.100000000000000001}')
        self.assertEqual(decoded["price"], "0.100000000000000001")
        for raw in ('{"a":1,"a":2}', '{"a":NaN}', '[1,2]', '{bad', {"a": 0.1}):
            with self.assertRaises(FoundationError):
                decode_message(raw)

    def test_d02_adapter_snapshot_normalizes_official_shape(self):
        raw = {"method": "subscription", "params": {"channel": "book.BTC-FIXTURE-C.100ms",
               "data": {"instrument_name": "BTC-FIXTURE-C", "type": "snapshot", "timestamp": 1000,
                        "change_id": 1, "bids": [["new", "0.01", "1"]], "asks": [["new", "0.02", "1"]]}}}
        args = dict(connection_id="c", ingest_sequence=0, receive_timestamp_ms=1001, receive_monotonic_ns=1001000000)
        event = normalize_book_message(raw, **args)
        self.assertEqual(event.event_type, "book_snapshot")
        self.assertEqual(event.payload["change_id"], 1)
        duplicate = normalize_book_message(raw, **dict(args, receive_timestamp_ms=1002))
        self.assertEqual(event.identity_hash, duplicate.identity_hash)
        raw["params"]["channel"] = "book.BTC-FIXTURE-C.raw"
        with self.assertRaises(FoundationError):
            normalize_book_message(raw, **args)

    def test_d10_bounded_timeout_and_throttling(self):
        pauses = []
        outcomes = [TimeoutError(), {"error": {"code": 10028}}, {"result": {"artificial": True}}]
        def transport(method, params):
            value = outcomes.pop(0)
            if isinstance(value, Exception):
                raise value
            return value
        adapter = OfflinePublicAdapter(transport, max_attempts=3, pause=pauses.append)
        self.assertTrue(adapter.request("public/get_order_book", {"instrument_name": "BTC-FIXTURE-C"})["artificial"])
        self.assertEqual(pauses, [1, 2])
        self.assertEqual(adapter.request_count, 3)
        self.assertEqual(len(adapter.faults), 2)
        stopped = OfflinePublicAdapter(lambda *args: (_ for _ in ()).throw(TimeoutError()), max_attempts=2)
        with self.assertRaises(FoundationError):
            stopped.request("public/get_instruments", {"currency": "BTC"})
        self.assertEqual(stopped.request_count, 2)

    def test_d12_private_credentials_and_unconfigured_network_rejected(self):
        adapter = OfflinePublicAdapter()
        for method, params in (("private/buy", {}), ("public/auth", {}),
                               ("public/ticker", {"instrument_name": "BTC-X", "access_token": "fixture"}),
                               ("public/get_instruments", {"currency": "BTC"})):
            with self.assertRaises(FoundationError):
                adapter.request(method, params)
        self.assertEqual(adapter.request_count, 0)

    def test_d09_durable_chain_and_idempotence(self):
        with tempfile.TemporaryDirectory(prefix="ro01_artificial_") as temp:
            path = Path(temp) / "events.jsonl"
            journal = DurableJournal(path)
            try:
                self.assertTrue(journal.append("a", {"fixture": True, "amount": Decimal("0.1")}))
                self.assertFalse(journal.append("a", {"fixture": True, "amount": Decimal("0.10")}))
                with self.assertRaises(FoundationError):
                    journal.append("a", {"amount": "9"})
                self.assertTrue(journal.append("b", {"fixture": True}))
                expected = journal.journal_hash
            finally:
                journal.close()
            self.assertEqual(validate_journal(path), {"records": 2, "journal_hash": expected})
            path.write_bytes(path.read_bytes()[:-1])
            with self.assertRaises(FoundationError):
                validate_journal(path)

    def test_d10_failed_durable_write_stops_sink(self):
        class FullDisk(io.BytesIO):
            def write(self, data):
                raise OSError("Artificial disk full")
        journal = DurableJournal(Path("unused-artificial-path"), opener=lambda *args: FullDisk())
        before = journal.journal_hash
        try:
            with self.assertRaises(FoundationError):
                journal.append("a", {"fixture": True})
            self.assertEqual(journal.journal_hash, before)
            self.assertTrue(journal.failed)
            with self.assertRaises(FoundationError):
                journal.append("b", {"fixture": True})
        finally:
            journal.close()


if __name__ == "__main__":
    unittest.main()
