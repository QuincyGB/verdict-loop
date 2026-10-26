# verdict-loop

A small, copyable **reference buyer agent** for the x402 fleet: it shows how an
agent uses paid x402 services *inside its own decision loop* — screening tokens
before it would trade them, and vetting unfamiliar paid endpoints before it
would adopt them.

The two services it calls are live in production and priced in USDC on Base,
settled through the x402 v2 `exact` scheme:

| Service | Endpoint | Price | What it returns |
|---|---|---|---|
| Token Verdict | `POST https://token-verdict-production.up.railway.app/v1/verdict` | $0.02 | `SOLID / CAUTION / DANGER` + 0–100 risk score, six weighted signals, analyst take |
| RouteVerdict | `POST https://route-verdict-production.up.railway.app/v1/check` | $0.05 | `TRUSTED / CAUTION / AVOID` + 0–100 trust score for an x402 endpoint (liveness, terms, schema quality, catalog presence, diff) |

Both pay to the fleet wallet `0x097f9685D1e0752bF8B02d61E5Ce9be7eA0FBA7F`.

## Live demo — running daily, in public

This loop runs **live every day at 08:00 America/Toronto** from the
fleet's own agent wallet, under the $0.10/day cap, and every run is
appended to the public log: **[docs/live-log.md](docs/live-log.md)**.

> Self-funded demonstration run by Verdict Row (the seller) to show
> the monitoring-loop pattern. These are our own calls on our own
> routes — not customer traffic.

The runner is `scripts/run_daily.sh`; the log entries carry each
call's verdict, the decision it produced, and the settlement
transaction hash, so the spend is verifiable on-chain by anyone.

## Architecture (6 lines)

1. `verdict_loop/loop.py` runs one pass over a JSON watchlist (config file).
2. Every payment runs through **x402-guard** (see *Payment path* below): its pipeline pre-flights the target before the loop's money moves. Under the guard sits the same 402 flow as always: unpaid POST → parse the 402 challenge → (live only) EIP-3009/EIP-712 sign → retry with `PAYMENT-SIGNATURE`.
3. `verdict_loop/decide.py` maps verdicts to decisions with pure functions: WOULD_BUY only a `SOLID` token at risk ≤ 40; ADOPT only a `TRUSTED` service at trust ≥ 80.
4. `verdict_loop/budget.py` is a file-backed daily spend cap (default **$0.10**) that authorizes every payment *before* it is signed — the guard's own check calls included, via the budget object handed to it.
5. Dry-run is the default and cannot pay: it parses the real live challenge and reports the price it *would* pay and the standing policy — it never invents a verdict.
6. The Settled pre-flight is stage 1 of the guard's pipeline (advisory, plus one narrow veto — see *Pre-flight* below). `verdict_loop/settled_check.py` remains in this repo as the reference implementation the guard's port was taken from, with its own tests.

## Quickstart (dry-run first)

```bash
python3 -m venv .venv && .venv/bin/pip install -r requirements.txt
.venv/bin/pip install -e ../x402-guard/python   # the payment path (sibling repo; PyPI release pending)
cp config.example.json config.json        # edit the watchlist to taste
.venv/bin/python -m verdict_loop --config config.json
```

Expected output (also saved in `sample-run.log` from a real run):

```
=== verdict-loop pass @ ... — mode: DRY-RUN ===
[token] USD Coin (Base) (0x8335..., base): DRY-RUN would pay $0.02 to 0x097f... on eip155:8453 for a Token Verdict screening
        policy on the verdict: WOULD_BUY only if SOLID and risk score <= 40; otherwise SKIP
...
--- summary ---
would spend: $0.09 against a $0.10 daily cap
cap projection: all 3 calls fit under the cap
```

## Live mode (real money — read this first)

Live mode spends **real USDC on Base** from *your own* wallet. It requires
**both**:

- `--live` on the command line, **and**
- a signer in the environment: `AGENT_PRIVATE_KEY` (0x-prefixed EVM key) or
  `AGENT_KEY_FILE` (path to a file containing it).

```bash
AGENT_PRIVATE_KEY=0x... .venv/bin/python -m verdict_loop --config config.json --live
```

- The daily cap (config `daily_cap_usd`, default **$0.10**) is enforced in
  code before any signature: a payment that would break the cap is reported
  `BLOCKED` and never signed. Settled payments are recorded in
  `verdict-loop-budget.json` (gitignored — it is a spending record).
- A **balance guard** runs before the pass: the planned calls are priced
  with unpaid probes and the payer's USDC balance is read from the chain.
  A known balance below the planned spend stops the run cleanly
  (`INSUFFICIENT FUNDS`, exit code **3**) before anything is signed —
  never mid-screen. If the balance cannot be read at all (public RPCs
  down), the run warns and proceeds on the cap alone.
- The cap ledger resets on the UTC day boundary.
- Start with the default watchlist: a full pass costs $0.09 in service
  calls, plus up to $0.005 of x402-guard drift checks when its cache is
  cold (the watchlist's calls share one endpoint, so one Recheck look
  covers the pass) — $0.095 worst case, inside the cap. Raising the cap
  or the watchlist is your explicit choice, in the config.
- **Cap stops degrade in a fixed order, and are not errors.** Guard
  check spend shares the cap (above), so a day that starts with spend
  already on the ledger may not fit a whole pass. When the remaining
  budget cannot cover the next stage, the pass skips the *optional
  service check* first — priced worst-case (fresh guard checks
  included) before it starts — and never skips token screens for cap
  reasons. The run prints a `cap stop:` summary line, the public log
  records the stop as a completed policy outcome, and the exit code
  stays 0 unless a real error also occurred. (This ordering is the
  fix for the 2026-10-25 08:00 run, where a cap refusal escaped the
  guard as an exception, crashed the pass after its token screens
  had settled, and the day's log entry was lost.)
- Never commit a key. `.gitignore` already excludes `*.key` and `.env`.

## Configuration

`config.json` (see `config.example.json`):

- `tokens`: `[{address, chain, label}]` — token contracts to screen each pass.
- `services_to_check`: x402 resource URLs to vet with RouteVerdict.
- `policy.max_risk_score` (default 40), `policy.min_trust_score` (default 80).
- `daily_cap_usd` (default 0.10), `budget_state` (ledger path).
- `token_verdict_url` / `route_verdict_url`: endpoint overrides.
- `settled_check` (default `true`): the Settled pre-flight below. The
  `--settled` / `--no-settled` flags and the `SETTLED_CHECK` env var
  (`0`/`false`/`no`/`off` disables) override it, in that order.
- `guard`: `{store_path, audit_log_path, drift_enabled, drift_ttl_seconds,
  recheck_url}` — the x402-guard payment path's local state and drift
  stage (below). Defaults: `x402-guard.db` + `x402-guard-audit.jsonl`
  in the working directory, drift on, 24h TTL.

## How the fleet plugs in

The payment flow in `x402.py` is the standard x402 v2 `exact` flow on Base
(same shape as the fleet's own MCP wrappers in
[QuincyGB/token-verdict-tools](https://github.com/QuincyGB/token-verdict-tools)):

1. POST unpaid → HTTP 402, challenge base64 in the `payment-required` header.
2. Select the `exact` / `eip155:8453` entry from `accepts`.
3. Build an EIP-3009 `TransferWithAuthorization` (to `payTo`, value `amount`,
   `validBefore = now + maxTimeoutSeconds`, random nonce).
4. Sign as EIP-712 with the domain from `accepts.extra` (USDC: name
   `USD Coin`, version `2`, chainId 8453, verifyingContract = the USDC asset).
5. Retry with the payload base64 in `PAYMENT-SIGNATURE`; the service's
   facilitator settles, and the `payment-response` header carries the receipt.

To point the loop at your own x402 services instead, change the two URLs in
the config and the decision functions in `decide.py` — the payment plumbing
and the spend cap are service-agnostic.

## Pre-flight: check the inspector's record first (Settled)

RouteVerdict grades an endpoint by probing it. [Settled](https://settled.tools)
grades endpoints the other way: its scout actually *buys* from them and keeps
the receipt — paid, delivered (or not), and whether the response matched the
advertised schema. So before the loop pays RouteVerdict to vet a new service,
it asks Settled, for free, what Settled's own money found:

- **Hard negative on record** — a delivery receipt with `delivered=false`,
  or an explicit not-payable verdict → the service is **not adopted,
  whatever RouteVerdict says**. In live mode the paid check is skipped
  entirely; in dry-run the note is printed alongside the would-pay line.
  A receipt's comparison verdict (`as_advertised`, `partial_match`,
  `nothing_to_compare`, ...) never vetoes on its own — it grades the
  listing's sample, not the delivery. `nothing_to_compare` in
  particular (Settled's copy of the listing has no usable sample to
  compare fields against) is logged distinctly and, when delivery is
  verified, the loop proceeds on that verified delivery.
- **`delivery_verified: true`** → the ADOPT line is annotated as
  corroborated. That is all it does: the TRUSTED ≥ 80 rule is never
  loosened by a Settled record.
- **Settled doesn't know the endpoint, or is unreachable** → the pass
  proceeds exactly as without the pre-flight. An outage never blocks
  the loop.

The lookup runs over Settled's free MCP endpoint (`tools/call
settled_check`, no credentials) and is read-only: it costs nothing and
never touches the spend cap. It is **on by default** — disable it with
`--no-settled`, `SETTLED_CHECK=0`, or `"settled_check": false` in the
config. In dry-run the lookup is performed for real (a free read changes
nothing about the no-payment contract); the test suite stays hermetic by
playing Settled over a mock transport, like everything else here.

The pattern is the point of this repo, so steal it: *before your agent's
first payment to an unfamiliar endpoint, check the delivery record of
someone who has already paid it.*

## Payment path: x402-guard (dogfood)

This loop is the reference deployment of
[x402-guard](https://github.com/QuincyGB/x402-guard) — Verdict Row's
buyer-side middleware. The loop doesn't call the services directly
any more; every payment is made by the guard's `GuardedClient`,
which runs this pipeline *before anything is signed*:

1. **Settled pre-flight** (free) — the stage described above.
2. **Drift check** — StallRow Recheck ($0.005) fingerprints the
   target's live payment terms, cached 24h in the guard's local
   store: a moved `payTo` or asset blocks the payment; a price move
   over 20% blocks; lesser changes warn.
3. **RouteVerdict gate** — first payments ≥ $0.10 would require a
   TRUSTED verdict (the loop's own calls are all below that, so the
   gate is armed but never fires here).
4. **Caps** — the loop's `DailySpendCap`, handed to the guard as its
   budget: check calls and service calls alike are authorized and
   recorded against the one $0.10/day cap.

The guard's drift checks for this loop's watchlist endpoint are
covered by a recheck pack where configured; the $0.10/day cap still
authorizes every spend — pack mint included — before anything is
signed.

Every decision lands in the guard's audit log (config
`guard.audit_log_path`, JSONL, gitignored) — the loop's own stdout
format and this log's format are unchanged by the integration, and
`tests/test_guard_integration.py` proves the guard is what's
executing (a drift block stops a service payment before RouteVerdict
is paid; a second pass inside the TTL makes no second Recheck call).

## Tests

Offline (the 402 fixtures are real challenges captured from the live
services; payments are played by an in-process mock transport):

```bash
.venv/bin/pip install -r requirements-dev.txt
.venv/bin/python -m pytest -q
```

Coverage: challenge parsing against the captured real 402 bodies,
verdict→decision mapping (including the services' own published example
outputs), spend-cap enforcement — including that the cap refuses a
payment *before* anything is signed and that a dry run can never spend —
and the Settled pre-flight: captured real `settled_check` records
(corroborated / known-untested / unknown), the veto and its narrowness,
and outage degradation, all driven through mock transports in full
loop passes — plus the x402-guard integration: the guard executing
the loop's payments, its audit log and drift cache, a drift block,
and cache reuse across passes.

## License

MIT — see `LICENSE`. Built as a reference for the x402 fleet
(Token Verdict / RouteVerdict / ListSmith / StallRow by QuincyGB).
