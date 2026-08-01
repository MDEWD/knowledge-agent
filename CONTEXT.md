# Knowledge Agent Deep Research

This context defines the language used by the long-running, evidence-grounded research workflow.

## Language

**Research Run**:
A durable execution of one research question, identified by a stable run ID.
_Avoid_: request, job, task

**Research State**:
The versioned, serializable state required to resume a Research Run without repeating completed work.
_Avoid_: context blob, metadata

**Evidence**:
A normalized source record retrieved during research and available for claim grounding.
_Avoid_: search result, snippet, note

**Claim**:
A report assertion that must be supported by one or more Evidence records.
_Avoid_: sentence, opinion

**Citation**:
The explicit relationship from a Claim to an Evidence record.
_Avoid_: link, reference

**Critique**:
A lifecycle-tracked, evidence-based challenge raised against a draft Claim or coverage gap.
_Avoid_: feedback, comment

**Research Policy**:
The rules that govern search routing, budgets, stopping, cancellation, and quality gates for a Research Run.
_Avoid_: configuration, prompt rules

## Relationships

- A **Research Run** owns exactly one current **Research State** and a history of checkpoints.
- A **Research State** contains zero or more **Evidence**, **Claim**, and **Critique** records.
- A **Claim** has zero or more **Citations**, each pointing to one **Evidence** record.
- A **Critique** remains open until a later **Research State** resolves or rejects it with evidence.
- A **Research Policy** decides whether a **Research Run** continues, stops, or is cancelled.

## Example dialogue

> **Dev:** "Can the Research Run finish because the score is high?"
> **Domain expert:** "Only if the Research Policy also sees adequate Citation coverage and no open high-severity Critique."

## Flagged ambiguities

- "source" previously meant both a search result and a rendered link; use **Evidence** for the durable research record and **Citation** for its use in a report.
- "resume" previously accepted a run ID but restarted most work; it now means restoring the persisted **Research State** at the next graph node.
