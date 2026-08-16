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

**Memory Observation**:
An immutable, source-linked event that may or may not be selected for long-term retention.
_Avoid_: memory, fact

**Memory Fact**:
A versioned, structured assertion retained because it can improve a future Agent decision.
_Avoid_: raw chat, vector chunk

**Memory Scope**:
The task, Agent, project, or time conditions under which a Memory Fact applies.
_Avoid_: tag, metadata blob

**Memory Conflict**:
Two incompatible Memory Facts whose scopes overlap and therefore require deterministic or user-driven resolution.
_Avoid_: duplicate, latest value

**Reflection Cycle**:
A consolidation pass that derives stable Memory Facts or Procedures from multiple Memory Observations and safely decays obsolete records.
_Avoid_: answer completeness check, search reflection

**Working Memory**:
The small, task-matched set of Memory Facts selected for the current Agent decision.
_Avoid_: all user history, top-k vector results

## Relationships

- A **Research Run** owns exactly one current **Research State** and a history of checkpoints.
- A **Research State** contains zero or more **Evidence**, **Claim**, and **Critique** records.
- A **Claim** has zero or more **Citations**, each pointing to one **Evidence** record.
- A **Critique** remains open until a later **Research State** resolves or rejects it with evidence.
- A **Research Policy** decides whether a **Research Run** continues, stops, or is cancelled.
- A **Memory Observation** can encode zero or more versioned **Memory Facts**.
- A **Memory Fact** is valid only inside its **Memory Scope** and temporal validity window.
- A **Memory Conflict** exists only when incompatible values have overlapping **Memory Scopes**.
- A **Reflection Cycle** consolidates Memory Observations into durable Memory Facts and Procedures.
- **Working Memory** contains only the Memory Facts selected for the current task and Agent.

## Example dialogue

> **Dev:** "Can the Research Run finish because the score is high?"
> **Domain expert:** "Only if the Research Policy also sees adequate Citation coverage and no open high-severity Critique."

## Flagged ambiguities

- "source" previously meant both a search result and a rendered link; use **Evidence** for the durable research record and **Citation** for its use in a report.
- "resume" previously accepted a run ID but restarted most work; it now means restoring the persisted **Research State** at the next graph node.
