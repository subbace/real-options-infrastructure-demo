"""Additional public-wrapper contracts, separate from the original 59 cases."""
import csv
import hashlib
import json
from pathlib import Path
import tempfile
import unittest

from examples.run_demo import instruments, replay_account, run_demo
from src.real_options_foundation.common import FoundationError

ROOT = Path(__file__).resolve().parents[1]


class PublicDemoTests(unittest.TestCase):
    def test_cash_agrees_with_independent_hand_calculation_and_closes_positions(self):
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "fresh"
            result = run_demo(output)
            # Fixed scenario: 1 - premium 0.02 - two fees 0.001 - delivery fee
            # 0.002 = 0.976 BTC. The option and future terminal exposure cancel.
            self.assertEqual(result["final_cash_btc"], "0.976")
            self.assertEqual(result["cash_change_btc"], "-0.024")
            self.assertEqual(result["total_explicit_fees_btc"], "0.004")
            self.assertTrue(result["positions_closed"])
            self.assertTrue(result["ledger_state_recovery_exact"])
            self.assertEqual(result["journal_records"], 4)
            with (output / "cash_trace.csv").open(newline="", encoding="utf-8") as stream:
                rows = list(csv.DictReader(stream))
            self.assertEqual([row["cash_btc"] for row in rows], ["1", "0.979", "0.978", "0.976"])
            self.assertEqual(rows[-1]["option_position_btc"], "0")
            self.assertEqual(rows[-1]["future_position_usd"], "0")
            self.assertIn("not market observations", (output / "accounting_flow.svg").read_text())

    def test_decision_uses_received_snapshot_and_blocks_reusing_liquidity(self):
        with tempfile.TemporaryDirectory() as directory:
            result = run_demo(Path(directory) / "fresh")
            self.assertEqual(result["selected_event_id"], "option-opening")
            self.assertGreater(result["later_event_receive_ms"], result["decision_ms"])
            self.assertEqual(result["option_quote"]["best_ask_btc"], "0.02")
            self.assertTrue(result["liquidity_reuse_blocked"])
            self.assertTrue(result["journal_duplicate_suppressed"])

    def test_durable_tamper_is_rejected_before_account_replay(self):
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "fresh"
            run_demo(output)
            path = output / "events.jsonl"
            lines = path.read_text(encoding="utf-8").splitlines()
            record = json.loads(lines[0]); record["payload"]["payload"]["fee_btc"] = "9"
            lines[0] = json.dumps(record)
            path.write_text("\n".join(lines) + "\n", encoding="utf-8")
            with self.assertRaises(FoundationError):
                replay_account(path, instruments())

    def test_existing_run_is_preserved(self):
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "already-present"; output.mkdir()
            marker = output / "keep.txt"; marker.write_text("preserve")
            with self.assertRaises(FileExistsError):
                run_demo(output)
            self.assertEqual(marker.read_text(), "preserve")

    def test_original_fourteen_source_bytes_are_preserved(self):
        identity = json.loads((ROOT / "provenance/SOURCE_IDENTITY.json").read_text())
        self.assertEqual(len(identity["original_source_files"]), 14)
        for item in identity["original_source_files"]:
            with self.subTest(path=item["path"]):
                self.assertEqual(hashlib.sha256((ROOT / item["path"]).read_bytes()).hexdigest().upper(), item["sha256"])


if __name__ == "__main__":
    unittest.main()
