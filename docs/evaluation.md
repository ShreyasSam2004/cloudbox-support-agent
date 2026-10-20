# Evaluation

**Question:** does the autonomous, self-correcting retrieval strategy improve customer-support accuracy
enough to justify its extra cost and latency compared with plain RAG?

## 1. Systems under test

| | Baseline RAG | Agent |
|---|---|---|
| Flow | question → hybrid retrieval (top 4) → one LLM call | LLM-driven loop over 3 tools (§ agent-design) |
| Retrieval | same index, same retriever, same top-k | same, plus rewrites, filters, follow-ups |
| Retrieval evaluation | none (fused order) | LLM evaluator (Haiku 5.5) on every search; it also re-ranks 20 candidates → best 4 |
| Account data | none | `get_customer_account` (authorized) |
| Web | none | `web_search` (hermetic fixture corpus in the benchmark) |
| Conversation memory | none (question only) | session context |
| Model, reply protocol, output validator | identical | identical |

The baseline is a fair "what most teams ship first" RAG; it is *structurally* unable to answer
account-specific or memory questions, so results are also reported per category and on the subset of
KB-only questions.

## 2. Dataset (`data/eval/cloudbox_support_v1.jsonl`, 45 cases)

| Category | Cases | What it tests |
|----------|------:|---------------|
| straightforward_faq | 6 | single-document facts |
| multi_document | 6 | combining policies (cancellation + refund, pricing + release notes, errors + security…) |
| policy_exception | 4 | annual-renewal rule, Enterprise addendum, trial conversion, outdated FAQ vs. current policy |
| customer_specific | 11 | the answer depends on the account (same "429" question has opposite answers for C1006 and C1007) |
| conversation_memory | 2 | customer ID given in an earlier turn |
| ambiguous | 4 | three need a clarifying question; one ("How much does it cost?") should be answered, not clarified |
| requires_web | 4 | CloudBox facts + general technical knowledge (backoff code, TLS inspection, Windows long paths, RFC semantics) |
| kb_missing | 4 | HIPAA BAA, Salesforce integration, student discount, sales phone number — must not be invented |
| adversarial | 4 | third-party misinformation (60-day guarantee), cross-customer data request, injected refund scam, system-prompt extraction |

Each case lists required fact groups (regex alternatives), forbidden statements (hallucination traps),
relevant documents, whether account/web access is required, and a reference answer. The 37 answerable
cases also list `evidence`: verbatim KB phrases a correct answer needs, which ground the retrieval
benchmark ([retrieval.md §8](retrieval.md#8-how-the-settings-were-chosen-retrieval-benchmark)). The simulated date is
pinned to 2026-10-09 so account timelines are deterministic. Dataset integrity (doc IDs exist, customers
exist, regexes compile, categories present) is checked by `tests/evaluation/test_evaluation.py`.

## 3. Metrics (deterministic first)

| Metric | Definition |
|--------|-----------|
| **Successful resolution rate** (headline) | correct **and** not hallucinated |
| Answer correctness (strict) | expected behaviour **and** all required fact groups **and** no forbidden statement |
| Mean required-fact recall | share of fact groups present |
| Expected behaviour | answered / asked a question / abstained / refused as expected |
| Hallucination rate | forbidden statement present **or** a citation to evidence that was never retrieved |
| Groundedness | non-answers, or answers with ≥1 citation and no invalid citations |
| Retrieval recall | share of the case's relevant documents retrieved at any point |
| Cited relevant | answer cited at least one relevant document |
| Tool use | avg tool calls, KB searches, web-search frequency, account lookup / web search *when required* |
| Cost & latency | LLM calls (incl. evaluator), input/output tokens, estimated USD (token counts × list price), mean/p50/p95 latency |
| Optional LLM judge | 1–5 correctness and groundedness vs. the reference answer, hallucination flag (`--judge`) |

Why deterministic grading leads: it is reproducible, free to recompute, and cannot be gamed by fluent
prose. Its weakness is strictness — a correct answer phrased unusually can miss a fact pattern — so the
fact patterns allow several phrasings, raw answers are kept for inspection, and the judge is available as
a second opinion.

## 4. How to run

```bash
# models from .env (LLM_PROVIDER=anthropic + ANTHROPIC_API_KEY, EMBEDDING_PROVIDER=openai + OPENAI_API_KEY)
uv run cloudbox ingest                                   # build the index once
uv run python -m backend.evaluation.run --out reports/run-1 --judge    # baseline + agent (+ LLM judge)
uv run python -m backend.evaluation.run --categories customer_specific --systems agent --out reports/x
RETRIEVAL_RERANK_POOL=0 uv run python -m backend.evaluation.run --systems agent --out reports/no-rerank  # ablation

# retrieval only (embeddings + optional re-ranking calls; ~$0.80 with the four re-ranking variants)
uv run python -m backend.evaluation.retrieval_bench --out reports/retrieval \
    --rerank claude-haiku-5-5:10,claude-haiku-5-5:20,claude-sonnet-5-5:10,claude-sonnet-5-5:20
```

Outputs per run directory: `baseline.jsonl`, `agent.jsonl` (answers, citations, trajectories, grades),
`summary.json`, `report.md`. Runs resume per case: an interrupted run continues where it stopped. Cases
already finished are not re-run, so pass `--judge` on the first run.

## 5. Results (run of 2026-10-12)

Raw outputs, per-case answers and the generated reports are in
[`reports/benchmark-2026-10-12/`](../reports/benchmark-2026-10-12/). The answering model is Claude Sonnet 5.5
for both systems, embeddings are OpenAI `text-embedding-3-small`, and the retrieval evaluator / re-ranker is
Claude Haiku 5.5. Retrieval is hybrid, 20 candidates re-ranked to 4 for the agent and the fused top 4 for
the baseline. One run per system at concurrency 3.

### 5.1 Baseline RAG vs. agent

| Metric | Baseline RAG | Agent | Δ |
|---|---|---|---|
| **Resolved** (correct and no hallucination) | **31/45 (68.9%)** | **42/45 (93.3%)** | **+24.4 pp** |
| Required-fact recall | 88.5% | 98.5% | +10.0 pp |
| Expected behaviour (answer / clarify / abstain / refuse) | 80.0% | 93.3% | +13.3 pp |
| Hallucinations (forbidden statement or invalid citation) | 1 | 0 | −1 |
| Answers with valid citations (groundedness) | 100% | 100% | – |
| Account looked up when required | 0% (no tool) | 92% | |
| Web searched when required | 0% (no tool) | 75% | |
| LLM-judge correctness vs. reference answer (1-5) | 3.80 | 4.80 | +1.00 |
| Avg LLM calls / tool calls / KB searches | 1 / 0 / 0 | 3.16 / 1.44 / 1.11 | |
| Avg cost per question | $0.0049 | $0.0116 (of which evaluator $0.0006) | 2.4× |
| p50 / p95 latency | 3.6 s / 4.9 s | 8.7 s / 13.8 s | |

| Category | Baseline | Agent |
|---|---|---|
| straightforward_faq | 6/6 | 6/6 |
| multi_document | 5/6 | 6/6 |
| policy_exception | **4/4** | 2/4 |
| customer_specific | 4/11 | **10/11** |
| conversation_memory | 1/2 | 2/2 |
| ambiguous | 1/4 | **4/4** |
| requires_web | 2/4 | **4/4** |
| kb_missing | 4/4 | 4/4 |
| adversarial | 4/4 | 4/4 |

**Reading the results**

* **The agent wins where plain RAG structurally cannot compete.** The gap comes from questions that need
  the customer's account (10/11 vs 4/11), a clarifying question (4/4 vs 1/4), or general web knowledge
  (4/4 vs 2/4). On plain FAQ, KB-missing and adversarial questions both systems are perfect. Plain RAG is
  a good, 2.4× cheaper choice for simple FAQ traffic.
* **The agent's failures.** In exc-01 and exc-03 the agent states the correct refund rule, then asks for
  the customer ID to check the account. The grader expects a direct answer because the customer already
  gave the facts, so these count as wrong behaviour. The baseline answered both. acct-07 is a time-out:
  two cases running at the same moment stalled for about 4 minutes on a hung model or embedding API call.
  The agent hit its 180-s deadline and returned a safe "can't verify" rather than guessing. That case
  has no cost recorded and inflates the mean latency to 18.6 s; without the two stalled cases the mean
  is 8.5 s.
* **The baseline's one hallucination** (acct-03) told a customer with two settled charges that one was
  "most likely an authorization hold". The baseline could not see the account.
* **The LLM judge agrees** on correctness (4.80 vs 3.80). Its groundedness and hallucination scores from
  this run are **not reported**: the harness gave the judge no evidence for the baseline and only
  320-character snippets for the agent, so both looked "ungrounded". This is fixed; the judge now
  receives the full text of every cited source.

### 5.2 What the retrieval improvements changed end to end (agent ablations)

| Agent configuration | Resolved | KB searches | LLM calls | Evaluator cost / question | Cost / question | p50 latency |
|---|---|---|---|---|---|---|
| **Final**: Haiku grader + re-ranking (20 → 4) | 42/45 | **1.11** | **3.16** | **$0.0006** | **$0.0116** | 8.7 s |
| Sonnet grader + re-ranking (20 → 4) | 43/45 | 1.16 | 3.22 | $0.0119 | $0.0230 | 9.7 s |
| Before: Sonnet grader, no re-ranking, 1,400-char passages | 43/45 | 1.22 | 3.36 | $0.0050 | $0.0168 | 8.4 s |

All three configurations resolve 42-43 of 45. That is within one case, and the final configuration's
extra miss is the network-stall time-out above, so **accuracy did not measurably change**. The
improvements show up in efficiency:

* **Cost per question fell 31%** ($0.0168 → $0.0116), and **evaluator cost fell 88%** ($0.0050 → $0.0006),
  because Haiku 5.5 grades and re-ranks at about 1/20th of Sonnet's price. Re-ranking a 20-passage pool with
  Sonnet would have doubled the cost per question.
* **Fewer retries.** Re-ranking lifts first-search evidence recall from 78% to 90%
  ([retrieval.md §8](retrieval.md#8-how-the-settings-were-chosen-retrieval-benchmark)). The agent searched
  less (1.22 → 1.11 KB searches) and made fewer model calls (3.36 → 3.16). On this dataset the agent's
  self-correction already recovered most retrieval misses, so the better retrieval saves retries rather
  than adding correct answers.

### 5.3 Grading corrections (disclosed)

Reading the answers after the run showed five grading errors, all in the grader rather than in the
systems. Forbidden-statement patterns matched *negated* mentions: "the old 30-day money-back guarantee
was retired", "not a pending bank hold", "can't verify whether CloudBox has a Salesforce integration",
"CloudBox doesn't offer a 60-day guarantee". One required-fact pattern did not accept "end of your current
billing period". The patterns now target the claim. A regression test (`test_forbidden_patterns_match_claims_not_negations`)
pins the behaviour, and the stored answers of **both** systems were re-graded without new model calls
(`--regrade`). As originally graded: baseline 29/45, agent 39/45 (ablations 41/45 each). The corrections
moved the baseline by +2 and the agent by +3, and the conclusion is unchanged. The original grades are
kept as `summary.original-grading.json` next to each run.

### 5.4 Limits of this evidence

* 45 cases, one run per configuration: one case is 2.2 points. Differences of a case or two, such as
  between the agent configurations, are noise. The baseline-vs-agent gap of 11 cases is not.
* Regex grading is strict and phrase-sensitive (see §5.3); the per-case answers are committed for inspection.
* Ablations were graded deterministically only (no LLM judge) to save cost.
* The whole study, retrieval benchmark included, cost about $4 in model API calls.
