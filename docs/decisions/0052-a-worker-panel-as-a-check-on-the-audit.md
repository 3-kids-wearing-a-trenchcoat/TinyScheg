# 0052. A worker panel: a language model plays each worker, as a check on the audit

**Status:** Accepted (2026-11-21).

## Context

The [schedule audit](../explanation/schedule-audit.md) finds grievances by rules written down in
[ADRs 0048–0051](0048-an-audit-that-only-observes.md). In [Phase 13](../roadmap.md#phase-13-a-reliable-audit)'s
step 4, reading cards by hand with the user is what tests those rules
([ADR 0051](0051-the-audit-after-reading-cards-by-hand.md)), and it's slow: eight cards in a session.

On 2026-11-20 the user proposed a check that scales: a language model playing each worker, reading the published
schedule and saying what they'd complain about, so that the complaints can be set against the audit's grievances. The
user set its limits:
* it's done alongside the audit, not instead of it;
* it runs through Claude Code on the user's account, with no API key, nothing installed and the environment
  untouched, since it's only a development tool;
* the definition is minimal: inputs are facts, with no verdicts;
* each worker sees only their own likes and dislikes;
* each complaint records whether the worker thinks it could have been avoided.

**The first full run** gave each of the 174 workers of the 16 schedules read in step 4 their own Claude Code
subagent (Sonnet, low effort). Their 198 complaints (42 workers had none) were matched by hand to the audit's
grievances:

| kind | in both | audit only | workers only |
|---|---|---|---|
| load | 63 | 15 | 22 |
| rest | 66 | 61 | 3 |
| missing like | 16 | 28 | 15 |
| disliked partner | 0 | 0 | 0 |
| other | – | – | 11 |

* **Load.** Workers judged their load against the even share they were shown, the audit against the best-off peer.
  In 19 of the 22 "workers only" cases, the extra hours were fewer than the worker's shortest shift, so no event
  under ADR 0051. The 15 "audit only" cases were workers at their even share, above the best-off peer.
* **Rest.** Workers raised rests at the minimum they were told about, 6 hours, even where everyone had 6 hours. They
  never raised rests that were short only in proportion to the shift before them.
* **Missing likes.** Of the 15 "workers only" cases, 11 were workers whose shifts were all worked alone. Three were
  likes cancelled by a dislike the worker couldn't know about. One was a worker who wanted a different liked person.
* **Other:**
  * 7 about short or split shifts: an hour's shift, or more shifts for the same hours;
  * 3 about long desk shifts worked alone;
  * 1 about night shifts.
* **Disliked partners.** None of the 16 schedules put anyone with someone they dislike, so this kind went untested.

**The run was expensive.** By the usage logs, each subagent processed about 23,000 tokens in three requests:
* Claude Code's subagent preamble, about 4,300 tokens, sent with every request;
* the input file, read with line numbers;
* the write of the answer.

Relaunching 34 of them took 44% of the user's five-hour usage limit. The user asked for a setup that uses fewer tokens,
and for instructions that set no thresholds: a worker should compare themselves with the others, not be told the
minimum rest. The options were tested on 2026-11-21, a step at a time, at a cost of about 70 model calls.

## Decision

### 1. A development check alongside the audit

1. **The panel is a check, not the audit's basis, and not a tuning measure.** Its "workers only" complaints point to
   what the audit may miss, for the user to judge as with cards read by hand. The cards remain the reference.
2. **Its answers aren't a ground truth:**
   * what the input shows steers them, as the minimum rest and the even share did;
   * the model comes from the same family as the one that helped design the audit;
   * workers raise what stands out, not everything: in the first run, 27 workers whose own rest was at the minimum
     didn't raise it.

   "Audit only" grievances therefore don't make the audit wrong: the audit lists every event, and which of them a
   worker would raise is interpretation ([ADR 0048](0048-an-audit-that-only-observes.md)).

### 2. What a worker sees: facts, with no thresholds and no targets

1. **The workplace:**
   * every slot must be filled;
   * shifts are a duty, and everyone would rather work less;
   * work is shared in proportion to availability, counting only hours when a post is staffed;
   * some slots need a role;
   * every hour counts the same, whatever the time of day;
   * people work together only with the others on the same shift;
   * with history, which shifts were already worked.
2. **The schedule:** a grid with numbered shifts and each post's slots, who is away when, and each worker's roles.
3. **Every worker's facts:** their hours available and worked, the share of their available time worked, and the
   number of shifts; their shifts, each with its length; and their rests.
4. **The worker's own profile:** their roles, likes and dislikes. Nobody else's preferences are shown.
5. **Not shown:**
   * **the minimum rest.** Without it, workers judged rests against each other's: one worker raised 6 hours where
     others had 7 to 11, and another said nothing where everyone had 6;
   * **the even share.** Without it, a worker at the even share complained against the workers 2 hours below, as
     the audit does, and a less available worker scaled their load correctly;
   * **anything the audit found.**

### 3. What a worker is asked

The instructions are the minimal ones agreed on 2026-11-20. Read the schedule as this worker would, and write down
each thing about your own schedule that you'd complain about to whoever made it, raising only what you'd actually
raise. Answer with a JSON list, one entry per complaint: the complaint in the worker's own words, the shifts and
coworkers it's about, and whether it could have been avoided ("yes", "no" or "not sure").

### 4. How it runs

1. **Headless Claude Code** (`claude -p`) on the user's account, with **Sonnet** at low effort. It runs with our system
   prompt only: no tools, no MCP servers, no settings, no saved session, and from an empty folder outside the
   repository, so that no project instructions are picked up.
2. **The part of the input every worker of a schedule shares goes in the system prompt,** and the worker's own profile
   is the message. The workers of a schedule run one after another, so that each one after the first reads the
   shared part from the cache.
3. **A routine check is 4 workers per schedule, drawn at random.** Replayed 10,000 times on the first run, such a
   sample caught every finding seen 7 times or more, and found the "workers only" ones better than picking the most
   aggrieved workers. Findings seen only once to three times in 174 workers can be missed by any sample. The full
   panel is for when that matters.
4. **Complaints are matched to grievances by reading them,** with each complaint's kind and matching grievances noted.
5. **The tool is
   [`tools/worker_panel.py`](https://github.com/3-kids-wearing-a-trenchcoat/TinyScheg/blob/main/tools/worker_panel.py)**,
   covered by tests that check the input files and the command without running the model. It writes each schedule's
   input files (`write`) and runs the workers (`run`, `--sample` for a routine check, `--dry-run` to see what would be
   sent), recording each worker's tokens and cost. The Claude Code subagent used for the first run is removed.

**Not taken:**
* **Subagents:** 13,000 to 23,000 tokens a worker, against about 3,000.
* **Haiku:** about 15 times cheaper, but on seven chosen workers it missed one worker's complaints entirely, and three
  complained about night shifts, against the input's own rule.
* **One reviewer per schedule,** writing everyone's complaints in one call: much cheaper, but it would see everyone's
  preferences.
* **The panel as the audit's basis or as a tuning measure:** see 1.
* **The Claude API with a key:** the user's choice, so that nothing is installed and the account in use pays for it.

## Consequences

* **The cost:**
  * 22 workers of two schedules cost about 66,600 tokens and, at the list prices `claude -p` reports, $0.20;
  * the user's usage meter rose by 2 points, including the main session's own turns;
  * each worker after the first in a schedule reads about 1,860 tokens from the cache and pays in full for about 580,
    most of them added by Claude Code to every request. Its output, mostly thinking, is about 70% of its cost;
  * a routine check of 64 workers comes to about 3% of the five-hour limit, the full panel to about 8%.
* **What the first run raised,** for the user to decide on:
  * the extra hours fewer than the worker's shortest shift (ADR 0051, 1.2);
  * load judged against the best-off peer or against the even share. Without the even share shown, the one worker
    tested judged it as the audit does;
  * short or split shifts, which bear on dangling shifts in the roadmap's "Later" section.
* **Driving the panel from a long session costs about as much as the panel.** Each turn of the main session re-reads
  its whole conversation. A routine check is cheapest started by the user, or from a fresh session.
* **The first run's answers aren't comparable with later ones:** the input and the way it runs both changed after it.
* **The tests on 2026-11-21 are kept in the lab folder** (`tools/benchmarks/results/2026-11-20-phase13-step4/`): every
  answer and the matching.
