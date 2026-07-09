# Trowel for Salesforce — Framework & Architecture Decisions

Every major choice below is written as: **the decision → why → why NOT the alternative**. This is the document you'll speak from in interviews — knowing *why not* is what separates architects from implementers.

---

## 1. Language: Python

**Why:** The entire eval/embedding/agent ecosystem (Anthropic SDK, sentence-transformers, networkx, pytest) is Python-first. You already know it. Data-wrangling metadata XML is painless.

**Why not Apex?** LLM orchestration can't live inside the org: callout limits, governor limits, no long-running processes, no access to eval tooling. The org is the *subject*, not the runtime. (Interview line: "I deliberately kept the analysis plane outside the control plane.")

**Why not Node/TypeScript?** Perfectly viable — but Python's eval and data-science tooling is deeper, and switching costs you learning hours with zero portfolio payoff.

## 2. Metadata acquisition: Salesforce CLI (`sf`) + Tooling API

**Why:** `sf project retrieve start` gives you the full metadata tree as versioned XML — official, scriptable, and identical to what CI/CD pipelines use (ties to your Infosys CI/CD story). The Tooling API adds runtime facts the Metadata API lacks: ApexCodeCoverage, FlowInterview failures, field usage.

**Why not screen-scrape Setup or use a managed package?** Scraping is brittle and unprofessional; a managed package requires install permissions in the target org — a security non-starter for an *assessment* tool that should be read-only. Read-only posture is a feature: "my tool cannot break your org" is the first question every buyer asks.

**Why not the REST describe endpoints alone?** They describe *schema*, not *automation logic*. You need the actual Flow XML and Apex bodies to analyze behavior.

## 3. Catalog store: SQLite first, pgvector later

**Why SQLite:** Zero infrastructure, ships inside the repo, trivially inspectable (`sqlite3 org.db`), perfect for a portfolio demo someone can clone and run. Fundamentals before infrastructure.

**Why not Pinecone/Weaviate on day 1?** Managed vector DBs are the right call at production scale (freshness, dedup, reranking across millions of docs) — but a single org is ~10³–10⁴ artifacts. Reaching for managed infra here signals résumé-driven development, not judgment. The ROADMAP has you graduating to **pgvector** in the stretch phase so you can speak to both. (This "when do you actually need a vector DB" answer is a top-tier interview differentiator in 2026.)

## 4. Retrieval: hybrid (graph + embeddings), not pure RAG

**The decision:** two retrieval paths, merged:
- **Dependency graph (networkx):** exact references — Flow → field, Apex → object, permission set → field. Deterministic, auditable.
- **Embeddings:** semantic questions — "anything that touches billing?" where naming is inconsistent.

**Why not pure vector RAG?** Metadata is *structured*. "Which Flows write to `Lead.Status`?" has one correct answer; vector similarity returns "probably these" — unacceptable for an assessment someone acts on. Pure RAG on structured data is the #1 mistake in enterprise AI right now, and being able to articulate this is worth more than the code.

**Why not graph-only?** Semantics matter too: naming drift ("Cust_Acct__c" vs "ClientAccount__c") and plain-English questions need embeddings. Hybrid = deterministic where possible, probabilistic where necessary.

## 5. Agent: hand-rolled tool-use loop first, framework later

**The decision:** Phase 1–6 uses a plain Claude tool-use loop (~80 lines): model receives tools (`query_catalog`, `traverse_graph`, `semantic_search`, `read_artifact`), loops until done.

**Why:** You cannot debug, eval, or explain what you didn't build. Frameworks (LangGraph, Agent SDK) abstract the loop; abstractions hide failure modes exactly where assessments need audit trails. Learning the raw loop first means every framework you touch later is legible.

**Why not LangGraph on day 1?** For a single-agent, linear-ish workflow it adds a dependency and a DSL without adding capability. Adopt it (stretch phase) when you go **multi-agent** — scanner/analyst/reporter handoffs — where graph-structured state genuinely earns its complexity. "I added the framework when the problem demanded it" is the architect answer.

**Why Claude tool use and not fine-tuning?** Fine-tuning bakes knowledge into weights — wrong tool for facts that change per-org and per-week. Tool use + retrieval keeps the model stateless and the facts fresh.

## 6. Evals: golden dataset + two-tier checks, before more features

**The decision (Week 5, deliberately mid-project, not last):**
- **Golden dataset:** ~30 hand-verified Q→A pairs about your seeded demo org ("Flow X is dead", "trigger Y and Flow Z both update field F")
- **Tier 1 — deterministic:** structural findings (dead automation, conflicts) checked by exact match. No LLM judges facts a graph query can verify.
- **Tier 2 — LLM-as-judge:** narrative quality (is the explanation accurate, complete, actionable?) scored by a second model against a rubric.
- Run via pytest; wired into GitHub Actions so every PR regression-tests the agent.

**Why:** Non-deterministic systems regress silently. Without evals, every prompt tweak is a gamble. Eval infrastructure is the scarcest skill cluster in 2026 hiring — this section of the repo is arguably worth more than the agent itself.

**Why not eval at the very end?** Then evals grade the system instead of shaping it. Mid-project placement means weeks 6–8 develop *against* the eval gate — which is how production teams actually work.

**Why LLM-as-judge at all (isn't it circular)?** For facts, yes — that's why Tier 1 is deterministic. For prose quality, human review doesn't scale and exact match is meaningless; a judge with a written rubric + spot-checked calibration is the industry-standard compromise. Know both halves of that answer.

## 7. Findings engine: rules first, LLM second

**The decision:** Deterministic detectors produce candidate findings (dead automation = graph node with zero inbound references + zero runtime interviews; conflict = two automations writing one field on one object's same trigger event). The LLM then *explains, prioritizes, and narrates* — it does not *discover*.

**Why:** Hallucinated findings destroy the product's entire premise. LLMs are excellent at synthesis and terrible at exhaustive enumeration; graph queries are the reverse. Assign each its strength.

**Why not let the agent free-range over raw XML?** Context windows can't hold an org; sampling misses things; and "the AI read everything" is unverifiable. Enumerate mechanically, explain intelligently.

## 8. Scoring: Salesforce Well-Architected pillars

**Why:** It's the official framework (Trusted, Easy, Adaptable), it's what consultancies bill against, and mapping findings → pillars turns a list of nitpicks into an executive artifact. This is your BA/TPM skillset made visible in code.

---

# Game-changing enhancements (post-week-8 backlog, ranked)

1. **MCP server** — expose `query_catalog` / `traverse_graph` / `semantic_search` as an MCP server so anyone can talk to their org from Claude Desktop. Turns a CLI tool into a *platform*, and MCP is the interoperability standard of 2026. Highest wow-per-hour.
2. **Agentforce Readiness Mode** — a second report scoring the org's *readiness for AI agents*: data contracts, "minimum viable context" exposure, permission hygiene for agent profiles. Rides the single hottest Salesforce demand signal of 2026; possibly nobody has built this.
3. **Time Machine** — snapshot metadata weekly, diff, and have the agent *narrate the change*: "someone added a 4th automation on Opportunity; conflict risk up." Assessment → monitoring = product-thinking story.
4. **Multi-agent split (LangGraph)** — scanner / analyst / report-writer agents with typed handoffs; the moment the framework becomes justified (see §5).
5. **Eval-gated CI badge** — public GitHub Actions badge showing golden-dataset pass rate on every commit. Quiet, devastating credibility signal.
6. **pgvector graduation** — swap the embedding store, write a short "when SQLite stops being enough" doc. Demonstrates scale judgment both ways.
7. **Remediation cost model** — findings → t-shirt-size effort estimates → sequenced roadmap. Pure TPM flex; makes the report actionable, not just diagnostic.
8. **Seeded "dig site" org** — a script that deliberately creates tech debt in a scratch org (dead Flows, conflicting triggers, permission sprawl) so anyone can reproduce your demo in 10 minutes. Reproducibility is what separates portfolio pieces from screenshots.
