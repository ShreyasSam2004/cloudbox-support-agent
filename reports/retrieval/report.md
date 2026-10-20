# Retrieval benchmark

Generated 2026-10-12 06:28 UTC. Embeddings: `openai:text-embedding-3-small`. 37 answerable questions with 49 labelled evidence phrases, plus 3 questions the knowledge base cannot answer (used only for the evaluator verdict check). Query = the customer's question verbatim. A phrase is *found* when it appears inside a returned passage as the agent sees it.

**recall@k**: share of evidence phrases in the top k passages. **complete@k**: questions whose evidence was *all* in the top k. **MRR**: mean 1/rank of the first passage containing evidence. **chars@k**: characters of context handed to the model. **recall @ N chars**: recall when each strategy may hand over at most N characters (fair comparison across chunk sizes).

## Chunking strategies (first stage: hybrid (keyword weight 1))

| Strategy | Chunks | Median chars | Phrases intact | recall@4 | recall@8 | complete@4 | MRR | chars@4 | recall @ 1.5k chars | recall @ 3k chars | recall @ 6k chars | Note |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| structured-1600 | 162 | 229 | 100% | 78% | 84% | 76% | 0.67 | 1,257 | 78% | 82% | 90% | current chunker (default) |
| structured-800 | 164 | 231 | 100% | 80% | 86% | 78% | 0.66 | 1,255 | 78% | 86% | 90% |  |
| structured-2400 | 160 | 227 | 100% | 80% | 84% | 78% | 0.68 | 1,321 | 80% | 82% | 90% |  |
| structured-1600-no-context | 163 | 224 | 100% | 78% | 84% | 76% | 0.67 | 1,234 | 78% | 82% | 90% | no parent-intro context |
| structured-1600-view-1400 | 162 | 229 | 100% | 78% | 84% | 76% | 0.67 | 1,253 | 78% | 84% | 90% | old 1,400-char passage cut |
| fixed-400 | 164 | 395 | 100% | 67% | 82% | 68% | 0.68 | 1,536 | 65% | 82% | 90% | naive windows, 20% overlap |
| fixed-800 | 82 | 794 | 100% | 82% | 90% | 81% | 0.77 | 3,047 | 55% | 82% | 88% | naive windows, 20% overlap |
| fixed-1600 | 44 | 1590 | 100% | 84% | 88% | 84% | 0.83 | 5,651 | 67% | 71% | 84% | naive windows, 20% overlap |

## Search mode and fusion weight (default chunker)

| First stage | recall@3 | recall@4 | recall@6 | recall@10 | recall@20 | complete@6 | MRR |
|---|---|---|---|---|---|---|---|
| vector | 76% | 82% | 84% | 88% | 88% | 84% | 0.72 |
| lexical | 61% | 71% | 80% | 80% | 84% | 81% | 0.57 |
| hybrid (keyword weight 1) | 73% | 78% | 84% | 86% | 90% | 84% | 0.67 |
| hybrid (keyword weight 0.5) | 78% | 80% | 82% | 84% | 88% | 81% | 0.71 |
| hybrid (keyword weight 0.25) | 80% | 80% | 82% | 84% | 88% | 81% | 0.71 |

## top-k (default chunker, hybrid (keyword weight 1))

| k | recall@k | complete@k | chars@k |
|---|---|---|---|
| 1 | 43% | 41% | 376 |
| 2 | 65% | 62% | 691 |
| 3 | 73% | 73% | 969 |
| 4 | 78% | 76% | 1,257 |
| 5 | 80% | 78% | 1,576 |
| 6 | 84% | 84% | 1,889 |
| 8 | 84% | 84% | 2,626 |
| 10 | 86% | 86% | 3,235 |
| 15 | 88% | 89% | 4,872 |
| 20 | 90% | 92% | 6,372 |

## LLM re-ranking (default chunker, candidates from hybrid (keyword weight 1))

The evaluator scores every candidate in the pool in the same call that grades the search, and the tool keeps the best k. The verdict columns check the evaluator's `relevant` flag against the labels: *full* = all evidence was in the pool, *none* = none was (includes the unanswerable questions).

| Re-ranking | recall@3 | recall@4 | recall@6 | complete@4 | complete@6 | MRR | relevant when full | not relevant when none | avg cost / search | p50 latency |
|---|---|---|---|---|---|---|---|---|---|---|
| none (hybrid (keyword weight 1) order) | 73% | 78% | 84% | 76% | 84% | 0.67 | – | – | $0 | – |
| claude-haiku-5-5, pool 10 | 84% | 86% | 86% | 86% | 86% | 0.83 | 81% of 32 | 100% of 6 | $0.0004 | 2.7s |
| claude-haiku-5-5, pool 20 | 88% | 90% | 90% | 92% | 92% | 0.84 | 85% of 34 | 80% of 5 | $0.0006 | 2.9s |
| claude-sonnet-5-5, pool 10 | 86% | 86% | 86% | 86% | 86% | 0.85 | 97% of 32 | 83% of 6 | $0.0072 | 3.2s |
| claude-sonnet-5-5, pool 20 | 86% | 88% | 90% | 89% | 92% | 0.84 | 97% of 34 | 80% of 5 | $0.0119 | 4.1s |

## Misses (default chunker, hybrid (keyword weight 1), top 4, no re-ranking)

Evidence phrases not in the top 4 for the verbatim question:

- **multi-01**: “takes effect at the end of the current billing period”
- **multi-02**: “sso (saml 2.0) pro $4 / user / month”
- **multi-04**: “after 5 consecutive failed sign-in attempts”
- **multi-06**: “compensation for downtime is provided as service credits”; “credits are not refunds, have no cash value”
- **acct-02**: “a hold appears on your bank statement as pending and is not a charge”
- **acct-05**: “you sent more requests per minute than your plan allows”
- **acct-08**: “no prorated refunds”; “at least 60 days before the end of the current term”
- **amb-04**: “price, monthly billing $0 $15 / month $49 / month”
- **adv-01**: “no longer applies to any purchase or renewal”

