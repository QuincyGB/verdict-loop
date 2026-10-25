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
