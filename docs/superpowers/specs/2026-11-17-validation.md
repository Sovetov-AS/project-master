# Validation evidence

Synthetic fixtures only; no owner project memory was published.

- Core regression suite: `python3 -m unittest discover -s tests -q` — 109 tests, PASS, one optional real-model test skipped without opt-in.
- Real local embeddings: FastEmbed 0.7.4 installed in an isolated virtualenv, multilingual MiniLM model downloaded explicitly to a separate local cache. 384 dimensions; related Russian payment sentences cosine 0.6434 versus -0.0744 for unrelated button-color sentence. These are fixture observations, not retrieval-quality benchmarks.
- Offline integration: `PM_EMBEDDING_TEST=1 PM_EMBEDDING_CACHE=/path/to/cache HF_HUB_OFFLINE=1 python -m unittest discover -s tests -p test_memory.py -q` — PASS with real semantic index/search, Russian paraphrase ranking and unchanged-source reuse. No project text is sent to a remote inference API.
- Compile scripts/tests, strict interaction-map validation and basic BPMN validation — PASS. Semantic BPMN lint explicitly skipped by the established command.
- Context reduction regression compares compact context against the same full synthetic corpus and preserves goal/next action. No billing or generalized percentage claim.

Limitations: semantic retrieval requires the separately installed pinned local runtime and model cache. Source registration and semantic correctness of summaries/links require agent review. Budget counts are estimates. Checkpoint is event-driven and cannot guarantee recording work immediately before a crash. Freshness is scoped to registered sources plus Git tracked diff and untracked file fingerprints. Explicit compact recovery preserves the original default recovery API. Current source documents and regression checks remain required before edits.
