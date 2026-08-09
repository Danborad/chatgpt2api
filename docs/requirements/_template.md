# NNNN: Requirement title

Status: draft

- Owner: unassigned
- Created: YYYY-MM-DD
- Updated: YYYY-MM-DD
- Related issues/ADRs: none

## Problem and user outcome

Describe the observed problem and the user-visible outcome. Do not prescribe an
implementation before the current behavior and ownership are established.

## Current behavior and evidence

Record verified current behavior with links to code, contracts, tests, or
current documentation. State unknowns explicitly. Plans and upstream projects
are not implementation evidence.

## Scope

- In scope:
- In scope:

## Non-goals

- Not included:
- Not included:

## Domain language

List existing terms from [`../../CONTEXT.md`](../../CONTEXT.md) and define any
proposed new term. Update `CONTEXT.md` before implementation if a new domain
term or relationship is accepted.

## Unique owners

Every affected concern must have one authoritative owner. Add rows as needed;
do not maintain mirrored rules in multiple layers.

| Concern | Authoritative owner | Interface consumed by others | Forbidden mirror or fallback |
| --- | --- | --- | --- |
| Business meaning |  |  |  |
| State transitions |  |  |  |
| Request/task lifecycle |  |  |  |
| Concurrency and cleanup |  |  |  |
| Persistence |  |  |  |
| Loading and selection |  |  |  |
| Layout, overlay, focus, or scrolling |  |  |  |

## Backend Modules and Interfaces

Name the owning service, repositories, projections, commands, public contracts,
error modes, and transaction boundary. Explain whether this changes an existing
Interface or introduces a real new one.

## Frontend interaction and responsive behavior

Describe the page workflow, loading/empty/error states, focus and overlay
lifecycle, responsive breakpoints, and the single scroll owner. Separate
backend-owned business meaning from frontend-owned presentation state.

## Persistence impact

State the authoritative store, records affected, transaction semantics,
retention/cleanup behavior, backup impact, and whether data can be discarded.
Do not infer a migration or compatibility requirement without user approval.

## Concurrency, security, and failure behavior

Describe admission limits, idempotency, cancellation, retries, authorization,
sensitive data, timeout behavior, partial failures, and recovery ownership.

## Acceptance criteria

- [ ] Observable outcome with an exact success condition.
- [ ] Failure/empty/loading behavior with an exact success condition.
- [ ] Responsive or accessibility behavior where applicable.
- [ ] Removed behavior and stale documentation are absent.

## Verification matrix

| Acceptance criterion | Verification level | Evidence required | Status |
| --- | --- | --- | --- |
|  | Contract/unit/integration/build/manual | Command, test, response, or user confirmation | pending |

Automated checks, browser inspection, user acceptance, and publication are
separate states. Record only evidence that actually exists.

## Documentation and CHANGELOG impact

List current maps, topic documents, runbooks, `CONTEXT.md`, ADRs, and
`CHANGELOG.md` entries that must change with the implementation.

## ADR requirement

State `not required` with a reason, or describe the durable architecture
decision that needs an ADR before implementation.

## Rollback

Describe how to stop or reverse the change without inventing compatibility work
that is outside the approved scope.

## Unresolved questions

- None, or list the decision owner and the exact question.
