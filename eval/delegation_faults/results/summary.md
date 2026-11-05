## By condition

| fault | strategy | n | correct | answered | restarted | injected/run | redelegated | tokens | Δtok vs no-rec | tok vs no-rec | seconds | sec vs no-rec | wasted tok | verifier tok | flagged | verif err |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| clean | baseline | 10 | 10/10 | 10/10 | 0 | 0.0 | 0 | 55880 | - | - | 25.7 | - | 0 | 0 | 0 | 0 |
| connection_drop | baseline | 10 | 10/10 | 10/10 | 0 | 1.4 | 10 | 67204 | - | - | 32.2 | - | 0 | 0 | 0 | 0 |
| connection_drop | full-restart | 10 | 10/10 | 10/10 | 10 | 1.5 | 0 | 81032 | +13829 | x1.21 | 25.8 | x0.80 | 21332 | 0 | 0 | 0 |
| connection_drop | always-verify | 10 | 10/10 | 10/10 | 0 | 1.5 | 10 | 126352 | +59148 | x1.88 | 42.6 | x1.32 | 0 | 52744 | 0 | 0 |
| result_timeout | baseline | 10 | 10/10 | 10/10 | 0 | 1.4 | 10 | 83888 | - | - | 198.9 | - | 20085 | 0 | 0 | 0 |
| result_timeout | full-restart | 10 | 9/10 | 9/10 | 10 | 1.4 | 0 | 90490 | +6602 | x1.08 | 215.2 | x1.08 | 42146 | 0 | 0 | 0 |
| result_timeout | always-verify | 10 | 10/10 | 10/10 | 0 | 1.5 | 10 | 188642 | +104755 | x2.25 | 209.7 | x1.05 | 33833 | 78126 | 15 | 1 |

## By question

| question | clean | drop | drop+R | drop+V | timeout | timeout+R | timeout+V |
|---|---|---|---|---|---|---|---|
| 27 | ✓ 43.2k 20s | ✓ 81.6k 44s (inj1,re) | ✓ 80.5k 31s (inj1,R) | ✓ 118.9k 43s (inj1,re) | ✓ 93.1k 220s (inj1,re) | ✓ 87.1k 212s (inj1,R) | ✓ 184.9k 210s (inj1,re,flag1) |
| 32 | ✓ 67.5k 38s | ✓ 60.8k 58s (inj2,re) | ✓ 92.2k 24s (inj2,R) | ✓ 116.6k 33s (inj2,re) | ✓ 85.8k 203s (inj2,re) | ✓ 110.4k 236s (inj2,R) | ✓ 169.5k 203s (inj2,re,flag2) |
| 89 | ✓ 51.6k 26s | ✓ 62.3k 33s (inj1,re) | ✓ 66.4k 29s (inj2,R) | ✓ 91.9k 34s (inj1,re) | ✓ 59.5k 204s (inj1,re) | ∅ 45.9k 314s (inj1,R) | ✓ 120.4k 201s (inj1,re,flag1) |
| 94 | ✓ 57.8k 33s | ✓ 102.3k 37s (inj1,re) | ✓ 132.9k 32s (inj1,R) | ✓ 128.1k 41s (inj1,re) | ✓ 97.6k 194s (inj1,re) | ✓ 50.6k 198s (inj1,R) | ✓ 189.0k 211s (inj1,re,flag1) |
| 95 | ✓ 48.9k 27s | ✓ 55.2k 22s (inj1,re) | ✓ 67.7k 27s (inj1,R) | ✓ 117.4k 33s (inj1,re) | ✓ 64.1k 193s (inj1,re) | ✓ 68.4k 195s (inj1,R) | ✓ 208.0k 205s (inj1,re,flag1) |
| 104 | ✓ 47.7k 13s | ✓ 47.8k 28s (inj1,re) | ✓ 54.5k 20s (inj1,R) | ✓ 177.1k 51s (inj1,re) | ✓ 84.1k 194s (inj1,re) | ✓ 78.9k 190s (inj1,R) | ✓ 175.4k 207s (inj1,re,flag1) |
| 114 | ✓ 28.3k 16s | ✓ 43.9k 19s (inj1,re) | ✓ 42.4k 14s (inj1,R) | ✓ 84.6k 28s (inj1,re) | ✓ 75.5k 195s (inj1,re) | ✓ 74.6k 195s (inj1,R) | ✓ 127.3k 212s (inj1,re,flag1) |
| 224 | ✓ 42.9k 19s | ✓ 60.5k 19s (inj2,re) | ✓ 57.2k 18s (inj2,R) | ✓ 199.5k 40s (inj3,re) | ✓ 72.0k 191s (inj2,re) | ✓ 97.1k 204s (inj2,R) | ✓ 238.3k 210s (inj3,re,flag3) |
| 251 | ✓ 54.9k 19s | ✓ 56.5k 21s (inj2,re) | ✓ 70.5k 22s (inj2,R) | ✓ 103.9k 36s (inj2,re) | ✓ 75.9k 194s (inj2,re) | ✓ 104.6k 198s (inj2,R) | ✓ 163.9k 213s (inj2,re,flag2) |
| 271 | ✓ 116.0k 46s | ✓ 101.1k 40s (inj2,re) | ✓ 146.1k 42s (inj2,R) | ✓ 125.5k 88s (inj2,re) | ✓ 131.3k 202s (inj2,re) | ✓ 187.3k 209s (inj2,R) | ✓ 309.8k 224s (inj2,re,flag2) |

Deltas and ratios: each recovery run vs the same fault's no-recovery run (strategy baseline) on the same question; clean rows are context only. Ratios are summed over the paired questions. 'wasted tok' is the discarded first attempt for full-restart, otherwise the tokens spent by Workers whose results were withheld (result_timeout). 'flagged' counts verifications with verified=false; 'verif err' counts verifier calls that failed.

Per-question cells: ✓ correct, ✗ wrong, ∅ no answer, ? ungraded; then total tokens and seconds. inj = faults injected, R = restarted, re = Lead re-delegated after the fault, flag = verifier flags. +R = full-restart, +V = always-verify.
