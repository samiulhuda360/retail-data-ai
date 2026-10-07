Model: `gemini-flash-lite-latest`. Cost is estimated from tokens at the list prices in `retail_ai/llm.py`.

| System | Split | Correct | Accuracy | Mean latency | p90 latency | Tokens / question | Model calls (cached) | Cost (USD) |
|---|---|---:|---:|---:|---:|---:|---:|---:|
| baseline | dev | 18/30 | 60% | 3.19 s | 5.14 s | 2,364 | 34 (9) | 0.0115 |
| baseline | holdout | 6/10 | 60% | 3.14 s | 3.94 s | 2,777 | 14 (0) | 0.0043 |
| baseline | all | 24/40 | 60% | 3.18 s | 5.14 s | 2,467 | 48 (9) | 0.0159 |
| semantic_agent | dev | 30/30 | 100% | 3.03 s | 3.99 s | 3,237 | 60 (7) | 0.0109 |
| semantic_agent | holdout | 10/10 | 100% | 2.70 s | 2.91 s | 3,242 | 20 (0) | 0.0036 |
| semantic_agent | all | 40/40 | 100% | 2.95 s | 3.76 s | 3,238 | 80 (7) | 0.0145 |

Questions answered incorrectly:

| ID | Split | System | Expected | Answer | Note |
|---|---|---|---|---|---|
| q01 | dev | baseline | 10284768.3686 | 10303730.855663 |  |
| q02 | dev | baseline | 139973.9030 | 142080.379075 |  |
| q04 | dev | baseline | 116326.8835 | 117621.597454 |  |
| q05 | dev | baseline | 0.4724 | 0.4630 |  |
| q09 | dev | baseline | 77.0476 | 78.4283 |  |
| q13 | dev | baseline | 2.5666 | 0.0000 |  |
| q20 | dev | baseline | 466489.2000 | 0.0000 |  |
| q22 | dev | baseline | 11220.7863 | 12219.870979 |  |
| q23 | dev | baseline | 82.4042 | 75.3251 |  |
| q25 | dev | baseline | store | Web Shop |  |
| q29 | dev | baseline | 0.6424 | 0.6287 |  |
| q30 | dev | baseline | 148.0000 | 153 |  |
| q32 | holdout | baseline | Melbourne | WLG |  |
| q35 | holdout | baseline | 0.8798 | None | query returned NULL |
| q39 | holdout | baseline | 110.9315 | 111.6517 |  |
| q40 | holdout | baseline | 103019.5910 | None | query returned NULL |

Recorded runs: 112 live model calls and 16 answered from the cache (responses recorded by earlier live calls with the same prompt). `retail eval --offline` re-scores every question from the cache without a key.
