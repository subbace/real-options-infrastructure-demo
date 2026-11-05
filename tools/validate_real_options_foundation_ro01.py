"""Run only the offline RO-01 fixture tests, with bounded worker resources.

Python 3.9 standard library only. This validates technical fixtures, never
market performance. No training, live acquisition or economic evaluation is
performed. Every invocation creates a new audit directory and receipt.
"""

from __future__ import annotations

import argparse
from contextlib import contextmanager, redirect_stderr, redirect_stdout
from datetime import datetime, timezone
import hashlib
import importlib
import io
import json
import os
from pathlib import Path
import re
import socket
import stat
import subprocess
import sys
import tempfile
import time
import traceback
from typing import Any, Dict, Iterator, List, Mapping, Optional, Sequence
import unittest
from unittest import mock
import uuid


ROOT = Path(__file__).resolve().parents[1]
MAX_EVENTS = 20000
MAX_CPU_SECONDS = 60
MAX_WALL_SECONDS = 60
MAX_OUTPUT_BYTES = 100000000
MAX_LOG_BYTES = 500000
GATES = tuple("D{:02d}".format(index) for index in range(1, 13))
PROTOCOLS = (
    "protocols/REAL_OPTIONS_FOUNDATION_RO01_EXECUTION_V1.md",
    "protocols/REAL_OPTIONS_DATA_AND_LEDGER_CONTRACT_V1.md",
    "protocols/REAL_OPTIONS_RESEARCH_PROGRAM_V1.md",
)


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest().upper()


def json_payload(value: Any) -> bytes:
    def ordinary(item: Any) -> Any:
        if isinstance(item, Mapping):
            return {key: ordinary(child) for key, child in item.items()}
        if isinstance(item, (tuple, list)):
            return [ordinary(child) for child in item]
        return item
    return (json.dumps(ordinary(value), ensure_ascii=False, indent=2,
                       sort_keys=True, allow_nan=False) + "\n").encode("utf-8")


def new_file(path: Path, payload: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("xb") as handle:
        handle.write(payload)
        handle.flush()
        os.fsync(handle.fileno())


def source_manifest() -> Dict[str, Dict[str, Any]]:
    paths = list((ROOT / "src/real_options_foundation").glob("*.py"))
    paths += list((ROOT / "tests").glob("test_real_options_*.py"))
    paths.append(Path(__file__).resolve())
    paths += [ROOT / relative for relative in PROTOCOLS if (ROOT / relative).is_file()]
    result = {}
    for path in sorted(set(paths)):
        resolved = path.resolve(strict=True)
        resolved.relative_to(ROOT)
        if path.is_symlink() or getattr(path.lstat(), "st_file_attributes", 0) & 0x400:
            raise RuntimeError("Source links/reparse points are not accepted")
        result[path.relative_to(ROOT).as_posix()] = {"sha256": sha256(path), "bytes": path.stat().st_size}
    return result


def git_state() -> Dict[str, Any]:
    if not (ROOT / ".git").exists():
        return {"available": False, "sealed": False,
                "reason": "Standalone package has no Git checkout metadata"}
    environment = dict(os.environ, GIT_OPTIONAL_LOCKS="0")
    prefix = ["git", "-c", "safe.directory=" + ROOT.as_posix(), "-C", str(ROOT)]
    def query(*arguments: str) -> bytes:
        return subprocess.run(prefix + list(arguments), check=True, stdout=subprocess.PIPE,
                              stderr=subprocess.PIPE, env=environment, timeout=5).stdout
    try:
        top = Path(query("rev-parse", "--show-toplevel").decode("utf-8").strip()).resolve()
        if top != ROOT:
            raise RuntimeError("Git root is not this exact source root")
        commit = query("rev-parse", "HEAD").decode("ascii").strip()
        branch = query("rev-parse", "--abbrev-ref", "HEAD").decode("utf-8").strip()
        dirty = bool(query("status", "--porcelain=v1", "-z", "--untracked-files=all"))
        return {"available": True, "commit": commit, "branch": branch,
                "working_tree": "DIRTY" if dirty else "CLEAN", "sealed": False,
                "interpretation": "Observed working-copy identity; no scientific seal or post-commit claim"}
    except (OSError, RuntimeError, subprocess.SubprocessError) as exc:
        return {"available": False, "sealed": False, "reason": type(exc).__name__}


def output_size(directory: Path) -> int:
    total = 0
    for current, directories, files in os.walk(str(directory), followlinks=False):
        for name in directories + files:
            path = Path(current) / name
            info = path.lstat()
            if stat.S_ISLNK(info.st_mode) or getattr(info, "st_file_attributes", 0) & 0x400:
                raise RuntimeError("Reparse/link found in validation output")
            path.resolve().relative_to(directory.resolve())
        total += sum((Path(current) / name).stat().st_size for name in files)
    return total


class NetworkDisabled(PermissionError):
    pass


@contextmanager
def network_guard() -> Iterator[List[str]]:
    attempts = []
    def deny(method: str) -> Any:
        def blocked(*args: Any, **kwargs: Any) -> Any:
            attempts.append(method)
            raise NetworkDisabled("RO-01 offline validation blocks " + method)
        return blocked
    with mock.patch.object(socket.socket, "connect", deny("socket.connect")), \
            mock.patch.object(socket.socket, "connect_ex", deny("socket.connect_ex")), \
            mock.patch.object(socket, "create_connection", deny("socket.create_connection")), \
            mock.patch.object(socket, "getaddrinfo", deny("socket.getaddrinfo")), \
            mock.patch.object(socket.socket, "sendto", deny("socket.sendto")):
        # A guard probe raises before resolution or connection; it sends no packet.
        try:
            socket.create_connection(("127.0.0.1", 9), timeout=0.01)
        except NetworkDisabled:
            pass
        else:
            raise RuntimeError("Offline network guard self-check failed")
        yield attempts


class BoundedLog(io.TextIOBase):
    def __init__(self) -> None:
        self.parts = []  # type: List[str]
        self.bytes_written = 0
        self.exceeded = False

    def write(self, value: str) -> int:
        payload = value.encode("utf-8", errors="replace")
        if self.bytes_written + len(payload) > MAX_LOG_BYTES:
            self.exceeded = True
            raise RuntimeError("RO-01 captured diagnostic output budget exceeded")
        self.bytes_written += len(payload)
        self.parts.append(value)
        return len(value)

    def text(self) -> str:
        return "".join(self.parts)


class FixtureResult(unittest.TestResult):
    def __init__(self) -> None:
        super().__init__()
        self.records = []  # type: List[Dict[str, Any]]
        self.active = {}  # type: Dict[str, Dict[str, Any]]

    def startTest(self, test: unittest.TestCase) -> None:
        super().startTest(test)
        description = test.id() + " " + (test.shortDescription() or "")
        gates = sorted(set("D" + item for item in re.findall(
            r"(?<![A-Za-z0-9])D(0[1-9]|1[0-2])(?![A-Za-z0-9])", description, re.I)))
        entry = {"name": test.id(), "gates": gates, "status": "RUNNING"}
        self.active[test.id()] = entry
        self.records.append(entry)

    def finish(self, test: unittest.TestCase, status: str, details: str = "") -> None:
        entry = self.active.get(test.id())
        if entry is None:
            # setUpClass/module failures can be reported before startTest.
            entry = {"name": test.id(), "gates": [], "status": status}
            self.records.append(entry)
        entry["status"] = status
        if details:
            entry["details"] = details[:8000]

    def addSuccess(self, test: unittest.TestCase) -> None:
        super().addSuccess(test)
        self.finish(test, "PASS")

    def addFailure(self, test: unittest.TestCase, err: Any) -> None:
        super().addFailure(test, err)
        self.finish(test, "FAIL", self._exc_info_to_string(err, test))

    def addError(self, test: unittest.TestCase, err: Any) -> None:
        super().addError(test, err)
        self.finish(test, "ERROR", self._exc_info_to_string(err, test))

    def addSkip(self, test: unittest.TestCase, reason: str) -> None:
        super().addSkip(test, reason)
        self.finish(test, "SKIP", reason)

    def addExpectedFailure(self, test: unittest.TestCase, err: Any) -> None:
        super().addExpectedFailure(test, err)
        self.finish(test, "EXPECTED_FAILURE", self._exc_info_to_string(err, test))

    def addUnexpectedSuccess(self, test: unittest.TestCase) -> None:
        super().addUnexpectedSuccess(test)
        self.finish(test, "UNEXPECTED_SUCCESS")

    def addSubTest(self, test: unittest.TestCase, subtest: Any, err: Any) -> None:
        super().addSubTest(test, subtest, err)
        if err is not None:
            self.finish(test, "SUBTEST_FAILURE", self._exc_info_to_string(err, test))


def gate_counts(records: Sequence[Mapping[str, Any]]) -> Dict[str, Any]:
    counts = {}
    for gate in GATES:
        entries = [entry for entry in records if gate in entry["gates"]]
        counts[gate] = {"tests": len(entries), "passed": sum(entry["status"] == "PASS" for entry in entries),
                        "names": [entry["name"] for entry in entries],
                        "status": "PASS" if entries and all(entry["status"] == "PASS" for entry in entries)
                        else "FAIL_OR_UNCOVERED"}
    return counts


def worker(run_dir: Path) -> int:
    started_wall = time.monotonic()
    run_dir = run_dir.resolve(strict=True)
    receipt = {"schema": "real-options-foundation-ro01-technical-fixture-v1",
               "classification": "technical_fixture", "status": "TECHNICAL_FIXTURE_FAIL",
               "generated_utc": datetime.now(timezone.utc).isoformat(),
               "limits": {"max_events": MAX_EVENTS, "max_total_cpu_seconds": MAX_CPU_SECONDS,
                          "max_wall_seconds": MAX_WALL_SECONDS, "max_output_bytes": MAX_OUTPUT_BYTES},
               "scientific_execution": "NONE", "economic_metrics": {},
               "live_acquisition": False, "real_orders": False,
               "tests_run": 0, "tests": [], "sources_before": {},
               "environment": {"python": sys.version.split()[0], "stdlib_only": True},
               "git_before": git_state(), "protocols_present": [p for p in PROTOCOLS if (ROOT / p).is_file()]}
    result = FixtureResult()
    log = BoundedLog()
    budget = None
    common = None
    attempts = []  # type: List[str]
    try:
        receipt["sources_before"] = source_manifest()
        test_files = sorted((ROOT / "tests").glob("test_real_options_*.py"))
        if not test_files:
            raise RuntimeError("No RO-01 fixture test files found")
        fixture_temp = run_dir / "fixture_temp"
        fixture_temp.mkdir(exist_ok=False)
        tempfile.tempdir = str(fixture_temp)
        for key in ("TMPDIR", "TEMP", "TMP"):
            os.environ[key] = str(fixture_temp)
        sys.dont_write_bytecode = True
        sys.path.insert(0, str(ROOT))
        with network_guard() as attempts, redirect_stdout(log), redirect_stderr(log):
            common = importlib.import_module("src.real_options_foundation.common")
            budget = common.WorkBudget(MAX_EVENTS, MAX_CPU_SECONDS)
            common.set_work_budget(budget)
            loader = unittest.TestLoader()
            suite = loader.discover(str(ROOT / "tests"), pattern="test_real_options_*.py", top_level_dir=str(ROOT))
            suite.run(result)
            budget.check()
        receipt["sources_after"] = source_manifest()
        receipt["sources_unchanged"] = receipt["sources_before"] == receipt["sources_after"]
        receipt["gate_counts"] = gate_counts(result.records)
        gates_ok = all(value["status"] == "PASS" for value in receipt["gate_counts"].values())
        passed = (result.testsRun > 0 and result.wasSuccessful() and not result.skipped
                  and not result.expectedFailures and all(record["status"] == "PASS" for record in result.records)
                  and gates_ok and receipt["sources_unchanged"] and not log.exceeded
                  and time.process_time() <= MAX_CPU_SECONDS
                  and time.monotonic() - started_wall <= MAX_WALL_SECONDS
                  and output_size(run_dir) <= MAX_OUTPUT_BYTES)
        if passed:
            receipt["status"] = "TECHNICAL_FIXTURE_PASS"
    except BaseException as exc:
        receipt["runner_error"] = {"type": type(exc).__name__, "message": str(exc)[:2000],
                                   "traceback": traceback.format_exc()[-8000:]}
    finally:
        if common is not None:
            common.set_work_budget(None)
        receipt.update({"tests_run": result.testsRun, "tests": result.records,
                        "failures": [test.id() for test, _ in result.failures],
                        "errors": [test.id() for test, _ in result.errors],
                        "skips": [test.id() for test, _ in result.skipped],
                        "gate_counts": gate_counts(result.records),
                        "event_operations": getattr(budget, "operations", 0),
                        "cpu_elapsed_seconds": format(time.process_time(), ".6f"),
                        "wall_elapsed_seconds": format(time.monotonic() - started_wall, ".6f"),
                        "network_guard": {"outbound_enabled": False, "guard_probe": "PASS" if attempts else "NOT_COMPLETED",
                                          "blocked_attempt_count": len(attempts), "blocked_methods": sorted(set(attempts))},
                        "git_after": git_state(), "captured_log_limit_exceeded": log.exceeded,
                        "interpretation": "Technical fixture checks only; no statistical, economic, live-data or deployment claim"})
        new_file(run_dir / "test_output.log", log.text().encode("utf-8", errors="replace"))
        receipt["output_bytes_before_receipt"] = output_size(run_dir)
        payload = json_payload(receipt)
        if receipt["output_bytes_before_receipt"] + len(payload) > MAX_OUTPUT_BYTES:
            receipt["status"] = "TECHNICAL_FIXTURE_FAIL"
            receipt["output_budget_exceeded"] = True
            payload = json_payload(receipt)
        new_file(run_dir / "receipt.json", payload)
    return 0 if receipt["status"] == "TECHNICAL_FIXTURE_PASS" else 1


def supervise(output_dir: Path) -> int:
    output_dir = output_dir.resolve()
    output_dir.mkdir(parents=True, exist_ok=True)
    run_id = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ") + "_" + uuid.uuid4().hex[:8]
    run_dir = output_dir / ("ro01_fixture_" + run_id)
    run_dir.mkdir(exist_ok=False)
    environment = dict(os.environ, PYTHONDONTWRITEBYTECODE="1", RO01_BOUNDED_WORKER="1")
    command = [sys.executable, "-B", str(Path(__file__).resolve()), "--worker", "--run-dir", str(run_dir)]
    started = time.monotonic()
    termination = None
    process = subprocess.Popen(command, cwd=str(ROOT), env=environment,
                               stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    try:
        while process.poll() is None:
            if time.monotonic() - started >= MAX_WALL_SECONDS:
                termination = "WALL_TIMEOUT"
                break
            try:
                if output_size(run_dir) > MAX_OUTPUT_BYTES:
                    termination = "OUTPUT_BUDGET_EXCEEDED"
                    break
            except (OSError, RuntimeError, ValueError):
                termination = "INVALID_OUTPUT_TREE"
                break
            time.sleep(0.05)
        if termination:
            process.kill()
        return_code = process.wait(timeout=5)
    except BaseException:
        process.kill()
        process.wait(timeout=5)
        raise
    receipt_path = run_dir / "receipt.json"
    try:
        receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        receipt = {}
    if termination or not receipt:
        fallback = {"schema": "real-options-foundation-ro01-technical-fixture-v1",
                    "classification": "technical_fixture", "status": "TECHNICAL_FIXTURE_FAIL",
                    "termination": termination or "WORKER_DID_NOT_COMPLETE_RECEIPT",
                    "worker_return_code": return_code, "tests_run": receipt.get("tests_run", 0),
                    "economic_metrics": {}, "scientific_execution": "NONE",
                    "git": git_state(), "sources": source_manifest(),
                    "output_bytes_observed": output_size(run_dir),
                    "wall_elapsed_seconds": format(time.monotonic() - started, ".6f"),
                    "cpu_elapsed_seconds": "UNAVAILABLE_AFTER_FORCED_TERMINATION"}
        receipt_path = run_dir / "termination_receipt.json"
        new_file(receipt_path, json_payload(fallback))
        receipt = fallback
    success = (return_code == 0 and termination is None and receipt.get("status") == "TECHNICAL_FIXTURE_PASS"
               and output_size(run_dir) <= MAX_OUTPUT_BYTES)
    print(json.dumps({"status": receipt.get("status"), "receipt": str(receipt_path),
                      "receipt_sha256": sha256(receipt_path), "tests_run": receipt.get("tests_run", 0),
                      "event_operations": receipt.get("event_operations"),
                      "cpu_elapsed_seconds": receipt.get("cpu_elapsed_seconds"),
                      "output_bytes": output_size(run_dir), "economic_evaluation": "NOT_PERFORMED"},
                     indent=2, sort_keys=True))
    return 0 if success else 1


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-dir", type=Path, default=ROOT / "output/ro01_validation")
    parser.add_argument("--worker", action="store_true", help=argparse.SUPPRESS)
    parser.add_argument("--run-dir", type=Path, help=argparse.SUPPRESS)
    arguments = parser.parse_args(argv)
    if arguments.worker:
        if arguments.run_dir is None or os.environ.get("RO01_BOUNDED_WORKER") != "1":
            parser.error("--worker is reserved for the bounded parent runner")
        return worker(arguments.run_dir)
    return supervise(arguments.output_dir)


if __name__ == "__main__":
    raise SystemExit(main())
