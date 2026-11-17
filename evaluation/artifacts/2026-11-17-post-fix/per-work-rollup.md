## Per-work vs per-instance reporting (14 works / 47 instances)

The frozen set is 14 distinct works: 7 works x5 instances, 5 works x2, 2 works x1. Instance-level figures let the seven five-instance works dominate; the work-level rows deduplicate decisions to (work, tag) pairs.

| Level | Units | Suggestions | Checked | Accepted | Rejected | Modified | Precision | Coverage |
|---|---|---|---|---|---|---|---|---|
| instance | 47 tracks | 47 | 47 | 44 | 3 | 0 | 93.6% | 93.6% (44/47) |
| work (dedup) | 14 works | 14 pairs | 14 | 12 | 2 | 0 | 85.7% | 85.7% (12/14) |

- Works fully accepted (no rejected/modified pair): 12/14 (85.7%).
- Per-category at work level: genre 12/14 accepted.

### Era / release-date coverage (explicit)

- Era suggestions: **0** at instance level, **0** at work level.
- Era coverage: **0.0%** of instances, **0.0%** of works.
- On this library that is the correct outcome under the binding operator rule: no local source on any of the 47 tracks carries a year or date. The local-date audit verified 0 embedded date tags (`TDRC`/`TDRL`/`TYER`/`date`/`year`), 0 filename year matches, 0 title year matches and 0 album year matches. A date present locally but not suggested would be the bug; there is none to surface.

### Work-level decisions

| Work | Instances | Tag | Source | Verdict |
|---|---|---|---|---|
| Free | 5 | `genre.k-pop` | metadata.album | accept |
| Golden | 5 | `genre.k-pop` | metadata.album | accept |
| How It’s Done | 5 | `genre.k-pop` | metadata.album | accept |
| Jinu’s Lament | 1 | `genre.k-pop` | metadata.album | accept |
| Prologue (Hunter’s Mantra) | 1 | `genre.k-pop` | metadata.album | reject |
| Score Suite | 2 | `genre.k-pop` | metadata.album | reject |
| Soda Pop | 5 | `genre.k-pop` | metadata.album | accept |
| Strategy | 2 | `genre.k-pop` | metadata.album | accept |
| Takedown | 5 | `genre.k-pop` | metadata.album | accept |
| TAKEDOWN (JEONGYEON, JIHYO, CHAEYOUNG) | 2 | `genre.k-pop` | metadata.album | accept |
| What It Sounds Like | 5 | `genre.k-pop` | metadata.album | accept |
| Your Idol | 5 | `genre.k-pop` | metadata.album | accept |
| 사랑인가 봐 Love, Maybe | 2 | `genre.k-pop` | metadata.album | accept |
| 오솔길 Path | 2 | `genre.k-pop` | metadata.album | accept |
