# CloudBox Support Benchmark — Baseline RAG vs. Agentic RAG

Generated 2026-10-12 06:49 UTC. All numbers below were produced by running both systems on the same dataset; nothing is estimated except cost (token counts × list price).

## Run configuration

- **dataset**: data/eval/cloudbox_support_v1.jsonl (45 cases)
- **agent / baseline model**: anthropic:claude-sonnet-5-5
- **retrieval evaluator model**: anthropic:claude-haiku-5-5
- **embeddings**: openai:text-embedding-3-small
- **retrieval**: hybrid, top_k=4, re-rank pool=20, chunk_max_chars=1600, store=memory
- **agent limits**: max_steps=8, max_tool_calls=12
- **web search**: hermetic fixture corpus (data/web_fixtures)
- **judge**: anthropic:claude-sonnet-5-5
- **simulated date**: 2026-10-09
- **finished**: 2026-10-12T06:42:56+00:00
- **judge note**: Only judge *correctness* (vs. the reference answer) is valid in this run. Judge groundedness and hallucination are not: the harness gave the judge no evidence for the baseline and 320-character snippets for the agent (fixed after this run; the judge now receives the full text of every cited source).
- **grading note**: Regraded after the run with corrected patterns (forbidden patterns now match claims, not negated mentions; one required-fact pattern widened). Same answers, no model calls; original grades in summary.original-grading.json.
- **regraded**: 2026-10-12T06:49:56+00:00

## Headline metrics

| Metric | Baseline | Agent | Δ (agent − baseline) |
|---|---|---|---|
| Successful resolution rate | 68.9% | 93.3% | +24.4 pp |
| Answer correctness (strict) | 68.9% | 93.3% | +24.4 pp |
| Mean required-fact recall | 88.5% | 98.5% | +10.0 pp |
| Expected behaviour (answer / clarify / abstain / refuse) | 80.0% | 93.3% | +13.3 pp |
| Hallucination rate (lower is better) | 2.2% | 0.0% | -2.2 pp |
| Groundedness (answers with valid citations) | 100.0% | 100.0% | +0.0 pp |
| Answers without any citation (count) | 0 | 0 | +0.00 |
| Retrieval recall of relevant documents | 90.2% | 90.2% | +0.0 pp |
| Cited a relevant document (when citing KB) | 89.7% | 100.0% | +10.3 pp |
| Account looked up when required | 0.0% | 92.3% | +92.3 pp |
| Web searched when required | 0.0% | 75.0% | +75.0 pp |
| Web-search frequency (all cases) | 0.0% | 6.7% | +6.7 pp |
| Avg tool calls | 0.00 | 1.44 | +1.44 |
| Avg knowledge-base searches | 0.00 | 1.11 | +1.11 |
| Avg LLM calls (incl. evaluator) | 1.00 | 3.16 | +2.16 |
| Avg input tokens | 897 | 13,832 | +12935.09 |
| Avg output tokens | 315 | 930 | +615.62 |
| Avg latency (s) | 3.6 | 18.6 | +15.0 |
| p50 latency (s) | 3.6 | 8.7 | +5.1 |
| p95 latency (s) | 4.9 | 13.8 | +8.9 |
| Avg estimated cost per question (USD) | $0.0049 | $0.0116 | +0.0067 |
| Avg retrieval-evaluator calls | 0.00 | 1.13 | +1.13 |
| Avg retrieval-evaluator cost per question (USD, incl. above) | $0.0000 | $0.0006 | +0.0006 |
| Total estimated cost (USD) | $0.2224 | $0.5007 | +0.2783 |
| Cases with unknown cost (excluded above) | 0 | 2 | +2.00 |
| Step/time-limit hits | 0 | 2 | +2.00 |
| Errors | 0 | 0 | +0.00 |
| LLM-judge: cases graded | 45 | 45 | +0.00 |
| LLM-judge correctness (1-5) | 3.80 | 4.80 | +1.00 |
| LLM-judge groundedness (1-5) | 1.16 | 3.53 | +2.38 |
| LLM-judge hallucination rate | 95.6% | 60.0% | -35.6 pp |

Counts — **baseline**: resolved 31/45, correct 31/45, hallucinated 1/45.
Counts — **agent**: resolved 42/45, correct 42/45, hallucinated 0/45.

## By category (resolved / cases)

| Category | Baseline | Agent |
|---|---|---|
| adversarial | 4/4 | 4/4 |
| ambiguous | 1/4 | 4/4 |
| conversation_memory | 1/2 | 2/2 |
| customer_specific | 4/11 | 10/11 |
| kb_missing | 4/4 | 4/4 |
| multi_document | 5/6 | 6/6 |
| policy_exception | 4/4 | 2/4 |
| requires_web | 2/4 | 4/4 |
| straightforward_faq | 6/6 | 6/6 |

## Agent trajectories

Distinct action sequences chosen by the model (the code does not prescribe them):

| Trajectory | Cases |
|---|---|
| search_knowledge_base → answer | 13 |
| get_customer_account → search_knowledge_base → answer | 10 |
| search_knowledge_base → search_knowledge_base → answer | 6 |
| clarification | 4 |
| get_customer_account → search_knowledge_base → search_knowledge_base → answer | 2 |
| cannot_verify | 2 |
| search_knowledge_base → web_search → answer | 2 |
| search_knowledge_base → search_knowledge_base → cannot_verify | 2 |
| search_knowledge_base → clarification | 1 |
| search_knowledge_base → search_knowledge_base → clarification | 1 |
| web_search → search_knowledge_base → answer | 1 |
| search_knowledge_base → cannot_verify | 1 |

## Per-case results

| Case | Category | Baseline | Agent |
|---|---|---|---|
| faq-01 | straightforward_faq | ✅ answer, facts 100%, 3.4s | ✅ answer, facts 100%, 7.4s |
| faq-02 | straightforward_faq | ✅ answer, facts 100%, 3.5s | ✅ answer, facts 100%, 8.1s |
| faq-03 | straightforward_faq | ✅ answer, facts 100%, 3.4s | ✅ answer, facts 100%, 7.6s |
| faq-04 | straightforward_faq | ✅ answer, facts 100%, 1.7s | ✅ answer, facts 100%, 5.9s |
| faq-05 | straightforward_faq | ✅ answer, facts 100%, 2.3s | ✅ answer, facts 100%, 6.4s |
| faq-06 | straightforward_faq | ✅ answer, facts 100%, 2.7s | ✅ answer, facts 100%, 6.1s |
| multi-01 | multi_document | ✅ answer, facts 100%, 3.6s | ✅ answer, facts 100%, 8.6s |
| multi-02 | multi_document | ✅ answer, facts 100%, 3.4s | ✅ answer, facts 100%, 7.8s |
| multi-03 | multi_document | ✅ answer, facts 100%, 2.7s | ✅ answer, facts 100%, 7.8s |
| multi-04 | multi_document | ✅ answer, facts 100%, 3.7s | ✅ answer, facts 100%, 13.8s |
| multi-05 | multi_document | ✅ answer, facts 100%, 4.7s | ✅ answer, facts 100%, 10.4s |
| multi-06 | multi_document | ❌ cannot_verify, facts 0%, 4.1s | ✅ answer, facts 100%, 8.6s |
| exc-01 | policy_exception | ✅ answer, facts 100%, 4.3s | ❌ clarification, facts 100%, 7.2s |
| exc-02 | policy_exception | ✅ answer, facts 100%, 3.6s | ✅ answer, facts 100%, 8.7s |
| exc-03 | policy_exception | ✅ answer, facts 100%, 3.5s | ❌ clarification, facts 100%, 8.1s |
| exc-04 | policy_exception | ✅ answer, facts 100%, 2.9s | ✅ answer, facts 100%, 8.9s |
| acct-01 | customer_specific | ❌ answer, facts 67%, 3.8s | ✅ answer, facts 100%, 11.7s |
| acct-02 | customer_specific | ❌ clarification, facts 50%, 4.0s | ✅ answer, facts 100%, 8.7s |
| acct-03 | customer_specific | ⚠️ halluc. answer, facts 100%, 4.5s | ✅ answer, facts 100%, 9.7s |
| acct-04 | customer_specific | ❌ clarification, facts 100%, 4.0s | ✅ answer, facts 100%, 13.4s |
| acct-05 | customer_specific | ❌ clarification, facts 67%, 3.6s | ✅ answer, facts 100%, 9.6s |
| acct-06 | customer_specific | ✅ answer, facts 100%, 4.0s | ✅ answer, facts 100%, 239.5s |
| acct-07 | customer_specific | ✅ answer, facts 100%, 3.6s | ❌ cannot_verify, facts 33%, 232.4s |
| acct-08 | customer_specific | ❌ answer, facts 0%, 5.0s | ✅ answer, facts 100%, 11.9s |
| acct-09 | customer_specific | ❌ clarification, facts 100%, 3.8s | ✅ answer, facts 100%, 9.8s |
| acct-10 | customer_specific | ✅ answer, facts 100%, 3.0s | ✅ answer, facts 100%, 9.5s |
| acct-11 | customer_specific | ✅ answer, facts 100%, 2.7s | ✅ answer, facts 100%, 8.9s |
| mem-01 | conversation_memory | ❌ answer, facts 50%, 3.9s | ✅ answer, facts 100%, 9.6s |
| mem-02 | conversation_memory | ✅ answer, facts 100%, 4.0s | ✅ answer, facts 100%, 8.7s |
| amb-01 | ambiguous | ❌ answer, facts 100%, 4.8s | ✅ clarification, facts 100%, 2.1s |
| amb-02 | ambiguous | ✅ clarification, facts 100%, 3.2s | ✅ clarification, facts 100%, 1.9s |
| amb-03 | ambiguous | ❌ answer, facts 100%, 3.9s | ✅ clarification, facts 100%, 2.0s |
| amb-04 | ambiguous | ❌ cannot_verify, facts 0%, 3.0s | ✅ answer, facts 100%, 8.1s |
| web-01 | requires_web | ✅ answer, facts 100%, 5.5s | ✅ answer, facts 100%, 10.8s |
| web-02 | requires_web | ✅ answer, facts 100%, 3.3s | ✅ answer, facts 100%, 8.0s |
| web-03 | requires_web | ❌ answer, facts 50%, 3.5s | ✅ answer, facts 100%, 10.2s |
| web-04 | requires_web | ❌ cannot_verify, facts 100%, 2.6s | ✅ answer, facts 100%, 8.6s |
| nokb-01 | kb_missing | ✅ cannot_verify, facts 100%, 2.3s | ✅ cannot_verify, facts 100%, 12.9s |
| nokb-02 | kb_missing | ✅ cannot_verify, facts 100%, 2.7s | ✅ cannot_verify, facts 100%, 11.3s |
| nokb-03 | kb_missing | ✅ answer, facts 100%, 2.5s | ✅ answer, facts 100%, 7.4s |
| nokb-04 | kb_missing | ✅ cannot_verify, facts 100%, 4.2s | ✅ cannot_verify, facts 100%, 7.2s |
| adv-01 | adversarial | ✅ answer, facts 100%, 2.7s | ✅ answer, facts 100%, 9.3s |
| adv-02 | adversarial | ✅ cannot_verify, facts 100%, 3.2s | ✅ cannot_verify, facts 100%, 4.8s |
| adv-03 | adversarial | ✅ answer, facts 100%, 4.8s | ✅ answer, facts 100%, 10.5s |
| adv-04 | adversarial | ✅ cannot_verify, facts 100%, 4.9s | ✅ clarification, facts 100%, 7.1s |

Raw per-case outputs (answers, citations, trajectories, grades) are in the `*.jsonl` files next to this report.
