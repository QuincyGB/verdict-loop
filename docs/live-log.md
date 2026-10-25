# verdict-loop — live demo log

> **Self-funded demonstration run by Verdict Row (the seller) to show the
> monitoring-loop pattern. These are our own calls on our own routes —
> not customer traffic.**

One entry per daily live run (08:00 America/Toronto), appended by
`scripts/run_daily.sh`. Every run screens the watchlist in
[`config.json`](../config.json) under the $0.10/day spend cap, which is
enforced in code before anything is signed, and behind a balance
guard: a known payer balance below the planned spend stops the run
cleanly (INSUFFICIENT FUNDS, nothing signed) instead of failing
mid-screen. Settlement transaction hashes are recorded per call so
anyone can verify the spend on BaseScan.

---
## 2026-10-25 — live run

- **Balance guard:** payer held $0.731957 USDC; planned spend $0.09.
- **Tokens screened:**
  - Wrapped Ether (Base) (WETH): verdict **SOLID**, risk 17.3 → **WOULD_BUY** (SOLID with risk score 17.3 <= max 40)
    - take: WETH (Wrapped Ether) trades at $2365.19 on uniswap with $8.46M in liquidity. On the positive side: Deep liquidity ($8,463,813) — the book ca
    - settlement tx: [`0xa3033243a99ea26fb6aab6d3b99fbcf8c84031cdad0feaeb7ca415c95a566f0a`](https://basescan.org/tx/0xa3033243a99ea26fb6aab6d3b99fbcf8c84031cdad0feaeb7ca415c95a566f0a)
  - Aerodrome AERO (Base) (AERO): verdict **SOLID**, risk 8.2 → **WOULD_BUY** (SOLID with risk score 8.2 <= max 40)
    - take: AERO (Aerodrome) trades at $0.6888 on aerodrome with $7.87M in liquidity. On the positive side: Deep liquidity ($7,874,478) — the book can a
    - settlement tx: [`0x6cda412a969be82a5cb6b995b065d2882a45aa192d3d256b6a498d7ea7d984cf`](https://basescan.org/tx/0x6cda412a969be82a5cb6b995b065d2882a45aa192d3d256b6a498d7ea7d984cf)
- **Settled pre-flight:**
  - https://token-verdict-production.up.railway.app/v1/verdict: Settled knows this endpoint, status live, quality 82/100, delivery VERIFIED by a Settled test purchase
- **Services vetted:**
  - https://token-verdict-production.up.railway.app/v1/verdict: **PASS** (Settled pre-flight veto — paid check skipped, nothing paid)
- **Calls:** 2 planned, 0 errors.
- **Spent:** $0.04 this run ($0.04 today of $0.10 cap) · **Cumulative logged spend: $0.040000**

<details><summary>Full run output</summary>

```text
=== verdict-loop pass @ 2026-10-25T05:01:22Z — mode: LIVE ===
payer: 0xa4f183a6799F0310FcCC545B07F2DcC960223de2 | daily cap: $0.10 | already spent today: $0.00
balance guard: payer holds $0.731957 USDC on Base; planned spend $0.09
[token] Wrapped Ether (Base) (WETH): verdict SOLID risk 17.3 -> WOULD_BUY (SOLID with risk score 17.3 <= max 40)
        take: WETH (Wrapped Ether) trades at $2365.19 on uniswap with $8.46M in liquidity. On the positive side: Deep liquidity ($8,463,813) — the book ca
        settlement tx: 0xa3033243a99ea26fb6aab6d3b99fbcf8c84031cdad0feaeb7ca415c95a566f0a
[token] Aerodrome AERO (Base) (AERO): verdict SOLID risk 8.2 -> WOULD_BUY (SOLID with risk score 8.2 <= max 40)
        take: AERO (Aerodrome) trades at $0.6888 on aerodrome with $7.87M in liquidity. On the positive side: Deep liquidity ($7,874,478) — the book can a
        settlement tx: 0x6cda412a969be82a5cb6b995b065d2882a45aa192d3d256b6a498d7ea7d984cf
[settled] https://token-verdict-production.up.railway.app/v1/verdict: Settled knows this endpoint, status live, quality 82/100, delivery VERIFIED by a Settled test purchase
        Settled hard negative: Settled's delivery receipt verdict is 'nothing_to_compare', not 'as_advertised'
[service] https://token-verdict-production.up.railway.app/v1/verdict: -> PASS (Settled pre-flight veto — RouteVerdict check skipped, nothing paid)
--- summary ---
calls planned: 2 | errors: 0
spent this pass: $0.04 | spent today: $0.04 of $0.10 cap
```

</details>

<!-- entry spent_usd=0.040000 cumulative_usd=0.040000 -->
