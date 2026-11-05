# Offline technical reproduction

Requires Python 3.9 or later and its standard library; no dependency installation, account, API key or live network is needed. From this extracted directory:

```text
python -B tools/validate_real_options_foundation_ro01.py --output-dir output/ro01_validation
```

The runner discovers only tests/test_real_options_*.py, blocks outbound socket operations, applies event/CPU/wall/output budgets and writes a new technical receipt. Inspect its exit code, named tests and D01-D12 gates. A fixture pass is not a financial result.

Packaging alone does not certify that this archive has passed fresh-extraction validation. Record that check and its source/archive hashes separately before calling it reproducible.

SOURCE_MANIFEST.json binds source bytes and records observed Git provenance; dirty working-copy contents are not represented as a sealed commit. No historic Git metadata or market data are included. No software/data licence is selected by this packaging tool. This is a local review artifact; publication and sharing need the owner's explicit decision.
