# RO-01 — Offline market data and ledger foundation

Effective date: 2026-10-21. Base: RO-00 closed at
`dc62c14a04e9fd42c900d398bb30ca1f18af3bd2` and its verified KB receipt.
Mode: `TECHNICAL_VALIDATION_ONLY`; no scientific experiment or performance claim.

## Authorized action

Implement a new standard-library Python 3.9 package, separate from all thesis
producers: `src/real_options_foundation/`. Implement requirement-level tests,
a bounded validation runner and a curated local portfolio source archive.
Document hypotheses, changes, failures and limitations for potential academic
publication and recruiter review. No repository publication is implied by
the user's tentative GitHub suggestion. Connected GitHub may be inspected
read-only; no external upload, invitation or messaging is part of this block.

The governing data contract is `REAL_OPTIONS_DATA_AND_LEDGER_CONTRACT_V1.md`.
Fixtures are artificial examples, never real acquired observations or
simulated market trajectories. Source documentation is consulted read-only.

## Implementation boundaries

- Exact finite Decimal inputs for contract arithmetic; refuse float/bool/NaN.
- Immutable instrument metadata and event payloads; recursive normalization
  of MappingProxyType/read-only mappings before new JSON serialization.
- Separate exchange, receive-UTC and receive-monotonic time, event identity,
  payload hash, transport state and book sequence. A duplicate is idempotent;
  a conflicting identity is an error, not silently replaced evidence.
- L2 snapshots/deltas with fail-closed gaps, reconnect and malformed data.
  Two-sided crossed books cannot be used. No fabricated quote for an empty side.
- An offline taker depth walk, partial/rejected execution and native size/tick
  validation. No inferred queue position or maker execution. Consumed liquidity
  cannot be assigned again to another simulated order.
- BTC cash, option quantities in BTC and inverse-future quantities in USD;
  reciprocal-price future P&L, explicit fees/margin reservation and two-stage
  option expiry under the documented post-August-2026 convention. No live margin
  adequacy or default fee/precision certification.
- Atomic ledger batches and append-only hash-chained records; repeated replay
  yields the same state. Invalid events leave financial state unchanged.
- Public-method/channel allowlist with injectable offline transport, bounded
  retry and explicit fault receipts; production network transport is absent.
- Quote/trade/mark/provider estimates remain distinct. Missing values retain
  missingness; causal joins require receive-time availability and configured
  age/skew bounds. No forward-fill across invalid state.

## Fixed technical gates

All D01–D12 from the data contract must pass through named tests. At minimum:

| Gate | Adversarial or hand-calculated requirement |
|---|---|
| D01 | wrong instrument family/units, incomplete metadata, tick/lot violations |
| D02 | full replacement, insert/update/delete and deterministic sorted book |
| D03 | gap, reordered change, conflicting duplicate, reconnect and resnapshot |
| D04 | no future receipt/estimate, missing timestamps, rollback and boundary ages |
| D05 | ticker/trade/mark cannot substitute for an executable book |
| D06 | bid/ask walk, partial liquidity, no depth reuse or double spread charge |
| D07 | option premium, inverse futures close/reversal, fees, margin/equity identity |
| D08 | call/put and OTM/ITM expiry, two events, no second generated delivery fee |
| D09 | duplicate replay stable; conflicting IDs rejected; immutable journal |
| D10 | timeout, throttling, malformed message and failed durable write |
| D11 | source references, artificial-fixture labels and complete technical receipt |
| D12 | network blocked during all validation; no credentials/private methods |

Validation uses the canonical interpreter without installation. Limits per
whole suite: 20,000 event operations, 60 seconds total CPU, 100,000,000 bytes
of output. A wall timeout and measured process CPU complement event accounting.
Budget violation or any failed test prevents closure and merge.
Receipts bind code/config/test hashes and the pre-run protocol Git commit;
technical receipts cannot close ID/OOD or profitability gates.

## Research and sharing records

`docs/RESEARCH_LOG.md` records each block and its outcome, including negative
findings. `docs/PUBLICATION_AND_PORTFOLIO_PLAN.md` defines claim/evidence,
precommitment, data rights and sharing boundaries. A concise English portfolio
overview states current evidence without claiming a PhD position or model win.
The curated archive contains only explicitly allowed new source, tests and
portable documentation; no Git history, KB, credentials, raw market data,
historic results or local machine paths. A licence is not chosen automatically.
The archive must validate offline in a fresh extraction before being described
as reproducible. No GitHub URL to a new research repository may be invented.

## Closure and next block

Keep all legacy scientific files/results unchanged relative to RO-00.
Record technical results, source references and limitations; commit on the
feature branch, fast-forward clean master only after gates pass, then perform
one KB refresh and write a post-commit handoff outside the repository.
Preserve the thesis source snapshot without new editorial modifications.

The sole next block is `REAL_OPTIONS_PUBLIC_DATA_PILOT_RO02_PROTOCOL`:
freeze universe, request/duration/storage caps, staleness/skew/latency rules,
source terms and data-quality gates before any real acquisition. It may close
with insufficient data quality; it does not authorize training or broker use.
No RO-02 feed collection is executed by RO-01.
