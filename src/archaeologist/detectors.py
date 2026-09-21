"""Week 3: deterministic detectors.

Why the LLM doesn't discover findings (FRAMEWORK §7)
-----------------------------------------------------
"This Flow has no inbound references" is a fact with a correct answer. Given the
metadata, two people who disagree about it can settle the disagreement by
counting. Anything with a checkable answer should be checked, not generated —
a model asked to find dead automation will sometimes miss a live caller and
sometimes invent one, and neither failure announces itself.

So detectors are ordinary code with ordinary unit tests, and the model's job
starts afterwards: explaining what a finding means for this org, judging which
of forty findings matter, writing the remediation order. Those are genuinely
judgement calls, they have no ground truth to check against, and they are where
a model actually beats a rule.

The dividing line is the eval strategy too (FRAMEWORK §6): facts get exact
assertions, prose gets a rubric and a judge. If a detector's output needed a
judge, the detector would be doing the wrong job.
"""

from __future__ import annotations

import networkx as nx

from .models import Artifact, Edge, Finding, Kind
from .graph import inbound

# A Flow with this processType is invocable only by name — from another Flow,
# from Apex, or from a REST call. That makes "nobody names it" a meaningful
# question to ask about it, and about nothing else.
_AUTOLAUNCHED = "autolaunchedflow"


def _is_record_triggered(artifact: Artifact) -> bool:
    """Record-triggered Flows also carry processType AutoLaunchedFlow.

    The platform invokes them from a record event, so no artifact ever names
    them and their inbound count is always zero. Counting references on one
    would flag every correctly-working record-triggered Flow in the org — the
    single most common way a dead-code detector destroys its own credibility.

    The distinguishing mark is ``<start><triggerType>``, not the processType.
    """
    return bool(artifact.attrs.get("trigger_type"))


def dead_automation(artifacts: list[Artifact], graph: nx.MultiDiGraph) -> list[Finding]:
    """TRW001 — an Active autolaunched Flow that nothing invokes.

    Eligibility is narrow on purpose. Excluded:
      - non-Active Flows: a Draft is not debt, it's a draft
      - record-triggered Flows: invoked by the platform (see above)
      - screen Flows: invoked from a Lightning page, Quick Action, or URL —
        none of which are in the retrieved metadata scope, so absence of an
        inbound edge proves nothing
      - scheduled Flows: invoked by the scheduler

    Known limitation, stated rather than hidden: a Flow invoked only from a
    Process Builder, a platform event subscription, or an external REST client
    will be reported. That is the honest boundary of what retrieved metadata
    can see, and it belongs in the report next to the finding.
    """
    findings: list[Finding] = []
    for artifact in artifacts:
        if artifact.kind is not Kind.FLOW:
            continue
        if (artifact.status or "").lower() != "active":
            continue
        if (artifact.subtype or "").lower() != _AUTOLAUNCHED:
            continue
        if _is_record_triggered(artifact):
            continue
        if artifact.attrs.get("schedule"):
            continue

        callers = inbound(graph, artifact.id, edge=Edge.INVOKES.value)
        if callers:
            continue

        findings.append(Finding(
            rule="TRW001",
            severity="medium",
            artifact_id=artifact.id,
            message=f"Active autolaunched Flow '{artifact.name}' is never invoked.",
            why=(
                "Active-but-unreachable automation is the tech debt nobody dares "
                "delete, because nobody can prove it's dead. It still consumes org "
                "limits at deploy time and still has to be reasoned about during "
                "every future change. Confirm no Process Builder or external caller "
                "names it, then deactivate."
            ),
        ))
    return findings


def unreferenced_custom_field(artifacts: list[Artifact],
                              graph: nx.MultiDiGraph) -> list[Finding]:
    """TRW002 — a custom field nothing in the retrieved metadata reads or writes.

    Severity is 'info', and that is a deliberate downgrade. Retrieved metadata
    does not include reports, list view filters, dashboards, page layouts, or
    external integrations, and a field used only by those is alive while looking
    dead here. Reporting it as a confirmed problem would be wrong.

    So it is reported as a *candidate for review* — a shortlist an admin can
    check in an afternoon, rather than a verdict. Widening the retrieval scope
    to layouts and reports is what promotes this to a real finding later.
    """
    findings: list[Finding] = []
    for artifact in artifacts:
        if artifact.kind is not Kind.FIELD:
            continue
        if not artifact.attrs.get("custom"):
            continue
        if artifact.attrs.get("synthesised"):
            # Referenced but never retrieved — by definition something uses it.
            continue
        if inbound(graph, artifact.id):
            continue

        findings.append(Finding(
            rule="TRW002",
            severity="info",
            artifact_id=artifact.id,
            message=f"Custom field '{artifact.name}' has no reader or writer in scope.",
            why=(
                "Candidate for review, not a confirmed orphan: reports, list views, "
                "page layouts and integrations are outside the retrieved metadata "
                "and any of them could be the consumer. Worth an admin's afternoon "
                "before it becomes a field nobody remembers the purpose of."
            ),
        ))
    return findings


DETECTORS = [dead_automation, unreferenced_custom_field]


def run_all(artifacts: list[Artifact], graph: nx.MultiDiGraph) -> list[Finding]:
    findings: list[Finding] = []
    for detector in DETECTORS:
        findings.extend(detector(artifacts, graph))
    order = {"high": 0, "medium": 1, "info": 2}
    return sorted(findings, key=lambda f: (order.get(f.severity, 9), f.rule, f.artifact_id))
