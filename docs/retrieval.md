# Retrieval Pipeline

```text
data/knowledge_base/*.md ──► parse (front matter + heading tree) ──► structure-aware chunks
      ──► embed (OpenAI / Ollama / …) ──► PostgreSQL: pgvector HNSW + tsvector GIN
query ──► embed ──► dense top-20 ─┐
      └──► lexical top-20 ────────┴──► Reciprocal Rank Fusion ──► 20 candidates
      ──► evaluator (one LLM call: score every candidate 0-3 + grade the search) ──► best 4 + verdict ──► agent
```

Every number on this page that says *measured* comes from the retrieval benchmark
(`uv run python -m backend.evaluation.retrieval_bench`, report in
[`reports/retrieval/report.md`](../reports/retrieval/report.md)); see §8.

## 1. The corpus is deliberately hard

20 CloudBox documents (policies, pricing, API reference, troubleshooting, security, legal, release
notes, runbook, FAQ, community posts) with:

* **Tables** — plan comparison (16 rows × 6 columns with footnotes), error codes, rate limits, SLA credits.
* **Nested sections and cross-references** — e.g. Cancellation §4 → Refund §3.2 → Billing §5.
* **Exceptions spread across documents** — the Enterprise Addendum overrides Refund/Cancellation for
  Enterprise; trial conversions have their own 48-hour rule; annual renewals have a 7-day *and*
  no-usage condition with a numeric usage threshold.
* **Conflicts** — the FAQ (2025) still advertises a 30-day money-back guarantee and Business-only SSO;
  Refund Policy v3 (2026) and the 2026 release notes supersede both.
* **Near-duplicates that differ in the detail that matters** — two kinds of HTTP 429 with opposite fixes.
* **Distractors** — a long Terms of Service that mentions refunds/fees without answering anything.
* **Adversarial content** — a community post with a prompt injection; a web page with hidden HTML instructions.

## 2. Parsing (`backend/retrieval/parsing.py`)

YAML front matter → document metadata (`doc_id, title, doc_type, authority, effective_date, version,
audience, url, plans, supersedes`). ATX headings → a section tree with GitHub-style anchors. Tables,
fenced code, lists and paragraphs become typed blocks. Markdown links to other KB files become
cross-references (`refund-policy#32-charges-after-cancellation`).

## 3. Structure-aware chunking (`backend/retrieval/chunking.py`)

| Rule | Why |
|------|-----|
| Chunks never cross a section boundary; each carries its breadcrumb ("Refund Policy > 3. Monthly plans > 3.2 Charges after cancellation") | Retrieval and the model both need to know *which* rule a passage is |
| The document intro is its own chunk | It often carries scope/supersession ("the 30-day guarantee was retired") |
| A short section intro is carried into each child's first chunk as context | An exception should never be retrieved without the rule it modifies |
| Tables and code blocks are atomic; oversized tables are split by rows with the header repeated | A row without its header is meaningless |
| Tables are additionally *linearized* into the indexed text ("Plan: Pro; Rate limit: 1,000 requests / min; …") | Both lexical and dense search can match a single cell |
| FAQ documents → one chunk per Q/A | FAQs are independent facts |
| Cross-references and authority metadata are stored with every chunk | The agent can follow references and weigh authority |

Result on this corpus (measured): 162 chunks; median 229 characters, p90 490, max 1,555 (the plan
comparison table, kept whole); every table chunk starts with its header and separator rows.

**Chunk size.** The size limit (`CHUNK_MAX_CHARS`, default 1,600) barely matters here: sections are
short, so 800 / 1,600 / 2,400 produce 164 / 162 / 160 chunks and the same retrieval quality (±1 evidence
phrase). Section structure, not a character count, decides the chunks. Against naive fixed-size windows,
structure-aware chunks win when the context budget is equal (§8). Passages are shown to the agent and the
evaluator up to `OBSERVATION_CHUNK_CHARS=2000`, so no chunk is truncated (the old 1,400 cut two chunks,
with no measured effect on this dataset).

## 4. Index and search

* **Dense**: `vector(d)` with an HNSW index (cosine). The embedding model + dimension used to build the
  index are recorded in `kb_index_meta`; serving refuses a mismatched model (a common silent regression).
* **Lexical**: generated `tsvector` column with GIN index, queried with an **OR** query built from the
  same tokenizer as the in-process BM25 (compound tokens like `cbx-4291`, `rate_limit_exceeded` are kept
  whole *and* split). AND-semantics full-text search misses most natural-language support questions.
* **Fusion**: Reciprocal Rank Fusion (`k=60`) over the top-20 of each; the UI/observation shows the dense
  cosine similarity as `semantic_similarity`. The keyword ranking's weight is configurable
  (`RETRIEVAL_LEXICAL_WEIGHT`, default 1.0). Down-weighting it helps only the top 3 results. Equal weights
  give the best top-20 candidate pool, which is what the re-ranker needs (measured, §8).
* **Re-ranking**: see §6. The fused top-20 is a high-recall *candidate pool*; the evaluator picks the best 4.
* **Filters**: `document_id` and `document_type` — exposed to the agent for targeted follow-up searches.
* `InMemoryVectorStore` implements the same contract (NumPy exact search + BM25) for tests and offline
  runs; an integration test checks parity with pgvector.

## 5. Ingestion (`backend/retrieval/ingestion.py`, `cloudbox ingest`)

Idempotent: content hash = SHA-256(file, chunker version, chunk size limit, embedding model). Unchanged documents are
skipped, changed ones are re-chunked and re-embedded in a transaction, deleted ones are removed. In Azure
it runs as a Container Apps Job after each deployment; the KB sources are versioned with the code
(docs-as-code: policy changes are reviewed in pull requests and released with the app).

## 6. The evaluator: re-ranking and grading in one call

Hybrid search finds the right *area* reliably but not always the decisive *clause*: the passage that
answers the question is in the fused top 20 for 90% of the evidence, but in the top 4 for only 78%
(measured). The evaluator closes that gap without an extra model call. It already has to read the
passages to grade the search, so it reads all 20 candidates and, in the same JSON response:

1. **scores each candidate** 0-3 (3 = states the needed fact, 2 = needed context such as the rule an
   exception modifies, 1 = same topic, 0 = unrelated). The tool keeps the 4 best (ties keep fused order,
   0s are dropped) and only those become citable `K#` evidence; and
2. **grades the search**: `relevant`, `coverage`, `missing_information`, `reason`, which the agent
   uses to decide its next action.

Candidates are labelled `cand-1 … cand-20` for the evaluator (not `P1`, because the support policy has
"P1 incidents"). The tool maps the labels to evidence IDs before the agent sees the verdict. If the
evaluator is disabled or fails, the tool falls back to the fused order. The code is in
`backend/retrieval/rerank.py` and `backend/tools/knowledge_base.py`.

The evaluator runs on **Claude Haiku 5.5** (`EVALUATOR_MODEL`), measured against Sonnet 5.5 on the same
candidates:

| Re-ranking (pool 20 → top 4) | recall@4 | all evidence in top 4 | MRR | cost / search | p50 latency |
|---|---|---|---|---|---|
| none (fused order) | 78% | 76% | 0.67 | – | – |
| Haiku 5.5 | **90%** | **92%** | 0.84 | **$0.0006** | 2.9 s |
| Sonnet 5.5 | 88% | 89% | 0.84 | $0.0119 | 4.1 s |

Haiku re-ranks as well as Sonnet at about 1/20th of the cost. As a grader it is stricter: when every
labelled KB phrase was in the pool, Haiku said `relevant` 85% of the time, Sonnet 97%. Haiku's
"disagreements" were mostly correct, though. For web-01/03/04 the KB has CloudBox's policy but not what
the customer asked (Python code, Windows steps, the HTTP-standard date format), so `partial` is the
right verdict, and it is what sends the agent to web search. End to end
([evaluation.md §5.2](evaluation.md#52-what-the-retrieval-improvements-changed-end-to-end-agent-ablations)),
the agent with the Haiku grader resolved 42/45 against 43/45 with Sonnet. That is within noise, and the
one difference was a network time-out. It did so at half the cost per question ($0.0116 vs $0.0230).

Typical failure modes the evaluator surfaces to the agent:

* "Can I get a refund?" retrieves the FAQ's outdated guarantee or generic billing text → `relevant=false,
  missing: refund eligibility rules for this plan/charge`.
* A customer-specific question retrieves the right policy but the answer depends on timestamps →
  `coverage=partial, missing: the customer's cancellation and charge times` → the agent looks up the account.
* A how-to question about Windows long paths retrieves CloudBox's 260-character note but not how to change
  the OS setting → `missing: how to enable long paths in Windows` → the agent uses the web, labelled external.

## 7. Embedding choices

| Environment | Embeddings | Notes |
|-------------|-----------|-------|
| Azure (dev/staging/prod) and local | OpenAI `text-embedding-3-small` (1536-d) | API key from Key Vault in Azure, from `.env` locally |
| Fully offline | Ollama `nomic-embed-text` (768-d) with task prefixes | 45 s to embed the corpus on a laptop CPU |
| Unit tests | Deterministic hashing embedder | No semantics — tests exercise the lexical half and plumbing |

## 8. How the settings were chosen (retrieval benchmark)

`backend/evaluation/retrieval_bench.py` scores retrieval without any LLM in the loop, except for the
re-ranking runs.

* **Labels.** 37 answerable benchmark questions carry `evidence`: 49 short verbatim phrases from the KB
  that a correct answer needs (e.g. *"issued to the original payment method within 5-10 business days"*).
  A phrase counts as found when it appears inside a returned passage, as the agent would see it. Because
  labels are text rather than chunk IDs, any chunking strategy can be scored with the same labels. A unit
  test fails if a document edit breaks a label.
* **Query.** The customer's question verbatim. The agent usually rewrites its query, so this is a
  conservative stand-in for its first search.
* **Cost.** Embeddings are cached in `.data/`; a full run with four re-ranking variants costs about $0.80.

Measured with OpenAI `text-embedding-3-small`, hybrid first stage:

| Chunking | Chunks | Median chars | recall@4 | recall @ 1.5k chars | recall @ 3k chars | recall @ 6k chars |
|---|---|---|---|---|---|---|
| **structure-aware, 1,600 max** (default) | 162 | 229 | 78% | **78%** | 82% | **90%** |
| structure-aware, 800 / 2,400 max | 164 / 160 | 231 / 227 | 80% / 80% | 78% / 80% | 86% / 82% | 90% / 90% |
| structure-aware, no parent context | 163 | 224 | 78% | 78% | 82% | 90% |
| fixed windows 400 (20% overlap) | 164 | 395 | 67% | 65% | 82% | 90% |
| fixed windows 800 | 82 | 794 | 82% | 55% | 82% | 88% |
| fixed windows 1,600 | 44 | 1,590 | 84% | 67% | 71% | 84% |

Large fixed windows look better at "top 4" only because 4 of them are 2-4× more text (5,651 vs 1,257
characters). At an equal character budget, structure-aware chunks match or beat every window size. Parent
context does not change phrase recall. It exists for answer quality: an exception is never shown without
its rule.

| First stage (default chunker) | recall@4 | recall@6 | recall@10 | recall@20 | MRR |
|---|---|---|---|---|---|
| vector only | 82% | 84% | 88% | 88% | 0.72 |
| keyword (BM25) only | 71% | 80% | 80% | 84% | 0.57 |
| **hybrid, keyword weight 1** (default) | 78% | 84% | 86% | **90%** | 0.67 |
| hybrid, keyword weight 0.5 / 0.25 | 80% / 80% | 82% / 82% | 84% / 84% | 88% / 88% | 0.71 / 0.71 |

**Decisions.** Keep structure-aware chunking and the 1,600 limit. Keep hybrid with equal weights, which
gives the best 20-candidate pool. Re-rank 20 candidates (`RETRIEVAL_RERANK_POOL=20`) and return 4
(`RETRIEVAL_TOP_K=4`): after re-ranking, recall@4 equals recall@6 (90%). Without re-ranking (evaluator
disabled), use `RETRIEVAL_TOP_K=6`: 78% → 84% for about 600 more characters.

**Caveat.** 49 phrases means one phrase ≈ 2 percentage points. Treat differences of 2-4 points as noise;
the re-ranking gain (+12 points recall@4, +16 points complete@4) and the equal-budget chunking result are
well beyond that.
