### Finding reproduction — the three rejected instances

| Track file (in the frozen input) | Suggested | Decision | Reason |
|---|---|---|---|
| `Marcelo Zarvos - Score Suite.mp3` | `genre.k-pop` @0.60 `metadata.album` | reject | 3:00 orchestral film-score suite by the film composer; not a K-pop song. No other tag was offered. |
| `Marcelo Zarvos - Score Suite (1).mp3` | `genre.k-pop` @0.60 `metadata.album` | reject | Duplicate instance of the same score suite (standard/deluxe album pair); not a K-pop song. |
| `Marcelo Zarvos,EJAE - Prologue (Hunter’s Mantra).mp3` | `genre.k-pop` @0.60 `metadata.album` | reject | 96 s film-score/chant prologue by the film composer with EJAE; not a K-pop song. |

Reproduce with the committed artifacts: the rejected rows in
`evaluation/artifacts/2026-11-17-post-fix/hand-check.jsonl`, the matching
`metadata.album` evidence lines in `engine-events.jsonl`, and the work-level
table produced by `evaluation/tools/per_work_rollup.py`.
