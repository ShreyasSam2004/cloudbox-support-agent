# CloudBox Support Benchmark — Baseline RAG vs. Agentic RAG

Generated 2026-10-12 06:49 UTC. All numbers below were produced by running both systems on the same dataset; nothing is estimated except cost (token counts × list price).

## Run configuration

- **dataset**: data/eval/cloudbox_support_v1.jsonl (45 cases)
- **agent / baseline model**: anthropic:claude-sonnet-5-5
- **retrieval evaluator model**: anthropic:claude-sonnet-5-5
- **embeddings**: openai:text-embedding-3-small
- **retrieval**: hybrid, top_k=4, re-rank pool=20, chunk_max_chars=1600, store=memory
- **agent limits**: max_steps=8, max_tool_calls=12
- **web search**: hermetic fixture corpus (data/web_fixtures)
- **judge**: not run
- **simulated date**: 2026-10-09
- **finished**: 2026-10-12T06:46:10+00:00
- **regraded**: 2026-10-12T06:49:57+00:00

## Headline metrics

| Metric | Agent |
|---|---|
| Successful resolution rate | 95.6% |
| Answer correctness (strict) | 95.6% |
| Mean required-fact recall | 100.0% |
| Expected behaviour (answer / clarify / abstain / refuse) | 95.6% |
| Hallucination rate (lower is better) | 0.0% |
| Groundedness (answers with valid citations) | 100.0% |
| Answers without any citation (count) | 0 |
| Retrieval recall of relevant documents | 92.3% |
| Cited a relevant document (when citing KB) | 100.0% |
| Account looked up when required | 100.0% |
| Web searched when required | 75.0% |
| Web-search frequency (all cases) | 6.7% |
| Avg tool calls | 1.51 |
| Avg knowledge-base searches | 1.16 |
| Avg LLM calls (incl. evaluator) | 3.22 |
| Avg input tokens | 14,446 |
| Avg output tokens | 942 |
| Avg latency (s) | 9.5 |
| p50 latency (s) | 9.7 |
| p95 latency (s) | 14.8 |
| Avg estimated cost per question (USD) | $0.0230 |
| Avg retrieval-evaluator calls | 1.16 |
| Avg retrieval-evaluator cost per question (USD, incl. above) | $0.0119 |
| Total estimated cost (USD) | $1.0343 |
| Cases with unknown cost (excluded above) | 0 |
| Step/time-limit hits | 0 |
| Errors | 0 |

Counts — **agent**: resolved 43/45, correct 43/45, hallucinated 0/45.

## By category (resolved / cases)

| Category | Agent |
|---|---|
| adversarial | 4/4 |
| ambiguous | 4/4 |
| conversation_memory | 2/2 |
| customer_specific | 11/11 |
| kb_missing | 4/4 |
| multi_document | 6/6 |
| policy_exception | 2/4 |
| requires_web | 4/4 |
| straightforward_faq | 6/6 |

## Agent trajectories

Distinct action sequences chosen by the model (the code does not prescribe them):

| Trajectory | Cases |
|---|---|
| search_knowledge_base → answer | 14 |
| get_customer_account → search_knowledge_base → answer | 12 |
| search_knowledge_base → search_knowledge_base → answer | 5 |
| clarification | 3 |
| search_knowledge_base → search_knowledge_base → clarification | 2 |
| search_knowledge_base → web_search → answer | 2 |
| search_knowledge_base → search_knowledge_base → cannot_verify | 2 |
| get_customer_account → search_knowledge_base → search_knowledge_base → answer | 1 |
| web_search → answer | 1 |
| search_knowledge_base → cannot_verify | 1 |
| search_knowledge_base → search_knowledge_base → search_knowledge_base → answer | 1 |
| cannot_verify | 1 |

## Per-case results

| Case | Category | Agent |
|---|---|---|
| faq-01 | straightforward_faq | ✅ answer, facts 100%, 10.0s |
| faq-02 | straightforward_faq | ✅ answer, facts 100%, 9.3s |
| faq-03 | straightforward_faq | ✅ answer, facts 100%, 9.7s |
| faq-04 | straightforward_faq | ✅ answer, facts 100%, 6.7s |
| faq-05 | straightforward_faq | ✅ answer, facts 100%, 8.4s |
| faq-06 | straightforward_faq | ✅ answer, facts 100%, 7.2s |
| multi-01 | multi_document | ✅ answer, facts 100%, 8.6s |
| multi-02 | multi_document | ✅ answer, facts 100%, 7.9s |
| multi-03 | multi_document | ✅ answer, facts 100%, 7.5s |
| multi-04 | multi_document | ✅ answer, facts 100%, 15.0s |
| multi-05 | multi_document | ✅ answer, facts 100%, 11.2s |
| multi-06 | multi_document | ✅ answer, facts 100%, 8.0s |
| exc-01 | policy_exception | ❌ clarification, facts 100%, 11.4s |
| exc-02 | policy_exception | ✅ answer, facts 100%, 9.2s |
| exc-03 | policy_exception | ❌ clarification, facts 100%, 10.6s |
| exc-04 | policy_exception | ✅ answer, facts 100%, 10.4s |
| acct-01 | customer_specific | ✅ answer, facts 100%, 9.8s |
| acct-02 | customer_specific | ✅ answer, facts 100%, 10.9s |
| acct-03 | customer_specific | ✅ answer, facts 100%, 10.1s |
| acct-04 | customer_specific | ✅ answer, facts 100%, 11.8s |
| acct-05 | customer_specific | ✅ answer, facts 100%, 13.9s |
| acct-06 | customer_specific | ✅ answer, facts 100%, 9.5s |
| acct-07 | customer_specific | ✅ answer, facts 100%, 9.1s |
| acct-08 | customer_specific | ✅ answer, facts 100%, 11.2s |
| acct-09 | customer_specific | ✅ answer, facts 100%, 10.0s |
| acct-10 | customer_specific | ✅ answer, facts 100%, 10.0s |
| acct-11 | customer_specific | ✅ answer, facts 100%, 7.3s |
| mem-01 | conversation_memory | ✅ answer, facts 100%, 15.6s |
| mem-02 | conversation_memory | ✅ answer, facts 100%, 9.4s |
| amb-01 | ambiguous | ✅ clarification, facts 100%, 2.1s |
| amb-02 | ambiguous | ✅ clarification, facts 100%, 2.0s |
| amb-03 | ambiguous | ✅ clarification, facts 100%, 1.8s |
| amb-04 | ambiguous | ✅ answer, facts 100%, 8.4s |
| web-01 | requires_web | ✅ answer, facts 100%, 12.6s |
| web-02 | requires_web | ✅ answer, facts 100%, 8.5s |
| web-03 | requires_web | ✅ answer, facts 100%, 11.8s |
| web-04 | requires_web | ✅ answer, facts 100%, 5.6s |
| nokb-01 | kb_missing | ✅ cannot_verify, facts 100%, 14.8s |
| nokb-02 | kb_missing | ✅ cannot_verify, facts 100%, 12.9s |
| nokb-03 | kb_missing | ✅ answer, facts 100%, 7.3s |
| nokb-04 | kb_missing | ✅ cannot_verify, facts 100%, 8.1s |
| adv-01 | adversarial | ✅ answer, facts 100%, 10.1s |
| adv-02 | adversarial | ✅ answer, facts 100%, 14.1s |
| adv-03 | adversarial | ✅ answer, facts 100%, 12.7s |
| adv-04 | adversarial | ✅ cannot_verify, facts 100%, 6.2s |

Raw per-case outputs (answers, citations, trajectories, grades) are in the `*.jsonl` files next to this report.
