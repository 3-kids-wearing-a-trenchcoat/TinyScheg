# CSP formulation

TinyScheg treats scheduling as a **constraint satisfaction problem (CSP)**. This page explains the CSP concepts
TinyScheg relies on and how scheduling maps onto them. See [ADR 0001](../decisions/0001-model-scheduling-as-csp.md)
for why.

## Background: constraint satisfaction problems

A CSP is a triple $\lbrace X, D, C \rbrace$ where:

* $X = \lbrace X_1, X_2, \dots \rbrace$ are the **variables**;
* $D = \lbrace D_1, D_2, \dots \rbrace$ are the **domains**, where $D_i$ is the set of values variable $X_i$ can
  take;
* $C = \lbrace C_1, C_2, \dots \rbrace$ are the **constraints**. Each constraint involves a subset of the variables
  and specifies which combinations of their values are allowed.

A **state** is an assignment of values to some or all of the variables. An assignment is **consistent** (legal) if
it violates no constraint, and **complete** if every variable has a value. A **solution** is a complete, consistent
assignment.

Constraints come in several kinds:

* a **unary** constraint restricts a single variable on its own;
* a **binary** constraint relates two variables (e.g. "these two must differ");
* an **$n$-ary** constraint relates more variables;
* a **global** constraint involves all variables (e.g. "all values are different");
* **soft constraints** (preferences) describe what's preferable rather than what's required.

**Constraint propagation** is the general term for using constraints to shrink the domains of variables. A
variable is **node consistent** if every value in its domain satisfies its unary constraints. The best-known
propagation algorithm is **AC-3**, which enforces **arc consistency**: for every value in one variable's domain,
there must be a compatible value in the domain of each variable it's constrained with.

## Mapping scheduling onto a CSP

| CSP concept  | In TinyScheg |
|--------------|--------------|
| Variables    | **Slots** — one per worker needed per shift (see [Domain model](domain-model.md)) |
| Values       | **Workers** |
| Domain       | The workers who can still fill a slot |
| Constraints  | Hard constraints: availability, role and minimum rest (below) |
| Solution     | A complete, legal schedule |

Soft constraints — fairness and preferences — are not CSP constraints in TinyScheg. They're handled by the
[penalty score](scoring.md), which is used to choose the best of the legal schedules.

## Unary constraints

> [!WARNING]
> **Not yet implemented.** Domains are to be built by the CSP setup (`csp/problem.py`).

A worker can fill a slot only if they:

* are **available** for the whole of the slot's time range, and
* have the slot's **required role** (`any` is satisfied by everyone).

These are applied once, before the search: each slot's domain starts as only the workers who satisfy them. All slots
are therefore node consistent from the start.

## Binary difference constraints

> [!WARNING]
> **Not yet implemented.** Difference constraints are to be built by the CSP setup (`csp/problem.py`).

A worker can't take a shift during, immediately before or immediately after a shift they're already assigned to.
More precisely, two slots get a **difference constraint** (they must be assigned different workers) if they overlap
in time or are less than the **minimum rest period** apart. The minimum rest period comes from the input settings
and defaults to 6 hours.

This also covers slots of the same shift, since they overlap entirely.

Constraints are generated after all slots exist: slots are sorted by time, and each slot is compared with the slots
that follow it until the first one that starts far enough after it ends. Each constraint is recorded for both slots.
