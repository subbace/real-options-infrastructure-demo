# Real-options hedging research laboratory

**Independent research following a completed master's thesis.**
Validated technical snapshot: 22 October 2026. Local portfolio; not published.

This project studies how to evaluate learned option-hedging policies when
market information, execution and accounting have explicit, testable
definitions. It combines quantitative research with practical data and
software engineering. The goal is a reproducible comparison of hedging risk
after costs, rather than an assumed trading return.

## Research problem

A strategy can appear effective because it sees unavailable information,
uses a synthetic option price as if it were a market quote, trades at a
non-executable price, or treats correlated windows as independent samples.
The laboratory makes those assumptions observable and separates technical
correctness from statistical and economic evidence.

The initial target is BTC inverse European options, with a matching dated
inverse future where validated instrument metadata permit it. The first
implementation block is offline and uses artificial fixtures. Real market
collection, model comparison and live operation are later, separate stages.

## Current evidence and stage

| Area | Current, evidence-bounded status |
|---|---|
| Prior research | Master's work investigated agent-based markets, learned hedging, distribution shift and replay on actual SPY underlying prices with synthetic options |
| Negative findings | The inherited studies did not establish robust neural superiority over Black–Scholes; those findings remain part of the record |
| Research governance | The post-thesis programme and data/ledger contract are versioned; chronological evaluation, SPENT data and comparison limits are explicit |
| RO-01 infrastructure | 59 artificial technical tests passed; all D01-D12 gates covered, with offline schemas, L2 reconstruction, conservative simulated execution and a reconciled ledger |
| Actual traded-option effectiveness | Not evaluated by this portfolio snapshot |
| Trading deployment or capital management | Not demonstrated or offered |

The historical SPY exercise is not described as a backtest of observed option
quotes. Passing artificial technical fixtures will not change that boundary
or establish financial profitability.

## Engineering implementation

- **Market-data provenance:** instrument identity, contract units, source
  payloads and availability timestamps, with explicit missing values.
- **Deterministic L2 replay:** initial snapshots and sequenced changes;
  invalidation on gaps/conflicts and recovery from a new snapshot.
- **Causal state construction:** only information received before a decision
  enters its features; quote, trade, index, mark and estimated Greeks remain
  distinct data types.
- **Conservative execution:** bid/ask-side fills, available depth, tick/size
  restrictions and partial fills. L2 alone does not establish queue priority.
- **Portfolio accounting:** cash, positions, fees, collateral and versioned
  settlement events, with idempotent replay and exact contract arithmetic.
- **Bounded verification:** hand-calculated artificial cases, deterministic
  hashes, negative tests and controlled failure scenarios without an account
  or trading credentials.

The complete fixture suite passed with 217 event operations and 0.531250 CPU
seconds on Python 3.9.1. These are engineering measurements, not market
performance. The technical receipt binds the tested source hashes; the
curated archive's manifest identifies its source revision and file hashes.

The liquidity model permits one simulated taker order per complete snapshot.
This conservatively prevents repeated use of the same observed liquidity;
it is not a calibrated queue or impact model. Margin checks and fees are
explicit fixture inputs, not an exchange margin or fee engine.

## Experimental approach

Begin with strong analytical, reduced-frequency and no-trade baselines, then
compare small inventory-aware, residual or recurrent policies within a
precommitted budget. Evaluate information, architecture and capacity as
separate hypotheses. Larger networks are not presumed to improve a hedge.

Future experiments will freeze calendar splits, permitted information,
execution assumptions, objectives and selection before opening the test.
Inference will address shared shocks and dependence between option episodes.
An inspected final test becomes SPENT; retrospective analysis is labelled
accordingly. Risk, costs, turnover and violations will accompany any reported
performance, including negative results and adverse regimes.

## Reproduction and reviewer access

From the extracted curated package, with Python 3.9 or later:

```text
python -B tools/validate_real_options_foundation_ro01.py --output-dir output/ro01_validation
```

No dependency installation or market account is required. The runner blocks
outbound sockets and writes a new receipt with named tests, gate coverage,
source hashes and resource usage. The expected result for this snapshot is
59 passed tests and D01-D12 PASS. Resource timings may vary.

A curated package contains only reviewed RO-01 source files,
labelled artificial fixtures, the tested validator, a concise reproduction
note and a per-file integrity manifest. It will exclude historical Git
history, raw market data, credentials, knowledge-base material and local
machine paths. External sharing and licensing remain decisions for the
project owner; no publication or invitation has been performed.

## Skills represented by the project

The work connects Python research software, market-data semantics,
event-driven replay, numerical accounting, reproducibility, failure testing
and cautious statistical interpretation. Its portfolio value is the ability
to build and explain auditable experiments, retain negative evidence and
state precisely what has and has not been validated.

This is an independent research portfolio. It does not claim doctoral
enrolment, a PhD qualification, institutional employment, an accepted paper
or an investment-performance record. AI assistance is documented in the
research record, with human responsibility for verification and claims.
