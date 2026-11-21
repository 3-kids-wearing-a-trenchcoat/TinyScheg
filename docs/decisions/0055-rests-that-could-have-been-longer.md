# 0055. Rests that could have been longer, and nearby schedules judged against the audited schedule's typical rest

**Status:** Accepted (2026-11-21). Amends [ADR 0054](0054-rest-against-the-typical-rest.md) (a nearby schedule was
judged against its own typical rest) and [ADR 0052](0052-a-worker-panel-as-a-check-on-the-audit.md) (how the
panel's input shows rests).

## Context

The [worker panel](0052-a-worker-panel-as-a-check-on-the-audit.md) checked the audit of ADRs 0053 and 0054 on
2026-11-21: 4 workers drawn at random from each of the 16 schedules read in
[Phase 13](../roadmap.md#phase-13-a-reliable-audit)'s step 4.
* 12 workers raised a short rest the audit counts as typical, mostly 6 hours after a 2-hour shift where that's the
  median.
* They raised it against someone else's much longer gap.

The user's view:
* a 6-hour rest is harsh, but if everyone has it, it's what there is to work with;
* workers objecting to one person's extra rest suggests at least some of those 6-hour rests came from oversight,
  not necessity;
* outliers are exactly the sign to look for, and the median hides them.

Checked on 2026-11-21:

* **The 12 rests.** Each was searched for a nearby schedule (up to 3 changes) that lengthens it with nobody gaining a
  grievance.
  * 1 had one: two 6-hour rests could have been 7 and 8 hours, with two others giving up rest but staying at the
    typical rest.
  * Most of the long gaps the workers cited included time between the two schedules or time away. The panel's input
    gave the whole gap first and that part second: "20 h, of which 8 h away or between schedules".
* **The mean as the typical rest,** the user's proposal. With the full audit on the 16 schedules:
  * rest events went from 61 to 190, and workers with one from 53 to 119 of 174;
  * events with a harmless fix fell from 14 to 8;
  * all 12 raised rests became events, none with a harmless fix.

  A few long rests lift the mean above the common 6 hours. A higher yardstick also turns most fixes into transfers,
  since any rest given up falls below it. The mean flags almost everyone and finds less that could be fixed.
* **The fix search asked directly.** A lab trial checked every worker with no rest event whose shortest rest is at the
  typical rest: 77 workers on the 16 schedules. It found 11 whose rest could have been longer at no one's expense,
  each with 1 to 3 swaps or moves. Outliers did hide oversight. Asking the fix search finds it without inflating the
  grievances.
* **A flaw found while building it.** Under ADR 0054, each nearby schedule was judged against its own typical rest.
  * Shortening several workers' rests lowers that yardstick with them, so the harm went unseen.
  * Lengthening one rest by shortening three passed as harmless.
  * The regular fix search had the same flaw, for rest fixes and for any fix that moves rests.

## Decision

1. **Every nearby schedule is judged against the audited schedule's typical rest.** It's a fixed yardstick, like the
   share for load, which is the same in every nearby schedule anyway. Judging a nearby schedule against its own
   typical rest would let a fix lower the yardstick by shortening others' rests.
2. **Rests that could have been longer.**
   * **Who is checked:** a worker with no rest event whose shortest rest, per hour of the shift before it, is at the
     typical rest. Workers with rest events already get the regular fix search.
   * **What counts:** a nearby schedule within the fix search's reach in which:
     * their shortest rest is longer;
     * none of their rests is shorter (place by place, shortest first, with no fewer rests);
     * nobody has a new or larger grievance of any kind ([ADR 0050](0050-a-fix-harms-only-where-a-workers-own-situation-gets-worse.md)).

     Others may rest less, as long as it gives them no event.
   * **How it's shown:** the smallest such schedule, a note on the worker's card and in the JSON report. A note isn't
     a grievance, and isn't counted in the closing table.
   * **How it's found:** in the same search as the fixes, each nearby schedule audited once.
3. **Tuning records rest's notes:** how many workers' shortest rests could have been longer (`rest_longer`). It's the
   sign that the model left rest on the table where no grievance shows it. Fewer is better, and it counts in dominance
   like the other measures.
4. **The panel's input leads with the time a worker was available** between two shifts, then the whole gap where it
   differs: "12 h (a 20 h gap, 8 h of it away or between schedules)". That's how the audit counts rest, and workers
   then compare like with like.

**Not taken:**
* **The mean as the typical rest:** see above.
* **Leaving typical rests unsearched:** the oversight the user expected exists (11 of 77 candidates) and stays out of
  sight.
* **Notes for every rest at or below the typical rest,** including workers with rest events: those already get fixes
  for their events.

## Consequences

* **On the stored tuning stages,** audited again:
  * notes appear for 5 of the 87 workers of next-period's first periods, and 3 of its second periods;
  * in the larger stages, notes appear for 47 of 684 workers (`s3b-workload`), 55 of 870 (`s3-candidates`) and 78 of
    1305 (`s2-weights`), first periods;
  * harmless rest fixes fell where they had relied on the moving yardstick, for example 70 to 16 in `s2-weights`'
    first periods, 49 to 23 in `s3b-workload`'s and 7 to 3 in next-period's;
  * a few load fixes became transfers for the same reason, for example 21 to 12 in `s4-check`'s first periods: the
    worker taking the shift would rest less than the typical rest.
* **Cost:** the re-audit took about as long as before, since the notes share the search's walk through nearby
  schedules.
* **Results audited before this ADR aren't comparable** with those after. **Panel answers from before the input
  change aren't comparable either.**
* **Checked by:**
  * hand-made tests: a note where two swaps with a longer-resting worker lengthen a typical rest; no note when
    everyone rests the same, even where shortening three rests would lower the schedule's own typical rest;
  * the notes against brute force on a small input;
  * the fix search against brute force on the fixed yardstick;
  * the panel input's rest line, with time away.
