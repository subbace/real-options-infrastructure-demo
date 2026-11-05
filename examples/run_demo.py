"""A fixed synthetic book, option/future account and replayable JSONL journal.

This wrapper uses unchanged RO-01 components. It neither models a profitable
strategy nor exercises the later SQLite/recurrent research infrastructure.
Run from the repository root: python -B -m examples.run_demo --output output/demo
"""
from __future__ import annotations

import argparse
import csv
from dataclasses import replace
from decimal import Decimal, localcontext
import json
from pathlib import Path
import time
from typing import Any, Dict

from src.real_options_foundation.book import L2Book
from src.real_options_foundation.common import (
    FoundationError, InstrumentSpec, WorkBudget, ordinary, set_work_budget,
)
from src.real_options_foundation.events import EventEnvelope, causal_latest
from src.real_options_foundation.journal import DurableJournal, validate_journal
from src.real_options_foundation.ledger import Ledger, LedgerEvent

SOURCE_COMMIT = "8666bfb10d31fefb49b0b495ab19e63022d8171e"
EXPIRY_MS = 4000000000000
DECISION_MS = 1002
DECISION_NS = 1002000000
OPTION_ID = "BTC-DEMO-C"
FUTURE_ID = "BTC-DEMO-F"


def instruments():
    """Invented contracts and quantities, never copied exchange observations."""
    common = dict(contract_size="1", expiration_ms=EXPIRY_MS,
                  metadata_version="PUBLIC_SYNTHETIC_DEMO_V1",
                  source_payload={"artificial_fixture": True,
                                  "generator": "examples.run_demo.instruments"})
    option = InstrumentSpec(instrument_id=OPTION_ID, kind="option",
        quote_currency="BTC", amount_unit="BTC", min_amount="0.1",
        amount_step="0.1", tick_size="0.001", strike="100", option_type="call",
        **common)
    future = InstrumentSpec(instrument_id=FUTURE_ID, kind="future",
        quote_currency="USD", amount_unit="USD", min_amount="10",
        amount_step="10", tick_size="1", **common)
    return {OPTION_ID: option, FUTURE_ID: future}


def snapshot(instrument_id, identity, bids, asks):
    """The Deribit-shaped envelope is artificial; its source tag is an interface."""
    return EventEnvelope(source="deribit", connection_id="synthetic-demo",
        ingest_sequence=1, channel="book." + instrument_id + ".100ms",
        instrument_id=instrument_id, exchange_timestamp_ms=1000,
        receive_timestamp_ms=1001, receive_monotonic_ns=1001000000,
        event_id=identity, event_type="book_snapshot",
        payload={"change_id": 1, "bids": bids, "asks": asks})


def replay_account(path: Path, specs) -> Ledger:
    """Validate the hash chain before interpreting the stored financial events."""
    validate_journal(path)
    account = Ledger(specs, initial_cash_btc="1")
    for line in path.read_text(encoding="utf-8").splitlines():
        record = json.loads(line)
        event = record["payload"]
        account.apply(LedgerEvent(record["event_id"], event["event_type"], event["payload"]))
    return account


def flow_svg(rows) -> str:
    """An accounting diagram, not a return curve or market-performance chart."""
    boxes = []
    for index, row in enumerate(rows):
        x = 20 + index * 225
        boxes.append('<rect x="%s" y="60" width="200" height="80" rx="5" '
                     'fill="#eef4ef" stroke="#145c50"/>' % x)
        boxes.append('<text x="%s" y="88" text-anchor="middle" font-size="13">%s</text>'
                     % (x + 100, row["stage"]))
        boxes.append('<text x="%s" y="118" text-anchor="middle" font-size="19">%s BTC</text>'
                     % (x + 100, row["cash_btc"]))
        if index < len(rows) - 1:
            boxes.append('<path d="M%s 100h22" stroke="#145c50" marker-end="url(#arrow)"/>'
                         % (x + 201))
    return ('<svg xmlns="http://www.w3.org/2000/svg" width="940" height="195" '
            'viewBox="0 0 940 195" role="img" aria-labelledby="title desc">'
            '<title id="title">Synthetic cash-account sequence</title>'
            '<desc id="desc">Fixed artificial scenario. Initial cash one BTC, '
            'final cash 0.976 BTC after premium and explicit fees. Not investment performance.</desc>'
            '<defs><marker id="arrow" markerWidth="7" markerHeight="7" refX="6" '
            'refY="3.5" orient="auto"><path d="M0 0L7 3.5L0 7" fill="#145c50"/>'
            '</marker></defs><rect width="940" height="195" fill="white"/>'
            '<g font-family="Arial,sans-serif" fill="#172c2d">'
            '<text x="20" y="30" font-size="17">Synthetic accounting example</text>'
            + "".join(boxes) +
            '<text x="20" y="175" font-size="12">Fixed inputs, not market observations; '
            'the negative cash change is not a strategy backtest.</text></g></svg>\n')


def run_demo(output: Path) -> Dict[str, Any]:
    """Create a fresh result directory; preserve existing runs on any failure."""
    output = Path(output)
    if output.exists():
        raise FileExistsError("Output already exists; choose a fresh directory")
    output.mkdir(parents=True)
    budget = WorkBudget(max_events=1000, max_cpu_seconds=10)
    set_work_budget(budget)
    try:
        specs = instruments()
        opening = snapshot(OPTION_ID, "option-opening",
            [["new", "0.01", "1"]], [["new", "0.02", "1"]])
        # This later event is deliberately present in the input list but is not
        # available to the decision. It is never applied to the decision book.
        later = replace(opening, event_id="option-not-yet-received", ingest_sequence=2,
            exchange_timestamp_ms=1004, receive_timestamp_ms=1005,
            receive_monotonic_ns=1005000000,
            payload={"change_id": 2, "bids": [["new", "9", "1"]],
                     "asks": [["new", "10", "1"]]})
        selected = causal_latest([opening, later], decision_timestamp_ms=DECISION_MS,
            decision_monotonic_ns=DECISION_NS, max_age_ms=2,
            event_type="book_snapshot", instrument_id=OPTION_ID)
        book = L2Book(specs[OPTION_ID]); book.apply(selected)
        quote_args = dict(decision_timestamp_ms=DECISION_MS,
                          decision_monotonic_ns=DECISION_NS, max_transport_age_ms=2)
        quote = book.quote(**quote_args)
        fill = book.execute_taker("buy", "1", **quote_args)
        reused_liquidity_blocked = False
        try:
            book.execute_taker("buy", "0.1", **quote_args)
        except FoundationError as error:
            reused_liquidity_blocked = str(error) == "snapshot_liquidity_already_claimed"

        future_book = L2Book(specs[FUTURE_ID])
        future_book.apply(snapshot(FUTURE_ID, "future-opening",
            [["new", "100", "100"]], [["new", "101", "100"]]))
        hedge = future_book.execute_taker("sell", "100", **quote_args)
        account = Ledger(specs, initial_cash_btc="1")
        rows = []
        def observe(stage):
            future = account.future_positions.get(FUTURE_ID)
            rows.append(ordinary({"stage": stage, "cash_btc": account.cash_btc,
                "option_position_btc": account.option_positions_btc.get(OPTION_ID, Decimal("0")),
                "future_position_usd": future.amount_usd if future else Decimal("0")}))
        observe("Initial")
        for identity, kind, trade, stage in (
            ("option-buy", "OPTION_FILL", fill, "Option bought"),
            ("future-sell", "FUTURE_FILL", hedge, "Future sold")):
            for index, (price, amount) in enumerate(trade.levels):
                account.apply(LedgerEvent(identity + "-" + str(index), kind,
                    {"instrument_id": trade.instrument_id, "side": trade.side,
                     "amount": amount, "price": price, "fee_btc": "0.001",
                     "timestamp_ms": DECISION_MS}))
            observe(stage)
        # The settlement price is an explicit synthetic assertion, never a
        # recovered or estimated venue delivery price. The two-stage convention
        # is inherited from the frozen RO-01 fixture contract.
        account.settle_option_expiry("synthetic-expiry", OPTION_ID, FUTURE_ID,
            "200", timestamp_ms=EXPIRY_MS, option_delivery_fee_btc="0.002")
        observe("Expiry settled")
        path = output / "events.jsonl"
        journal = DurableJournal(path)
        try:
            for event in account.replay_events:
                journal.append(event.event_id,
                    {"event_type": event.event_type, "payload": event.payload})
            first = account.replay_events[0]
            duplicate_suppressed = not journal.append(first.event_id,
                {"event_type": first.event_type, "payload": first.payload})
        finally:
            journal.close()
        validation = validate_journal(path)
        recovered = replay_account(path, specs)
        with localcontext() as context:
            context.prec = 50
            expected_cash = Decimal("1") - Decimal("0.02") - Decimal("0.001") * 2 - Decimal("0.002")
        summary = ordinary({
            "schema": "ro01-public-demo-v1",
            "classification": "SYNTHETIC_ENGINEERING_EXAMPLE_NOT_ECONOMIC_VALIDATION",
            "original_source_commit": SOURCE_COMMIT,
            "data_provenance": "Fixed artificial constants in examples/run_demo.py; no RNG or market download",
            "decision_ms": DECISION_MS, "selected_event_id": selected.event_id,
            "later_event_receive_ms": later.receive_timestamp_ms,
            "option_quote": {"best_bid_btc": quote.best_bid, "best_ask_btc": quote.best_ask},
            "fills": {"option_amount_btc": fill.filled_amount,
                      "future_amount_usd": hedge.filled_amount, "future_side": hedge.side},
            "cash_trace": rows,
            "final_cash_btc": account.cash_btc,
            "cash_change_btc": account.cash_btc - Decimal("1"),
            "total_explicit_fees_btc": account.snapshot()["fees_paid_btc"],
            "positions_closed": not account.option_positions_btc and not account.future_positions,
            "hand_calculated_cash_btc": expected_cash,
            "cash_reconciliation_exact": account.cash_btc == expected_cash,
            "later_event_excluded": selected.event_id != later.event_id,
            "liquidity_reuse_blocked": reused_liquidity_blocked,
            "journal_duplicate_suppressed": duplicate_suppressed,
            "journal_records": validation["records"],
            "ledger_state_recovery_exact": recovered.state_hash == account.state_hash,
            "ledger_journal_recovery_exact": recovered.journal_hash == account.journal_hash,
            "journal_hash": validation["journal_hash"],
            "ledger_state_hash": account.state_hash,
            "ledger_journal_hash": account.journal_hash,
            "event_operations": budget.operations,
        })
        checks = [summary[key] for key in (
            "cash_reconciliation_exact", "positions_closed", "later_event_excluded",
            "liquidity_reuse_blocked", "journal_duplicate_suppressed",
            "ledger_state_recovery_exact", "ledger_journal_recovery_exact")]
        if not all(checks):
            raise AssertionError("The synthetic demonstration failed its accounting or causal contracts")
        (output / "summary.json").write_text(json.dumps(summary, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        with (output / "cash_trace.csv").open("w", newline="", encoding="utf-8") as stream:
            writer = csv.DictWriter(stream, fieldnames=["stage", "cash_btc", "option_position_btc", "future_position_usd"])
            writer.writeheader(); writer.writerows(rows)
        (output / "accounting_flow.svg").write_text(flow_svg(rows), encoding="utf-8")
        return summary
    finally:
        set_work_budget(None)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=Path("output/demo"))
    args = parser.parse_args(argv)
    wall = time.perf_counter(); cpu = time.process_time()
    result = run_demo(args.output)
    print(json.dumps({"status": "PASS", "final_cash_btc": result["final_cash_btc"],
        "event_operations": result["event_operations"],
        "wall_seconds": round(time.perf_counter() - wall, 6),
        "cpu_seconds": round(time.process_time() - cpu, 6)}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
