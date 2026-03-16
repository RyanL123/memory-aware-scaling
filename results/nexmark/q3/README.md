# Nexmark Q3 Results Ledger

This folder stores append-only benchmark records for `q3`.

## Run notes

- `2026-02-24` entry comes from an interrupted multi-query round.
- User explicitly requested to stop after q1/q2/q3 and skip remaining queued work.
- Metrics were collected from Flink REST fallback (Prometheus scrape targets unavailable).
- Sampling interval is 20s with 9 samples (~3 minutes), which is below the 10-minute guideline in `AGENTS.md`.
- `job_id`/autoscaler recommendation fields are marked `not-captured` or `unknown` for this partial round.
