"""Hand-calculated, artificial offline fixtures for RO-01 L2 gates.

These examples are protocol tests, not market observations or trajectories.
"""

from dataclasses import FrozenInstanceError, replace
from decimal import Decimal, localcontext
import unittest

from src.real_options_foundation.book import L2Book
from src.real_options_foundation.common import FoundationError, InstrumentSpec
from src.real_options_foundation.events import EventEnvelope


D = Decimal


def option_spec():
    return InstrumentSpec(
        kind="option", instrument_id="BTC-30OCT26-100000-C", underlying="BTC",
        settlement_currency="BTC", quote_currency="BTC", amount_unit="BTC",
        contract_size=D("1"), min_amount=D("0.1"), amount_step=D("0.1"),
        tick_size=D("0.0001"), expiration_ms=1793347200000,
        strike=D("100000"), option_type="call", metadata_version="fixture-v1",
        source_payload={"fixture": "ARTIFICIAL_NOT_MARKET_DATA"},
    )


def event(spec, number=1, event_type="book_snapshot", payload=None,
          connection="connection-a", receive_ms=1000, mono_ns=1000000000,
          exchange_ms=990, channel=None):
    if payload is None:
        payload = {"change_id": 10, "prev_change_id": None,
                   "bids": [["new", "0.0090", "0.2"],
                            ["new", "0.0080", "0.3"]],
                   "asks": [["new", "0.0110", "0.1"],
                            ["new", "0.0120", "0.3"]]}
    if channel is None:
        channel = ("book.%s.100ms" % spec.instrument_id
                   if event_type.startswith("book_") else "transport")
    return EventEnvelope(
        schema_version=1, source="deribit", connection_id=connection,
        ingest_sequence=number, channel=channel, instrument_id=spec.instrument_id,
        exchange_timestamp_ms=exchange_ms, receive_timestamp_ms=receive_ms,
        receive_monotonic_ns=mono_ns, event_id="fixture-event-%s" % number,
        event_type=event_type, payload=payload,
    )


class RealOptionsBookTests(unittest.TestCase):
    def setUp(self):
        self.spec = option_spec()
        self.book = L2Book(self.spec)

    def apply_snapshot(self):
        initial = event(self.spec)
        self.book.apply(initial)
        return initial

    def quote(self, **kwargs):
        params = dict(decision_timestamp_ms=1100,
                      decision_monotonic_ns=1100000000,
                      max_transport_age_ms=100)
        params.update(kwargs)
        return self.book.quote(**params)

    def execute(self, side="buy", amount="0.2", **kwargs):
        params = dict(decision_timestamp_ms=1100,
                      decision_monotonic_ns=1100000000,
                      max_transport_age_ms=100)
        params.update(kwargs)
        return self.book.execute_taker(side, amount, **params)

    def test_d02_snapshot_is_sorted_immutable_full_replacement(self):
        self.apply_snapshot()
        first = self.book.snapshot()
        self.assertEqual(first.bids, ((D("0.0090"), D("0.2")),
                                      (D("0.0080"), D("0.3"))))
        with self.assertRaises(FrozenInstanceError):
            first.change_id = 99
        self.book.apply(event(self.spec, 2, payload={
            "change_id": 20, "bids": [["new", "0.0070", "0.1"]], "asks": []}))
        self.assertEqual(self.book.snapshot().bids, ((D("0.0070"), D("0.1")),))
        self.assertEqual(self.book.snapshot().asks, ())
        self.assertEqual(first.asks[0], (D("0.0110"), D("0.1")))

    def test_d02_change_delete_insert_are_absolute_and_atomic(self):
        self.apply_snapshot()
        self.book.apply(event(self.spec, 2, "book_change", {
            "change_id": 11, "prev_change_id": 10,
            "bids": [["change", "0.0090", "0.4"],
                     ["delete", "0.0080", "0"], ["new", "0.0070", "0.1"]],
            "asks": []}))
        self.assertEqual(self.book.snapshot().bids,
                         ((D("0.0090"), D("0.4")), (D("0.0070"), D("0.1"))))
        before = self.book.snapshot()
        with self.assertRaises(FoundationError):
            self.book.apply(event(self.spec, 3, "book_change", {
                "change_id": 12, "prev_change_id": 11,
                "bids": [["change", "0.0090", "0.5"]],
                "asks": [["new", "0.0120", "0.2"]]}))
        self.assertFalse(self.book.valid)
        self.assertEqual(self.book.snapshot().bids, before.bids)

    def test_d03_gap_reorder_and_resnapshot(self):
        for new_id, previous in ((12, 11), (9, 10)):
            with self.subTest(change_id=new_id):
                book = L2Book(self.spec)
                book.apply(event(self.spec))
                with self.assertRaises(FoundationError):
                    book.apply(event(self.spec, 2, "book_change", {
                        "change_id": new_id, "prev_change_id": previous,
                        "bids": [], "asks": []}))
                with self.assertRaises(FoundationError):
                    book.quote(decision_timestamp_ms=1100,
                               decision_monotonic_ns=1100000000,
                               max_transport_age_ms=100)
                book.apply(event(self.spec, 3))
                self.assertTrue(book.valid)

    def test_d02_ordered_batch_can_remove_and_recreate_a_level(self):
        self.apply_snapshot()
        self.book.apply(event(self.spec, 2, "book_change", {
            "change_id": 11, "prev_change_id": 10,
            "bids": [["delete", "0.0090", "0.2"],
                     ["new", "0.0090", "0.4"]], "asks": []}))
        self.assertEqual(self.book.snapshot().bids[0], (D("0.0090"), D("0.4")))

    def test_d03_identical_duplicate_does_not_refresh_transport(self):
        initial = self.apply_snapshot()
        before = self.book.state_hash
        repeated = replace(initial, receive_timestamp_ms=5000,
                           receive_monotonic_ns=5000000000)
        self.assertFalse(self.book.apply(repeated))
        self.assertEqual(self.book.state_hash, before)
        with self.assertRaises(FoundationError):
            self.quote(decision_timestamp_ms=5000,
                       decision_monotonic_ns=5000000000)

    def test_d03_conflicting_identity_invalidates_without_partial_mutation(self):
        initial = self.apply_snapshot()
        levels = self.book.snapshot().bids
        with self.assertRaises(FoundationError):
            self.book.apply(replace(initial, payload={"change_id": 11,
                                                     "bids": [], "asks": []}))
        self.assertEqual(self.book.snapshot().bids, levels)
        self.assertFalse(self.book.valid)
        self.book.apply(event(self.spec, 2))
        self.assertTrue(self.book.valid)

    def test_d03_reconnect_requires_snapshot_and_old_connection_is_rejected(self):
        self.apply_snapshot()
        with self.assertRaises(FoundationError):
            self.book.apply(event(self.spec, 2, "book_change", {
                "change_id": 11, "prev_change_id": 10, "bids": [], "asks": []},
                connection="connection-b"))
        self.book.apply(event(self.spec, 3, connection="connection-b"))
        self.assertTrue(self.book.valid)
        with self.assertRaises(FoundationError):
            self.book.apply(event(self.spec, 4))

    def test_d03_snapshot_cannot_move_backwards_on_same_connection(self):
        self.apply_snapshot()
        with self.assertRaises(FoundationError):
            self.book.apply(event(self.spec, 2, payload={
                "change_id": 9, "bids": [], "asks": []}))

    def test_d03_disconnect_and_heartbeat_do_not_restore_validity(self):
        self.apply_snapshot()
        self.book.apply(event(self.spec, 2, "disconnect", {}))
        self.book.apply(event(self.spec, 3, "heartbeat", {}))
        self.assertFalse(self.book.valid)
        with self.assertRaises(FoundationError):
            self.quote()

    def test_d04_utc_rollback_allowed_monotonic_decrease_rejected(self):
        self.apply_snapshot()
        self.book.apply(event(self.spec, 2, "book_change", {
            "change_id": 11, "prev_change_id": 10, "bids": [], "asks": []},
            receive_ms=900, mono_ns=1010000000))
        self.assertTrue(self.book.valid)
        self.quote()
        with self.assertRaises(FoundationError):
            self.book.apply(event(self.spec, 3, "heartbeat", {},
                                  receive_ms=1100, mono_ns=1000000001))
        self.assertFalse(self.book.valid)

    def test_d04_receive_exchange_and_monotonic_causality(self):
        self.apply_snapshot()
        for params in ({"decision_timestamp_ms": 999},
                       {"decision_monotonic_ns": 999999999}):
            with self.subTest(params=params), self.assertRaises(FoundationError):
                self.quote(**params)
        book = L2Book(self.spec)
        book.apply(event(self.spec, exchange_ms=1200))
        with self.assertRaises(FoundationError):
            book.quote(decision_timestamp_ms=1100, decision_monotonic_ns=1100000000,
                       max_transport_age_ms=100)

    def test_d04_missing_exchange_time_is_not_invented(self):
        with self.assertRaises(FoundationError):
            self.book.apply(event(self.spec, exchange_ms=None))
        self.assertFalse(self.book.valid)
        self.book.apply(event(self.spec, 2))
        self.book.apply(event(self.spec, 3, "heartbeat", {}, exchange_ms=None))
        self.assertTrue(self.book.valid)

    def test_d04_heartbeat_liveness_is_separate_from_unchanged_quote_age(self):
        self.apply_snapshot()
        self.book.apply(event(self.spec, 2, "heartbeat", {},
                              receive_ms=2000, mono_ns=2000000000))
        fresh = self.quote(decision_timestamp_ms=2100,
                           decision_monotonic_ns=2100000000)
        self.assertEqual(fresh.best_ask, D("0.0110"))
        with self.assertRaises(FoundationError):
            self.quote(decision_timestamp_ms=2100, decision_monotonic_ns=2100000001)
        with self.assertRaises(FoundationError):
            self.quote(decision_timestamp_ms=2100, decision_monotonic_ns=2100000000,
                       max_book_age_ms=1000)

    def test_d01_d05_malformed_and_non_executable_events_fail_closed(self):
        invalid = [
            {"change_id": 20, "bids": [["new", "0.0090", "-0.1"]], "asks": []},
            {"change_id": 20, "bids": [["new", "0.00901", "0.1"]], "asks": []},
            {"change_id": 20, "bids": [["new", "0.0090", "0.15"]], "asks": []},
            {"change_id": 20, "bids": [["new", "0.0090"]], "asks": []},
            {"change_id": 20, "bids": [["new", "0.0090", "0.1"],
                                         ["new", "0.0090", "0.2"]], "asks": []},
            {"change_id": 20, "bids": [["new", "0.0120", "0.1"]],
             "asks": [["new", "0.0110", "0.1"]]},
            {"change_id": 20, "bids": [["new", "0.0110", "0.1"]],
             "asks": [["new", "0.0110", "0.1"]]},
            {"change_id": 20, "bids": [], "asks": "invalid"},
        ]
        for payload in invalid:
            with self.subTest(payload=payload):
                book = L2Book(self.spec)
                book.apply(event(self.spec))
                with self.assertRaises(FoundationError):
                    book.apply(event(self.spec, 2, payload=payload))
                self.assertFalse(book.valid)
        for event_type in ("trade", "mark", "provider_greeks"):
            with self.subTest(event_type=event_type), self.assertRaises(FoundationError):
                self.book.apply(event(self.spec, event_type=event_type, payload={}))

    def test_d06_taker_buy_walks_asks_and_sell_walks_bids(self):
        self.apply_snapshot()
        buy = self.execute()
        self.assertEqual(buy.levels, ((D("0.0110"), D("0.1")),
                                     (D("0.0120"), D("0.1"))))
        self.assertEqual(buy.quote_amount, D("0.00230"))
        self.assertEqual(buy.average_price, D("0.0115"))
        self.assertTrue(buy.spread_included)
        self.assertFalse(buy.partial)
        self.book.apply(event(self.spec, 2))
        sell = self.execute("sell", "0.3")
        self.assertEqual(sell.levels, ((D("0.0090"), D("0.2")),
                                      (D("0.0080"), D("0.1"))))
        self.assertEqual(sell.quote_amount, D("0.00260"))

    def test_d06_partial_and_rejected_orders_never_invent_depth(self):
        self.apply_snapshot()
        before = self.book.state_hash
        with self.assertRaises(FoundationError):
            self.execute(amount="0.5")
        self.assertEqual(before, self.book.state_hash)
        partial = self.execute(amount="0.5", allow_partial=True)
        self.assertEqual(partial.filled_amount, D("0.4"))
        self.assertEqual(partial.unfilled_amount, D("0.1"))
        self.assertEqual(partial.quote_amount, D("0.00470"))
        self.assertTrue(partial.partial)

    def test_d06_no_depth_reuse_even_after_delta_or_heartbeat(self):
        self.apply_snapshot()
        self.execute()
        for _ in range(2):
            with self.assertRaises(FoundationError):
                self.execute()
        self.book.apply(event(self.spec, 2, "book_change", {
            "change_id": 11, "prev_change_id": 10, "bids": [], "asks": []}))
        self.book.apply(event(self.spec, 3, "heartbeat", {}))
        with self.assertRaises(FoundationError):
            self.execute()
        self.book.apply(event(self.spec, 4, payload={
            "change_id": 20, "bids": [["new", "0.0090", "0.2"]],
            "asks": [["new", "0.0110", "0.1"], ["new", "0.0120", "0.3"]]}))
        self.assertEqual(self.execute().filled_amount, D("0.2"))

    def test_d06_empty_side_has_no_fabricated_fill(self):
        self.book.apply(event(self.spec, payload={
            "change_id": 10, "bids": [], "asks": []}))
        self.assertIsNone(self.quote().best_bid)
        self.assertIsNone(self.quote().best_ask)
        with self.assertRaises(FoundationError):
            self.execute(allow_partial=True)

    def test_d06_invalid_order_size_or_side_does_not_claim_liquidity(self):
        self.apply_snapshot()
        before = self.book.state_hash
        for side, amount in (("maker", "0.1"), ("buy", "0.15"),
                             ("buy", "0"), ("buy", "-0.1")):
            with self.subTest(side=side, amount=amount), self.assertRaises(FoundationError):
                self.execute(side=side, amount=amount)
        self.assertEqual(self.book.state_hash, before)

    def test_d01_d06_native_inverse_future_ticks_and_amounts(self):
        spec = InstrumentSpec(
            kind="future", instrument_id="BTC-30OCT26", underlying="BTC",
            settlement_currency="BTC",
            quote_currency="USD", amount_unit="USD", contract_size=D("10"),
            min_amount=D("10"), amount_step=D("10"), tick_size=D("2.5"),
            expiration_ms=1793347200000, strike=None, option_type=None,
            metadata_version="fixture-v1", source_payload={"fixture": True})
        book = L2Book(spec)
        book.apply(event(spec, payload={
            "change_id": 10, "bids": [["new", "99997.5", "20"]],
            "asks": [["new", "100000", "20"], ["new", "100002.5", "20"]]}))
        with self.assertRaises(FoundationError):
            book.execute_taker("buy", "15", decision_timestamp_ms=1100,
                               decision_monotonic_ns=1100000000,
                               max_transport_age_ms=100)
        fill = book.execute_taker("buy", "30", decision_timestamp_ms=1100,
                                  decision_monotonic_ns=1100000000,
                                  max_transport_age_ms=100)
        self.assertEqual(fill.filled_amount, D("30"))
        self.assertIsNone(fill.quote_amount)  # inverse cashflow is reciprocal-price
        self.assertEqual(fill.levels[1], (D("100002.5"), D("10")))

    def test_d09_replay_has_same_hash_and_immutable_quote(self):
        initial = self.apply_snapshot()
        expected = self.book.state_hash
        other = L2Book(self.spec)
        other.apply(initial)
        self.assertEqual(expected, other.state_hash)
        quote = self.quote()
        with self.assertRaises(FrozenInstanceError):
            quote.change_id = 99
        self.book.apply(event(self.spec, 2, payload={
            "change_id": 11, "bids": [], "asks": []}))
        self.assertEqual(quote.best_ask, D("0.0110"))

    def test_d09_fill_is_independent_of_global_decimal_precision(self):
        initial = self.apply_snapshot()
        reference = self.execute(amount="0.3")
        reference_hash = self.book.state_hash
        with localcontext() as context:
            context.prec = 6
            low_precision_book = L2Book(self.spec)
            low_precision_book.apply(initial)
            actual = low_precision_book.execute_taker(
                "buy", "0.3", decision_timestamp_ms=1100,
                decision_monotonic_ns=1100000000, max_transport_age_ms=100)
            self.assertEqual(actual, reference)
            self.assertEqual(low_precision_book.state_hash, reference_hash)

    def test_d12_raw_and_private_channels_rejected(self):
        for channel in ("book.%s.raw" % self.spec.instrument_id, "private/book", "markprice"):
            with self.subTest(channel=channel):
                book = L2Book(self.spec)
                with self.assertRaises(FoundationError):
                    book.apply(event(self.spec, channel=channel))
                self.assertFalse(book.valid)


if __name__ == "__main__":
    unittest.main()
