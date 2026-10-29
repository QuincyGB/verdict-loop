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

## 2026-10-25 — live run (08:00 America/Toronto) — completed with cap stop · recovered/backfilled entry

- **Recovered entry:** backfilled after the fact on 2026-10-25 from the cron run record, the budget ledger, the x402-guard audit log, and the settlement transactions below. The original run's entry was never written: a spend-cap refusal escaped the guard as an exception and crashed the pass, and the log append then failed with `KeyError 'spent_today'`. Both faults are fixed in the commit that adds this entry. The original stdout transcript was not retained, so no raw log is attached to this entry — every figure below comes from the records named above.
- **Balance guard:** payer held $0.691957 USDC; planned spend $0.09.
- **Tokens screened:**
  - Wrapped Ether (Base) (WETH): verdict **SOLID**, risk 16.4 → **WOULD_BUY** (SOLID with risk score 16.4 <= max 40)
    - settlement tx: [`0xe4ff82a8b1ab1e49b54fab612c658273f91d657b610484107513a667991d1a82`](https://basescan.org/tx/0xe4ff82a8b1ab1e49b54fab612c658273f91d657b610484107513a667991d1a82)
  - Aerodrome AERO (Base) (AERO): verdict **SOLID**, risk 8.2 → **WOULD_BUY** (SOLID with risk score 8.2 <= max 40)
    - settlement tx: [`0x6ea20a29653ff652c13d40539e5f2ecc40a9b529cc8e2db2ec13e99efc9be774`](https://basescan.org/tx/0x6ea20a29653ff652c13d40539e5f2ecc40a9b529cc8e2db2ec13e99efc9be774)
- **Guard checks:** one StallRow Recheck drift check ($0.005, result BASELINE) ran during the first token screen; the second screen used the guard's cache. Check spend shares the daily cap by design.
- **Services vetted:**
  - https://token-verdict-production.up.railway.app/v1/verdict: **SKIPPED — cap stop** (the optional service check is the first stage dropped; paying its $0.05 would have brought the day to $0.135, over the $0.10 cap — $0.085 was already spent: $0.04 by the 05:01 UTC pass above, $0.045 by this one). No Settled pre-flight line and no ADOPT/PASS were produced for this stage.
- **Calls:** 2 token screens settled, 1 guard drift check settled, service check skipped (cap stop), 0 service errors.
- **Spent:** $0.045000 this run ($0.085 today of $0.10 cap) · **Cumulative logged spend: $0.085000**

<!-- entry spent_usd=0.045000 cumulative_usd=0.085000 -->
## 2026-10-26 — live run

- **Balance guard:** payer held $5.055438 USDC; planned spend $0.09.
- **Tokens screened:**
  - Wrapped Ether (Base) (WETH): verdict **SOLID**, risk 11.8 → **WOULD_BUY** (SOLID with risk score 11.8 <= max 40)
    - take: WETH (Wrapped Ether) trades at $2333.93 on uniswap with $531.1k in liquidity. On the positive side: Deep liquidity ($531,058) — the book can
    - settlement tx: [`0xc816952ff85ff7c5b4e6a38e6bc68a97007e1c2fb4c4ef508c3ca15d65917f99`](https://basescan.org/tx/0xc816952ff85ff7c5b4e6a38e6bc68a97007e1c2fb4c4ef508c3ca15d65917f99)
  - Aerodrome AERO (Base) (AERO): verdict **SOLID**, risk 12.7 → **WOULD_BUY** (SOLID with risk score 12.7 <= max 40)
    - take: AERO (Aerodrome) trades at $0.6647 on aerodrome with $7.12M in liquidity. On the positive side: Deep liquidity ($7,115,272) — the book can a
    - settlement tx: [`0xc4f59588fa7717de3787ce9518dde7ce9e29124dd1e5b9188726bbf8e5a528c5`](https://basescan.org/tx/0xc4f59588fa7717de3787ce9518dde7ce9e29124dd1e5b9188726bbf8e5a528c5)
- **Settled pre-flight:**
  - https://token-verdict-production.up.railway.app/v1/verdict: Settled knows this endpoint, status live, quality 79/100, delivery VERIFIED by a Settled test purchase, latest receipt had nothing to compare (no usable sample in Settled's listing) — proceeding on verified delivery
- **Services vetted:**
  - https://token-verdict-production.up.railway.app/v1/verdict: verdict **TRUSTED**, trust 95 → **ADOPT** (TRUSTED with trust score 95 >= min 80)
    - settlement tx: [`0x8f7fb7faf0d9d59979d5ca7a2d0090c02913cdb185514741bda520b226ba7b25`](https://basescan.org/tx/0x8f7fb7faf0d9d59979d5ca7a2d0090c02913cdb185514741bda520b226ba7b25)
- **Calls:** 3 planned, 0 errors.
- **Spent:** $0.10 this run ($0.10 today of $0.10 cap) · **Cumulative logged spend: $0.180000**

<details><summary>Full run output</summary>

```text
=== verdict-loop pass @ 2026-10-26T11:57:11Z — mode: LIVE ===
payer: 0xa4f183a6799F0310FcCC545B07F2DcC960223de2 | daily cap: $0.10 | already spent today: $0.00
balance guard: payer holds $5.055438 USDC on Base; planned spend $0.09
[token] Wrapped Ether (Base) (WETH): verdict SOLID risk 11.8 -> WOULD_BUY (SOLID with risk score 11.8 <= max 40)
        take: WETH (Wrapped Ether) trades at $2333.93 on uniswap with $531.1k in liquidity. On the positive side: Deep liquidity ($531,058) — the book can
        settlement tx: 0xc816952ff85ff7c5b4e6a38e6bc68a97007e1c2fb4c4ef508c3ca15d65917f99
[token] Aerodrome AERO (Base) (AERO): verdict SOLID risk 12.7 -> WOULD_BUY (SOLID with risk score 12.7 <= max 40)
        take: AERO (Aerodrome) trades at $0.6647 on aerodrome with $7.12M in liquidity. On the positive side: Deep liquidity ($7,115,272) — the book can a
        settlement tx: 0xc4f59588fa7717de3787ce9518dde7ce9e29124dd1e5b9188726bbf8e5a528c5
[settled] https://token-verdict-production.up.railway.app/v1/verdict: Settled knows this endpoint, status live, quality 79/100, delivery VERIFIED by a Settled test purchase, latest receipt had nothing to compare (no usable sample in Settled's listing) — proceeding on verified delivery
[service] https://token-verdict-production.up.railway.app/v1/verdict: verdict TRUSTED trust 95 -> ADOPT (TRUSTED with trust score 95 >= min 80)
        corroborated by Settled: its scout's test purchase of this endpoint delivered as advertised — the adoption stands on RouteVerdict's rule alone; Settled only confirms it
        settlement tx: 0x8f7fb7faf0d9d59979d5ca7a2d0090c02913cdb185514741bda520b226ba7b25
--- summary ---
calls planned: 3 | errors: 0
spent this pass: $0.095 | spent today: $0.095 of $0.10 cap
```

</details>

<!-- entry spent_usd=0.095000 cumulative_usd=0.180000 -->
## 2026-10-27 — live run

- **Balance guard:** payer held $10.110438 USDC; planned spend $0.09.
- **Tokens screened:**
  - Wrapped Ether (Base) (WETH): verdict **SOLID**, risk 11.8 → **WOULD_BUY** (SOLID with risk score 11.8 <= max 40)
    - take: WETH (Wrapped Ether) trades at $2313.52 on pancakeswap with $4.45M in liquidity. On the positive side: Deep liquidity ($4,447,347) — the boo
    - settlement tx: [`0xf22e80fcb7aef4b8cc76e569ebd716f96d09069fcd1dd496fe89fe9d51798cc6`](https://basescan.org/tx/0xf22e80fcb7aef4b8cc76e569ebd716f96d09069fcd1dd496fe89fe9d51798cc6)
  - Aerodrome AERO (Base) (AERO): verdict **SOLID**, risk 8.2 → **WOULD_BUY** (SOLID with risk score 8.2 <= max 40)
    - take: AERO (Aerodrome) trades at $0.6773 on aerodrome with $6.99M in liquidity. On the positive side: Deep liquidity ($6,990,280) — the book can a
    - settlement tx: [`0x263c510fa71dad8703ab5d8239dc0b4c87129e37053b585d247115b919fb2c6d`](https://basescan.org/tx/0x263c510fa71dad8703ab5d8239dc0b4c87129e37053b585d247115b919fb2c6d)
- **Settled pre-flight:**
  - https://token-verdict-production.up.railway.app/v1/verdict: Settled knows this endpoint, status live, quality 79/100, delivery VERIFIED by a Settled test purchase, latest receipt had nothing to compare (no usable sample in Settled's listing) — proceeding on verified delivery
- **Services vetted:**
  - https://token-verdict-production.up.railway.app/v1/verdict: verdict **TRUSTED**, trust 95 → **ADOPT** (TRUSTED with trust score 95 >= min 80)
    - settlement tx: [`0x27198044dcc12f52c49286f9a7099a5e8bde85a84fcc05fc7c949f54bc927fd3`](https://basescan.org/tx/0x27198044dcc12f52c49286f9a7099a5e8bde85a84fcc05fc7c949f54bc927fd3)
- **Calls:** 3 planned, 0 errors.
- **Spent:** $0.10 this run ($0.10 today of $0.10 cap) · **Cumulative logged spend: $0.275000**

<details><summary>Full run output</summary>

```text
=== verdict-loop pass @ 2026-10-27T11:57:17Z — mode: LIVE ===
payer: 0xa4f183a6799F0310FcCC545B07F2DcC960223de2 | daily cap: $0.10 | already spent today: $0.00
balance guard: payer holds $10.110438 USDC on Base; planned spend $0.09
[token] Wrapped Ether (Base) (WETH): verdict SOLID risk 11.8 -> WOULD_BUY (SOLID with risk score 11.8 <= max 40)
        take: WETH (Wrapped Ether) trades at $2313.52 on pancakeswap with $4.45M in liquidity. On the positive side: Deep liquidity ($4,447,347) — the boo
        settlement tx: 0xf22e80fcb7aef4b8cc76e569ebd716f96d09069fcd1dd496fe89fe9d51798cc6
[token] Aerodrome AERO (Base) (AERO): verdict SOLID risk 8.2 -> WOULD_BUY (SOLID with risk score 8.2 <= max 40)
        take: AERO (Aerodrome) trades at $0.6773 on aerodrome with $6.99M in liquidity. On the positive side: Deep liquidity ($6,990,280) — the book can a
        settlement tx: 0x263c510fa71dad8703ab5d8239dc0b4c87129e37053b585d247115b919fb2c6d
[settled] https://token-verdict-production.up.railway.app/v1/verdict: Settled knows this endpoint, status live, quality 79/100, delivery VERIFIED by a Settled test purchase, latest receipt had nothing to compare (no usable sample in Settled's listing) — proceeding on verified delivery
[service] https://token-verdict-production.up.railway.app/v1/verdict: verdict TRUSTED trust 95 -> ADOPT (TRUSTED with trust score 95 >= min 80)
        corroborated by Settled: its scout's test purchase of this endpoint delivered as advertised — the adoption stands on RouteVerdict's rule alone; Settled only confirms it
        settlement tx: 0x27198044dcc12f52c49286f9a7099a5e8bde85a84fcc05fc7c949f54bc927fd3
--- summary ---
calls planned: 3 | errors: 0
spent this pass: $0.095 | spent today: $0.095 of $0.10 cap
```

</details>

<!-- entry spent_usd=0.095000 cumulative_usd=0.275000 -->
## 2026-10-28 — live run

- **Balance guard:** payer held $3.623438 USDC; planned spend $0.09.
- **Tokens screened:**
  - Wrapped Ether (Base) (WETH): verdict **SOLID**, risk 16.4 → **WOULD_BUY** (SOLID with risk score 16.4 <= max 40)
    - take: WETH (Wrapped Ether) trades at $2359.33 on uniswap with $522.6k in liquidity. On the positive side: Deep liquidity ($522,634) — the book can
    - settlement tx: [`0xda2bfba53d644340cecd3946e04de0e8194a7c34c5b47549829ec32fa0a28eaf`](https://basescan.org/tx/0xda2bfba53d644340cecd3946e04de0e8194a7c34c5b47549829ec32fa0a28eaf)
  - Aerodrome AERO (Base) (AERO): verdict **SOLID**, risk 8.2 → **WOULD_BUY** (SOLID with risk score 8.2 <= max 40)
    - take: AERO (Aerodrome) trades at $0.7044 on aerodrome with $7.24M in liquidity. On the positive side: Deep liquidity ($7,238,305) — the book can a
    - settlement tx: [`0x794b1ebef352d3e4e21177ff9abbdd55f41492cd5ca5a09da19b69f3878a212d`](https://basescan.org/tx/0x794b1ebef352d3e4e21177ff9abbdd55f41492cd5ca5a09da19b69f3878a212d)
- **Settled pre-flight:**
  - https://token-verdict-production.up.railway.app/v1/verdict: Settled knows this endpoint, status live, quality 85/100, delivery VERIFIED by a Settled test purchase, latest receipt had nothing to compare (no usable sample in Settled's listing) — proceeding on verified delivery
- **Services vetted:**
  - https://token-verdict-production.up.railway.app/v1/verdict: verdict **TRUSTED**, trust 95 → **ADOPT** (TRUSTED with trust score 95 >= min 80)
    - settlement tx: [`0x8a272f666ac2908d66e37940962eabba2974b0e441844ff2afe277bcd2e914fd`](https://basescan.org/tx/0x8a272f666ac2908d66e37940962eabba2974b0e441844ff2afe277bcd2e914fd)
- **Calls:** 3 planned, 0 errors.
- **Spent:** $0.09 this run ($0.09 today of $0.10 cap) · **Cumulative logged spend: $0.365000**

<details><summary>Full run output</summary>

```text
=== verdict-loop pass @ 2026-10-28T11:57:05Z — mode: LIVE ===
payer: 0xa4f183a6799F0310FcCC545B07F2DcC960223de2 | daily cap: $0.10 | already spent today: $0.00
balance guard: payer holds $3.623438 USDC on Base; planned spend $0.09
[token] Wrapped Ether (Base) (WETH): verdict SOLID risk 16.4 -> WOULD_BUY (SOLID with risk score 16.4 <= max 40)
        take: WETH (Wrapped Ether) trades at $2359.33 on uniswap with $522.6k in liquidity. On the positive side: Deep liquidity ($522,634) — the book can
        settlement tx: 0xda2bfba53d644340cecd3946e04de0e8194a7c34c5b47549829ec32fa0a28eaf
[token] Aerodrome AERO (Base) (AERO): verdict SOLID risk 8.2 -> WOULD_BUY (SOLID with risk score 8.2 <= max 40)
        take: AERO (Aerodrome) trades at $0.7044 on aerodrome with $7.24M in liquidity. On the positive side: Deep liquidity ($7,238,305) — the book can a
        settlement tx: 0x794b1ebef352d3e4e21177ff9abbdd55f41492cd5ca5a09da19b69f3878a212d
[settled] https://token-verdict-production.up.railway.app/v1/verdict: Settled knows this endpoint, status live, quality 85/100, delivery VERIFIED by a Settled test purchase, latest receipt had nothing to compare (no usable sample in Settled's listing) — proceeding on verified delivery
[service] https://token-verdict-production.up.railway.app/v1/verdict: verdict TRUSTED trust 95 -> ADOPT (TRUSTED with trust score 95 >= min 80)
        corroborated by Settled: its scout's test purchase of this endpoint delivered as advertised — the adoption stands on RouteVerdict's rule alone; Settled only confirms it
        settlement tx: 0x8a272f666ac2908d66e37940962eabba2974b0e441844ff2afe277bcd2e914fd
--- summary ---
calls planned: 3 | errors: 0
spent this pass: $0.09 | spent today: $0.09 of $0.10 cap
```

</details>

<!-- entry spent_usd=0.090000 cumulative_usd=0.365000 -->
## 2026-10-29 — live run

- **Balance guard:** payer held $23.961438 USDC; planned spend $0.09.
- **Tokens screened:**
  - Wrapped Ether (Base) (WETH): verdict **SOLID**, risk 16.4 → **WOULD_BUY** (SOLID with risk score 16.4 <= max 40)
    - take: WETH (Wrapped Ether) trades at $2322.91 on pancakeswap with $4.40M in liquidity. On the positive side: Deep liquidity ($4,399,796) — the boo
    - settlement tx: [`0x9f07697ebaf11c249c96f95b1b5ee9155515c981ceff00b30e83978c59b3e993`](https://basescan.org/tx/0x9f07697ebaf11c249c96f95b1b5ee9155515c981ceff00b30e83978c59b3e993)
  - Aerodrome AERO (Base) (AERO): verdict **SOLID**, risk 12.7 → **WOULD_BUY** (SOLID with risk score 12.7 <= max 40)
    - take: AERO (Aerodrome) trades at $0.682 on aerodrome with $6.61M in liquidity. On the positive side: Deep liquidity ($6,611,654) — the book can ab
    - settlement tx: [`0x8da5929761138695d75b7ca6d73eafb4708da5d1383b8d2897480c26179b26e4`](https://basescan.org/tx/0x8da5929761138695d75b7ca6d73eafb4708da5d1383b8d2897480c26179b26e4)
- **Settled pre-flight:**
  - https://token-verdict-production.up.railway.app/v1/verdict: Settled knows this endpoint, status live, quality 85/100, delivery VERIFIED by a Settled test purchase, latest receipt had nothing to compare (no usable sample in Settled's listing) — proceeding on verified delivery
- **Services vetted:**
  - https://token-verdict-production.up.railway.app/v1/verdict: verdict **TRUSTED**, trust 95 → **ADOPT** (TRUSTED with trust score 95 >= min 80)
    - settlement tx: [`0xeae715459e0e4b935350e6d1e6f1f7337fd8bb3d1379f8d90b8a14b6c3a774e0`](https://basescan.org/tx/0xeae715459e0e4b935350e6d1e6f1f7337fd8bb3d1379f8d90b8a14b6c3a774e0)
- **Calls:** 3 planned, 0 errors.
- **Spent:** $0.10 this run ($0.10 today of $0.10 cap) · **Cumulative logged spend: $0.460000**

<details><summary>Full run output</summary>

```text
=== verdict-loop pass @ 2026-10-29T11:57:20Z — mode: LIVE ===
payer: 0xa4f183a6799F0310FcCC545B07F2DcC960223de2 | daily cap: $0.10 | already spent today: $0.00
balance guard: payer holds $23.961438 USDC on Base; planned spend $0.09
[token] Wrapped Ether (Base) (WETH): verdict SOLID risk 16.4 -> WOULD_BUY (SOLID with risk score 16.4 <= max 40)
        take: WETH (Wrapped Ether) trades at $2322.91 on pancakeswap with $4.40M in liquidity. On the positive side: Deep liquidity ($4,399,796) — the boo
        settlement tx: 0x9f07697ebaf11c249c96f95b1b5ee9155515c981ceff00b30e83978c59b3e993
        guard: guard warn (settled pass, drift warn, route_verdict skipped, pre_trade skipped, caps skipped); checks cost $0.005
[token] Aerodrome AERO (Base) (AERO): verdict SOLID risk 12.7 -> WOULD_BUY (SOLID with risk score 12.7 <= max 40)
        take: AERO (Aerodrome) trades at $0.682 on aerodrome with $6.61M in liquidity. On the positive side: Deep liquidity ($6,611,654) — the book can ab
        settlement tx: 0x8da5929761138695d75b7ca6d73eafb4708da5d1383b8d2897480c26179b26e4
[settled] https://token-verdict-production.up.railway.app/v1/verdict: Settled knows this endpoint, status live, quality 85/100, delivery VERIFIED by a Settled test purchase, latest receipt had nothing to compare (no usable sample in Settled's listing) — proceeding on verified delivery
[service] https://token-verdict-production.up.railway.app/v1/verdict: verdict TRUSTED trust 95 -> ADOPT (TRUSTED with trust score 95 >= min 80)
        corroborated by Settled: its scout's test purchase of this endpoint delivered as advertised — the adoption stands on RouteVerdict's rule alone; Settled only confirms it
        settlement tx: 0xeae715459e0e4b935350e6d1e6f1f7337fd8bb3d1379f8d90b8a14b6c3a774e0
--- summary ---
calls planned: 3 | errors: 0
spent this pass: $0.095 | spent today: $0.095 of $0.10 cap
```

</details>

<!-- entry spent_usd=0.095000 cumulative_usd=0.460000 -->
