"""Record all three bounded validation steps without hiding failed attempts.

Raw process logs may include local paths, so they remain in an ignored local
directory. The JSON report records portable commands, exit codes and measured
wall times. Process CPU for the original worker and demo is provided by each
runner; no platform-independent child-CPU measurement is invented here.
"""
import argparse
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import platform
import re
import subprocess
import sys
import time

ROOT = Path(__file__).resolve().parents[1]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--label", required=True)
    args = parser.parse_args()
    if not re.fullmatch(r"[a-zA-Z0-9_-]{1,40}", args.label):
        parser.error("Use a short label containing letters, digits, underscores or hyphens")
    report_path = ROOT / "validation" / ("validation_" + args.label + ".json")
    if report_path.exists():
        raise FileExistsError("Validation label already recorded; preserve the attempt and use a new label")
    log_dir = ROOT / "validation/private_logs" / args.label
    log_dir.mkdir(parents=True)
    steps = [
        ("original_ro01", ["tools/validate_real_options_foundation_ro01.py", "--output-dir", "output/ro01_" + args.label]),
        ("public_wrapper_tests", ["-m", "unittest", "discover", "-s", "demo_tests", "-v"]),
        ("public_demo", ["-m", "examples.run_demo", "--output", "output/demo_" + args.label]),
    ]
    report = {"schema": "ro01-public-validation-v1", "label": args.label,
        "generated_utc": datetime.now(timezone.utc).isoformat(),
        "python_version": platform.python_version(), "python_implementation": platform.python_implementation(),
        "platform": platform.system(), "machine": platform.machine(), "third_party_dependencies": [],
        "command_interpreter": "python means the interpreter running this validator",
        "commands": [], "original_research_replicated": False, "economic_validation": False}
    environment = dict(os.environ, PYTHONDONTWRITEBYTECODE="1")
    for name, arguments in steps:
        command = [sys.executable, "-B"] + arguments
        started = time.perf_counter()
        timed_out = False
        try:
            result = subprocess.run(command, cwd=str(ROOT), env=environment,
                capture_output=True, timeout=90)
            code, out, err = result.returncode, result.stdout, result.stderr
        except subprocess.TimeoutExpired as error:
            timed_out = True
            code, out, err = 124, error.stdout or b"", error.stderr or b""
        elapsed = time.perf_counter() - started
        (log_dir / (name + ".stdout.txt")).write_bytes(out)
        (log_dir / (name + ".stderr.txt")).write_bytes(err)
        item = {"step": name, "command": ["python", "-B"] + arguments,
                "exit_code": code, "wall_seconds": round(elapsed, 6), "timed_out": timed_out}
        try:
            parsed = json.loads(out.decode("utf-8"))
            item["runner_summary"] = {key: value for key, value in parsed.items()
                if key not in {"receipt"}}
        except (ValueError, UnicodeError):
            # unittest writes its individual case results to stderr. Retain all
            # named results locally and publish only the relevant outcome text.
            lines = err.decode("utf-8", errors="replace").splitlines()
            item["result_lines"] = [line for line in lines if line.startswith("Ran ")
                                    or line in {"OK", "FAILED"} or line.startswith("FAILED (")]
        report["commands"].append(item)
        # Persist each attempt, including any earlier failure, before proceeding.
        report_path.parent.mkdir(parents=True, exist_ok=True)
        report_path.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    report["status"] = "PASS" if all(item["exit_code"] == 0 for item in report["commands"]) else "FAIL"
    report_path.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps({"status": report["status"], "report": report_path.relative_to(ROOT).as_posix(),
                      "steps": [{"step": x["step"], "exit_code": x["exit_code"], "wall_seconds": x["wall_seconds"]}
                                for x in report["commands"]]}))
    return 0 if report["status"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
