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

## Architecture (5 lines)

1. `verdict_loop/loop.py` runs one pass over a JSON watchlist (config file).
2. Every call goes through `verdict_loop/x402.py`: unpaid POST → parse the 402 challenge → (live only) EIP-3009/EIP-712 sign → retry with `PAYMENT-SIGNATURE`.
3. `verdict_loop/decide.py` maps verdicts to decisions with pure functions: WOULD_BUY only a `SOLID` token at risk ≤ 40; ADOPT only a `TRUSTED` service at trust ≥ 80.
4. `verdict_loop/budget.py` is a file-backed daily spend cap (default **$0.10**) that authorizes every payment *before* it is signed.
5. Dry-run is the default and cannot pay: it parses the real live challenge and reports the price it *would* pay and the standing policy — it never invents a verdict.

## Quickstart (dry-run first)

```bash
python3 -m venv .venv && .venv/bin/pip install -r requirements.txt
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
- The cap ledger resets on the UTC day boundary.
- Start with the default watchlist: a full pass costs $0.09, inside the cap.
  Raising the cap or the watchlist is your explicit choice, in the config.
- Never commit a key. `.gitignore` already excludes `*.key` and `.env`.

## Configuration

`config.json` (see `config.example.json`):

- `tokens`: `[{address, chain, label}]` — token contracts to screen each pass.
- `services_to_check`: x402 resource URLs to vet with RouteVerdict.
- `policy.max_risk_score` (default 40), `policy.min_trust_score` (default 80).
- `daily_cap_usd` (default 0.10), `budget_state` (ledger path).
- `token_verdict_url` / `route_verdict_url`: endpoint overrides.

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

## Tests

Offline (the 402 fixtures are real challenges captured from the live
services; payments are played by an in-process mock transport):

```bash
.venv/bin/pip install -r requirements-dev.txt
.venv/bin/python -m pytest -q
```

Coverage: challenge parsing against the captured real 402 bodies,
verdict→decision mapping (including the services' own published example
outputs), and spend-cap enforcement — including that the cap refuses a
payment *before* anything is signed and that a dry run can never spend.

## License

MIT — see `LICENSE`. Built as a reference for the x402 fleet
(Token Verdict / RouteVerdict / ListSmith / StallRow by QuincyGB).
