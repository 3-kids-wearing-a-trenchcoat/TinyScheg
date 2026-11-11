# 0023. A dislike outweighs a like: the neutral partner value stays below 1/2

**Status:** Accepted.

## Context

In the likes penalty, each worker in a shared shift rates each partner from their own lists: a liked partner costs
0, a disliked one costs $\beta$ (1), and a neutral one costs $\alpha$, set as the ratio $\alpha / \beta$ by
`neutral_partner` ([ADR 0022](0022-scoring-parameters-with-defaults-and-input-overrides.md), default 1/3). Each side
of a pair is rated separately, so a pair costs the sum of both workers' ratings.

The neutral value decides how a like compares with a dislike. Measured from a neutral pairing, a like saves
$\alpha$ and a dislike costs $\beta - \alpha$. They balance exactly at $\alpha / \beta = 1/2$: then a pair where one
worker dislikes the other and the other likes them costs $1 + 0 = 1$, the same as two neutral workers
($\tfrac12 + \tfrac12$). Above 1/2 such a pair would even score *better* than a neutral one. ADR 0022 allowed any
value between 0 and 1.

From experience, a worker stuck with someone they dislike is worse off than a worker paired with someone they like
is better off: if A dislikes B but B likes A, the pairing should be a net negative, not neutral.

## Decision

`neutral_partner` must be **more than 0 and less than 1/2**, the limit being the named constant
`MAX_NEUTRAL_PARTNER` (0.5, exclusive). This replaces ADR 0022's upper limit of 1; the default, 1/3, is unchanged
and already meets it (a dislike counts twice as much as a like). An input setting 0.5 or more is rejected with an
error saying why. Tuning chooses only within this range.

## Consequences

* A pair where one dislikes the other always costs more than a neutral pair, whatever the input says: at the
  default, 1 against 2/3.
* The parameter still sets *how much* a dislike outweighs a like: $(1 - \alpha/\beta) / (\alpha/\beta)$ times, e.g.
  twice at 1/3, three times at 1/4, one and a half times at 0.4.
* Inputs that relied on values of 0.5 or more are now invalid. None are known; the parameter was introduced recently.
