"""Hand-calculated, artificial RO-01 accounting cases; no market observations."""

import unittest
from dataclasses import replace
from decimal import Decimal, localcontext

from src.real_options_foundation.common import FoundationError, InstrumentSpec, canonical_json_bytes
from src.real_options_foundation.ledger import (
    Ledger, LedgerEvent, SETTLEMENT_CONVENTION, TWO_STAGE_START_MS,
)


D = Decimal
EXPIRY = 1800000000000
TRADE_TIME = EXPIRY - 100000


def option(name="CALL", option_type="call", strike="100000", expiry=EXPIRY):
    return InstrumentSpec(instrument_id=name, kind="option", quote_currency="BTC",
                          amount_unit="BTC", contract_size=D("1"), min_amount=D("0.1"),
                          amount_step=D("0.1"), tick_size=D("0.0001"), expiration_ms=expiry,
                          metadata_version="ARTIFICIAL_FIXTURE_V1", source_payload={"fixture": True},
                          strike=D(strike), option_type=option_type)


def future(name="FUT", expiry=EXPIRY):
    return InstrumentSpec(instrument_id=name, kind="future", quote_currency="USD",
                          amount_unit="USD", contract_size=D("10"), min_amount=D("10"),
                          amount_step=D("10"), tick_size=D("2.5"), expiration_ms=expiry,
                          metadata_version="ARTIFICIAL_FIXTURE_V1", source_payload={"fixture": True})


def fill(event_id, kind="option", instrument="CALL", side="buy", amount="1", price="0.05",
         fee="0", timestamp=TRADE_TIME):
    return LedgerEvent(event_id, "OPTION_FILL" if kind == "option" else "FUTURE_FILL",
                       {"instrument_id": instrument, "side": side, "amount": amount,
                        "price": price, "fee_btc": fee, "timestamp_ms": timestamp})


def settlement(event_id, price, daily=False, fee="0", timestamp=EXPIRY):
    return LedgerEvent(event_id, "FUTURE_DAILY_SETTLEMENT" if daily else "FUTURE_SETTLEMENT",
                       {"instrument_id": "FUT", "settlement_price": price,
                        "fee_btc": fee, "timestamp_ms": timestamp})


def account(event_id, event_type, amount, timestamp=TRADE_TIME):
    return LedgerEvent(event_id, event_type, {"amount_btc": amount, "timestamp_ms": timestamp})


class TestRealOptionsLedger(unittest.TestCase):
    def make_ledger(self, instruments=None, **kwargs):
        specs = instruments or [option(), future()]
        return Ledger({spec.instrument_id: spec for spec in specs}, initial_cash_btc=D("1"), **kwargs)

    def assertUnchanged(self, ledger, state_hash, journal_hash):
        self.assertEqual(ledger.state_hash, state_hash)
        self.assertEqual(ledger.journal_hash, journal_hash)

    def test_option_premium_fee_and_mark_have_no_duplicate_cashflow(self):
        ledger = self.make_ledger()
        ledger.apply(fill("buy", fee="0.001"))
        self.assertEqual(ledger.cash_btc, D("0.949"))
        self.assertEqual(ledger.option_positions_btc["CALL"], D("1"))
        self.assertEqual(ledger.equity_btc({"CALL": "0.07"}, {}), D("1.019"))
        self.assertEqual(ledger.cash_btc, D("0.949"))
        ledger.apply(fill("partial-close", side="sell", amount="0.4", price="0.08"))
        self.assertEqual(ledger.cash_btc, D("0.981"))
        self.assertEqual(ledger.option_positions_btc["CALL"], D("0.6"))

    def test_short_option_is_a_negative_valuation_not_free_premium(self):
        ledger = self.make_ledger()
        ledger.apply(fill("short", side="sell", fee="0.001"))
        self.assertEqual(ledger.cash_btc, D("1.049"))
        self.assertEqual(ledger.equity_btc({"CALL": "0.04"}, {}), D("1.009"))

    def test_future_open_has_no_principal_cashflow(self):
        ledger = self.make_ledger()
        ledger.apply(fill("f-open", "future", "FUT", amount="1000", price="10000", fee="0.00005"))
        self.assertEqual(ledger.cash_btc, D("0.99995"))
        self.assertEqual(ledger.equity_btc({}, {"FUT": "12500"}), D("1.01995"))
        ledger.apply(fill("f-close", "future", "FUT", "sell", "1000", "12500", "0.00004"))
        self.assertEqual(ledger.cash_btc, D("1.01991"))
        self.assertFalse(ledger.future_positions)
        self.assertEqual(ledger.snapshot()["fees_paid_btc"], D("0.00009"))

    def test_inverse_reciprocal_cost_basis_and_partial_close(self):
        ledger = self.make_ledger()
        ledger.apply(fill("entry-a", "future", "FUT", amount="1000", price="10000"))
        ledger.apply(fill("entry-b", "future", "FUT", amount="1000", price="20000"))
        self.assertEqual(ledger.future_positions["FUT"].inverse_entry, D("0.000075"))
        self.assertEqual(ledger.equity_btc({}, {"FUT": "20000"}), D("1.05"))
        ledger.apply(fill("close-half", "future", "FUT", "sell", "1000", "20000"))
        self.assertEqual(ledger.cash_btc, D("1.025"))
        self.assertEqual(ledger.future_positions["FUT"].amount_usd, D("1000"))
        self.assertEqual(ledger.future_positions["FUT"].inverse_entry, D("0.000075"))

    def test_future_reversal_realizes_old_side_only(self):
        ledger = self.make_ledger()
        ledger.apply(fill("entry", "future", "FUT", amount="1000", price="10000"))
        ledger.apply(fill("reverse", "future", "FUT", "sell", "1500", "12500"))
        self.assertEqual(ledger.cash_btc, D("1.02"))
        self.assertEqual(ledger.future_positions["FUT"].amount_usd, D("-500"))
        self.assertEqual(ledger.future_positions["FUT"].inverse_entry, D("0.00008"))
        ledger.apply(fill("cover", "future", "FUT", "buy", "500", "10000"))
        self.assertEqual(ledger.cash_btc, D("1.03"))
        self.assertFalse(ledger.future_positions)

    def test_daily_settlement_resets_basis_without_double_pnl(self):
        ledger = self.make_ledger()
        ledger.apply(fill("entry", "future", "FUT", amount="1000", price="10000"))
        ledger.apply(settlement("daily", "12500", daily=True, timestamp=EXPIRY - 1000))
        self.assertEqual(ledger.cash_btc, D("1.02"))
        self.assertEqual(ledger.future_positions["FUT"].amount_usd, D("1000"))
        self.assertEqual(ledger.equity_btc({}, {"FUT": "20000"}), D("1.05"))
        ledger.apply(settlement("final", "20000"))
        self.assertEqual(ledger.cash_btc, D("1.05"))
        self.assertFalse(ledger.future_positions)

    def test_equity_refuses_incomplete_or_inexact_marks(self):
        ledger = self.make_ledger()
        ledger.apply(fill("option"))
        ledger.apply(fill("future", "future", "FUT", amount="10", price="10000"))
        for option_marks, future_marks in (({}, {}), ({"CALL": "0.05"}, {}),
                                          ({"CALL": "0.05"}, {"FUT": 10000.0}),
                                          ({"CALL": "-1"}, {"FUT": "10000"}),
                                          ({"CALL": "0.05"}, {"FUT": "0"})):
            with self.subTest(option_marks=option_marks, future_marks=future_marks):
                with self.assertRaises(FoundationError):
                    ledger.equity_btc(option_marks, future_marks)

    def test_reservation_reduces_available_not_cash_or_equity(self):
        ledger = self.make_ledger()
        ledger.apply(account("reserve", "RESERVE_MARGIN", "0.7"))
        self.assertEqual(ledger.cash_btc, D("1"))
        self.assertEqual(ledger.available_cash_btc, D("0.3"))
        self.assertEqual(ledger.equity_btc({}, {}), D("1"))
        self.assertEqual(ledger.snapshot()["fees_paid_btc"], D("0"))

    def test_cash_constraint_is_optional_and_failed_batch_is_atomic(self):
        ledger = self.make_ledger(enforce_available_cash=True)
        state, journal = ledger.state_hash, ledger.journal_hash
        events = [account("cash", "CASHFLOW", "0.2"), account("reserve", "RESERVE_MARGIN", "2")]
        with self.assertRaises(FoundationError):
            ledger.apply_batch(events)
        self.assertUnchanged(ledger, state, journal)
        self.assertEqual(len(ledger.journal), 0)
        self.assertTrue(ledger.apply(account("cash", "CASHFLOW", "0.2")))

    def test_itm_call_two_events_cash_once_and_idempotent_retry(self):
        ledger = self.make_ledger()
        ledger.apply(fill("premium", fee="0.001"))
        self.assertEqual(ledger.settle_option_expiry("expiry", "CALL", "FUT", "125000",
                                                   timestamp_ms=EXPIRY, option_delivery_fee_btc="0.002"), 2)
        self.assertEqual(ledger.cash_btc, D("1.147"))
        self.assertFalse(ledger.option_positions_btc)
        self.assertFalse(ledger.future_positions)
        self.assertEqual([item.event.event_type for item in ledger.journal[-2:]],
                         ["OPTION_EXERCISE_INTO_FUTURE", "FUTURE_SETTLEMENT"])
        state, journal = ledger.state_hash, ledger.journal_hash
        self.assertEqual(ledger.settle_option_expiry("expiry", "CALL", "FUT", "125000",
                                                   timestamp_ms=EXPIRY, option_delivery_fee_btc="0.002"), 0)
        self.assertUnchanged(ledger, state, journal)
        with self.assertRaises(FoundationError):
            ledger.settle_option_expiry("expiry", "CALL", "FUT", "125001", timestamp_ms=EXPIRY)
        self.assertUnchanged(ledger, state, journal)

    def test_long_put_and_both_short_sides_have_correct_sign(self):
        cases = [("put", "buy", "80000", "1.20"),
                 ("put", "sell", "80000", "0.80"),
                 ("call", "sell", "125000", "0.85")]
        for option_type, side, price, expected in cases:
            with self.subTest(option_type=option_type, side=side):
                ledger = self.make_ledger([option(option_type=option_type), future()])
                ledger.apply(fill("premium", side=side))
                ledger.settle_option_expiry("expiry", "CALL", "FUT", price, timestamp_ms=EXPIRY)
                self.assertEqual(ledger.cash_btc, D(expected))

    def test_otm_and_at_money_expire_without_generated_future(self):
        for price in ("80000", "100000"):
            with self.subTest(price=price):
                ledger = self.make_ledger()
                ledger.apply(fill("premium"))
                self.assertEqual(ledger.settle_option_expiry("expiry", "CALL", "FUT", price,
                                                           timestamp_ms=EXPIRY), 1)
                self.assertEqual(ledger.cash_btc, D("0.95"))
                self.assertEqual(ledger.journal[-1].event.event_type, "OPTION_EXPIRY_OTM")
                self.assertFalse(ledger.option_positions_btc)

    def test_generated_contract_is_not_constrained_by_trade_lot_or_tick(self):
        ledger = self.make_ledger([option(strike="100001"), future()])
        ledger.apply(fill("premium", amount="0.1"))
        ledger.settle_option_expiry("expiry", "CALL", "FUT", "125000", timestamp_ms=EXPIRY)
        # 0.1 * 100001 = 10000.1 USD is not a 10 USD trade lot; strike is off future tick.
        self.assertEqual(ledger.cash_btc, D("1.0149992"))

    def test_settlement_rejects_wrong_expiry_and_double_delivery_fee_atomically(self):
        ledger = self.make_ledger([option(), future(expiry=EXPIRY + 1)])
        ledger.apply(fill("premium"))
        state, journal = ledger.state_hash, ledger.journal_hash
        with self.assertRaises(FoundationError):
            ledger.settle_option_expiry("expiry", "CALL", "FUT", "125000", timestamp_ms=EXPIRY)
        self.assertUnchanged(ledger, state, journal)
        ledger = self.make_ledger()
        ledger.apply(fill("premium"))
        state, journal = ledger.state_hash, ledger.journal_hash
        for parameters in ({"future_delivery_fee_btc": "0.001"},
                           {"option_delivery_fee_btc": "-0.001"}):
            with self.assertRaises(FoundationError):
                ledger.settle_option_expiry("expiry", "CALL", "FUT", "125000",
                                           timestamp_ms=EXPIRY, **parameters)
            self.assertUnchanged(ledger, state, journal)

    def test_multiple_same_expiry_options_require_one_net_future_settlement(self):
        ledger = self.make_ledger([option(), option("PUT", "put", "150000"), future()])
        ledger.apply_batch((fill("c"), fill("p", instrument="PUT")))
        state, journal = ledger.state_hash, ledger.journal_hash
        with self.assertRaises(FoundationError):
            ledger.settle_option_expiry("isolated", "CALL", "FUT", "125000", timestamp_ms=EXPIRY)
        self.assertUnchanged(ledger, state, journal)
        exercises = [LedgerEvent(name, "OPTION_EXERCISE_INTO_FUTURE",
                                 {"option_id": instrument, "future_id": "FUT", "settlement_price": "125000",
                                  "timestamp_ms": EXPIRY, "fee_btc": "0",
                                  "settlement_convention": SETTLEMENT_CONVENTION})
                     for name, instrument in (("call-expiry", "CALL"), ("put-expiry", "PUT"))]
        ledger.apply_batch(exercises + [settlement("net-settlement", "125000")])
        # Call +0.2 BTC and put +0.2 BTC; two 0.05 BTC premiums.
        self.assertEqual(ledger.cash_btc, D("1.3"))
        self.assertFalse(ledger.option_positions_btc)
        self.assertFalse(ledger.future_positions)

    def test_existing_future_hedge_nets_at_exercise_without_double_pnl(self):
        ledger = self.make_ledger()
        ledger.apply(fill("option"))
        ledger.apply(fill("hedge", "future", "FUT", "sell", "100000", "100000"))
        ledger.settle_option_expiry("expiry", "CALL", "FUT", "125000", timestamp_ms=EXPIRY)
        self.assertEqual(ledger.cash_btc, D("0.95"))
        self.assertFalse(ledger.future_positions)

    def test_conflicting_duplicate_and_mid_batch_failure_preserve_journal(self):
        ledger = self.make_ledger()
        event = fill("once")
        self.assertTrue(ledger.apply(event))
        self.assertFalse(ledger.apply(event))
        state, journal = ledger.state_hash, ledger.journal_hash
        with self.assertRaises(FoundationError):
            ledger.apply(fill("once", price="0.06"))
        self.assertUnchanged(ledger, state, journal)
        with self.assertRaises(FoundationError):
            ledger.apply_batch([account("new", "CASHFLOW", "1"), account("new", "CASHFLOW", "2")])
        self.assertUnchanged(ledger, state, journal)
        self.assertTrue(ledger.apply(account("new", "CASHFLOW", "1")))

    def test_journal_payload_is_detached_immutable_and_double_replay_identical(self):
        ledger = self.make_ledger()
        payload = {"amount_btc": "0.1", "metadata": {"source": "fixture"}, "timestamp_ms": TRADE_TIME}
        event = LedgerEvent("deposit", "CASHFLOW", payload)
        payload["amount_btc"] = "900"
        payload["metadata"]["source"] = "changed"
        ledger.apply(event)
        self.assertEqual(ledger.cash_btc, D("1.1"))
        with self.assertRaises(TypeError):
            ledger.journal[0].event.payload["metadata"]["source"] = "change"
        ledger.apply(fill("option", fee="0.001"))
        ledger.apply(fill("future", "future", "FUT", amount="1000", price="10000"))
        for _ in range(2):
            replay = self.make_ledger()
            replay.apply_batch(ledger.replay_events)
            self.assertEqual(replay.state_hash, ledger.state_hash)
            self.assertEqual(replay.journal_hash, ledger.journal_hash)
            self.assertEqual(canonical_json_bytes(replay.snapshot()), canonical_json_bytes(ledger.snapshot()))

    def test_time_unit_grid_and_nonfinite_errors_fail_closed(self):
        ledger = self.make_ledger()
        bad_events = [fill("bad", amount="0.15"), fill("bad", price="0.05001"),
                      fill("bad", fee="NaN"), fill("bad", timestamp=True),
                      fill("bad", timestamp=EXPIRY), fill("bad", instrument="UNKNOWN"),
                      LedgerEvent("bad", "OPTION_FILL", {"instrument_id": "CALL"})]
        state, journal = ledger.state_hash, ledger.journal_hash
        for event in bad_events:
            with self.subTest(event=event.as_dict()):
                with self.assertRaises(FoundationError):
                    ledger.apply(event)
                self.assertUnchanged(ledger, state, journal)
        with self.assertRaises(FoundationError):
            LedgerEvent("bad", "CASHFLOW", {"amount_btc": 0.1})
        ledger.apply(fill("valid", timestamp=TRADE_TIME))
        with self.assertRaises(FoundationError):
            ledger.apply(fill("past", timestamp=TRADE_TIME - 1))

    def test_historical_settlement_convention_is_not_assumed(self):
        old_expiry = TWO_STAGE_START_MS - 1
        ledger = self.make_ledger([option(expiry=old_expiry), future(expiry=old_expiry)])
        ledger.apply(fill("old", timestamp=old_expiry - 1000))
        state, journal = ledger.state_hash, ledger.journal_hash
        with self.assertRaises(FoundationError):
            ledger.settle_option_expiry("expiry", "CALL", "FUT", "125000", timestamp_ms=old_expiry)
        self.assertUnchanged(ledger, state, journal)

    def test_fixture_quantization_and_context_independence_are_explicit(self):
        ledger = self.make_ledger(cash_quantum_btc=D("0.00000001"))
        with localcontext() as context:
            context.prec = 8
            ledger.apply(fill("entry", "future", "FUT", amount="1000", price="10000"))
            ledger.apply(fill("close", "future", "FUT", "sell", "1000", "12000"))
        self.assertEqual(ledger.cash_btc, D("1.01666667"))
        self.assertEqual(ledger.snapshot()["realized_future_pnl_btc"], D("0.01666667"))
        with self.assertRaises(FoundationError):
            self.make_ledger(cash_quantum_btc="0.00000003")

    def test_event_budget_and_invalid_second_event_are_atomic(self):
        ledger = self.make_ledger(max_events=2)
        state, journal = ledger.state_hash, ledger.journal_hash
        with self.assertRaises(FoundationError):
            ledger.apply_batch([account(str(index), "CASHFLOW", "0.1")
                                for index in range(3)])
        self.assertUnchanged(ledger, state, journal)
        with self.assertRaises(FoundationError):
            ledger.apply_batch([fill("valid"), fill("bad-future", "future", "FUT", amount="10", price="-1")])
        self.assertUnchanged(ledger, state, journal)

    def test_direct_batch_cannot_bypass_generated_future_delivery_fee_guard(self):
        ledger = self.make_ledger()
        ledger.apply(fill("premium"))
        state, journal = ledger.state_hash, ledger.journal_hash
        exercise = LedgerEvent("exercise", "OPTION_EXERCISE_INTO_FUTURE",
                               {"option_id": "CALL", "future_id": "FUT", "settlement_price": "125000",
                                "timestamp_ms": EXPIRY, "fee_btc": "0.001",
                                "settlement_convention": SETTLEMENT_CONVENTION})
        with self.assertRaises(FoundationError):
            ledger.apply_batch([exercise, settlement("delivery", "125000", fee="0.001")])
        self.assertUnchanged(ledger, state, journal)
        with self.assertRaises(FoundationError):
            ledger.apply_batch([exercise, settlement("delivery", "130000", fee="0")])
        self.assertUnchanged(ledger, state, journal)
        self.assertEqual(ledger.option_positions_btc["CALL"], D("1"))
        ledger.apply_batch([exercise, settlement("delivery", "125000", fee="0")])
        self.assertEqual(ledger.cash_btc, D("1.149"))
        self.assertEqual(ledger.snapshot()["pending_exercise_future_ids"], [])

    def test_cash_and_margin_timestamps_are_mandatory_and_chronological(self):
        ledger = self.make_ledger()
        for event_type in ("CASHFLOW", "RESERVE_MARGIN"):
            state, journal = ledger.state_hash, ledger.journal_hash
            with self.assertRaises(FoundationError):
                ledger.apply(LedgerEvent("no-time", event_type, {"amount_btc": "0.1"}))
            self.assertUnchanged(ledger, state, journal)
        ledger.apply(account("deposit", "CASHFLOW", "0.1"))
        state, journal = ledger.state_hash, ledger.journal_hash
        with self.assertRaises(FoundationError):
            ledger.apply(account("past-reservation", "RESERVE_MARGIN", "0.1", timestamp=TRADE_TIME - 1))
        self.assertUnchanged(ledger, state, journal)

    def test_state_hash_binds_complete_metadata_not_only_version_labels(self):
        original = option()
        changed_tick = replace(original, tick_size=D("0.0002"))
        changed_payload = replace(original, source_payload={"fixture": True, "revision": "different"})
        first = self.make_ledger([original, future()])
        second = self.make_ledger([changed_tick, future()])
        third = self.make_ledger([changed_payload, future()])
        self.assertEqual(original.metadata_version, changed_tick.metadata_version)
        self.assertNotEqual(first.state_hash, second.state_hash)
        self.assertNotEqual(first.state_hash, third.state_hash)


if __name__ == "__main__":
    unittest.main()
