# Trowel for Salesforce — 8-Week Roadmap (5–8 hrs/week)

**Rule of thumb each week:** ~60% building, ~25% learning the *why* (readings below), ~15% writing down what you learned (these notes become your LinkedIn posts and interview answers for free).

Every week ends with a **shippable increment** — commit it, even if rough. Eight commits > one perfect launch.

---

## Week 1 — Dig site setup & metadata fundamentals (5–6 h)
**Build:** Free Developer Edition org + `sf` CLI auth. Run `scripts/seed_dig_site.py` ideas manually for now: create 2 dead Flows, a trigger + record-triggered Flow that both update the same Lead field, 5 unused custom fields. Retrieve everything with `sf project retrieve start`. Open the XML. Read it.
**Learn (the why):** Metadata API vs Tooling API — what each can and can't see (FRAMEWORK §2). Why read-only posture is a product feature.
**Ship:** repo initialized, org connected, raw metadata committed to `/dig-site-sample`.
**Checkpoint question you should be able to answer:** *"Why can't this tool be a managed package inside the org?"*

## Week 2 — First LLM contact: explain one Flow (6–8 h)
**Build:** `archaeologist/summarize.py` — feed one Flow's XML to Claude, get back a structured JSON summary (purpose, objects touched, fields written, trigger conditions). Use a JSON schema / tool-use forced output, not "please respond in JSON."
**Learn:** Prompt engineering with structured output — why schema-forced output beats prose parsing (determinism, testability). Temperature and why 0 for analysis. Token costs: measure what one Flow costs; extrapolate to an org.
**Ship:** CLI command that explains any Flow in the org.
**Checkpoint:** *"Why structured output instead of asking for markdown?"*

## Week 3 — Catalog & dependency graph (6–8 h)
**Build:** Parser walks all retrieved XML → SQLite tables (artifacts, fields, references). Build the networkx graph: nodes = artifacts/fields, edges = references. First deterministic detector: dead automation (zero inbound refs).
**Learn:** Why a graph and not just SQL joins (transitive dependencies: "what breaks if I delete this field?" is a graph traversal). Why deterministic detection before any LLM involvement (FRAMEWORK §7).
**Ship:** `excavate` + `catalog` commands; graph queryable; first real finding printed.
**Checkpoint:** *"Why doesn't the LLM discover findings?"*

## Week 4 — Embeddings & hybrid retrieval (6–8 h)
**Build:** Embed artifact summaries (from week 2's summarizer, batched) into a vector table. Build the hybrid retriever: graph for exact refs, embeddings for semantic. CLI Q&A: `ask "what happens when a Lead converts?"`.
**Learn:** Embedding model choice (small local model vs API — cost/quality/privacy trade). Why hybrid beats pure RAG on structured data (FRAMEWORK §4) — write this one up properly; it's your best interview material.
**Ship:** working Q&A over the org.
**Checkpoint:** *"When would pure vector RAG give a wrong answer here that hybrid gets right?"*

## Week 5 — Evals (the week that separates you from every demo-builder) (6–8 h)
**Build:** `evals/golden/` — 30 hand-verified Q→A pairs about your dig site. Tier 1 pytest: deterministic findings must match exactly. Tier 2: LLM-as-judge with a written rubric scoring narrative answers 1–5. GitHub Action running it all on PR.
**Learn:** Why evals mid-project, not last; why facts get deterministic checks and prose gets a judge; judge calibration (spot-check 10 judgments by hand, record agreement rate).
**Ship:** failing-able CI. Deliberately break a prompt and watch the eval catch it — screenshot that; it's a LinkedIn post.
**Checkpoint:** *"Isn't LLM-as-judge circular?"* (Know the two-tier answer cold.)

## Week 6 — The agent loop (7–8 h)
**Build:** Hand-rolled tool-use loop: Claude + four tools (`query_catalog`, `traverse_graph`, `semantic_search`, `read_artifact`). Agent answers open questions by choosing tools itself. Add remaining detectors: conflicting automation, permission sprawl, naming drift.
**Learn:** Agent loop anatomy — stop conditions, tool-result truncation, max-turns guards, what happens when the model calls a tool wrong. Why hand-rolled before LangGraph (FRAMEWORK §5).
**Ship:** `investigate` command — agent autonomously researches and reports on any question, passing week-5 evals.
**Checkpoint:** *"What failure modes did you hit in the loop, and what guards did you add?"* (Keep a log — real answers beat rehearsed ones.)

## Week 7 — Assessment report (6–8 h)
**Build:** Findings engine → Well-Architected pillar scores → HTML report (Jinja2 template): executive summary, scored pillars, prioritized findings, remediation sequence with effort estimates. This is where your TPM/BA identity shows.
**Learn:** Why rules-generate/LLM-narrates for the report; how consultancies structure org health assessments (skim a public example); what makes a finding *actionable* vs merely true.
**Ship:** `assess` command producing `reports/org-assessment.html`. Print it. It should look like something a VP would read.
**Checkpoint:** *"Who is the audience for each report section?"*

## Week 8 — Launch (5–7 h)
**Build:** `scripts/seed_dig_site.py` for reproducibility. Polish README (architecture diagram ✅, demo GIF, eval badge). Record 3-min Loom: problem → live run → report. Add case-study page to your portfolio site. Pin the repo.
**Publish:** LinkedIn post 1: "I pointed an AI agent at a 5-year-old Salesforce org. Here's what it found." Post 2 (a week later): the hybrid-retrieval why-not-pure-RAG writeup. Post 3: the evals story.
**Checkpoint:** A stranger can clone, seed, run, and get a report in <15 minutes.

---

## After week 8 — enhancement backlog
Work FRAMEWORK.md's ranked list top-down: **MCP server → Agentforce Readiness Mode → Time Machine → multi-agent/LangGraph → pgvector**. Each is 1–3 weeks at your pace, and each is its own LinkedIn post.

## Weekly hygiene (every single week)
- Commit with real messages; the git history is part of the portfolio
- Log costs (tokens/$) — "I know what this costs to run" is rare and senior
- Write 5 bullet points of what you learned → `docs/learning-log.md`
- If you slip a week, cut scope, not the eval gate

## Certification pairing (parallel track, ~1 h/week from the same hours)
Weeks 1–4: **Salesforce AI Specialist** study (overlaps heavily with what you're building). Weeks 5–8: **Agentforce Specialist**. Sitting both by end of month 3 while the repo goes public is the one-two punch.
