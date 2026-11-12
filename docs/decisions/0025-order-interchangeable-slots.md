# 0025. Fill a shift's interchangeable slots in ascending worker order

**Status:** Accepted.

## Context

Slots of the same shift that need the same role, such as the two slots of a gate shift needing 2 of anyone, are
**interchangeable**: they have the same time, length and role, and so the same initial domain and the same
constraints, and the [scoring](../explanation/scoring.md) treats a shift's slots alike (the likes penalty averages
over a shift's other slots, and workload and rest depend only on the slot's time). Putting (Anne, Bob) or (Bob, Anne)
in them is the same schedule, but the search explored both, and $k!$ orders for $k$ such slots. With
[branch and bound](0004-branch-and-bound-with-monotone-penalty.md) running to the end, that duplicate work made
inputs with many shared shifts take far longer.

Schedules are often **asymmetric**: shifts of different lengths, dangling shifts at the end of a period, variations
with other roles, posts open only part of the day. Only symmetry *within* a shift is safe whatever the shape of the
schedule; shifts or time blocks are never treated as interchangeable, since they differ in hours, rest targets and
who is available. Symmetry between workers (two workers identical in every respect) is also safe in principle, but
rare in practice and easy to get wrong, so it's left out.

## Decision

Interchangeable slots are filled in **ascending worker index** (input order): when one is assigned, forward checking
keeps only the workers after it in the domains of the later ones (by slot index), and only those before it in the
earlier ones. `Problem.interchangeable` lists each slot's interchangeable slots.

Any legal schedule can be turned into one in this order by sorting the workers within each group of interchangeable
slots; that schedule is just as legal and has exactly the same penalty. So the best penalty is unchanged, for the
first legal schedule and for branch and bound alike.

## Consequences

* The same best penalty, found sooner where shifts have interchangeable slots: on the one benchmark input that has
  them (2026-11-12), 43 times fewer nodes, 174 s down to 4.5 s. Inputs without them are unaffected.
* Which of several equally good schedules is kept can change, but only by the order of workers within a shift.
* Tested against brute force on small inputs, and against the same search without the ordering.
