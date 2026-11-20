"""Tests for the tuning tools: tools/benchmarks/generate.py and tools/tune.py."""
import copy
import csv
import dataclasses
import datetime as dt
import pathlib
import statistics
import sys

import pytest

import tune
from audit import DEFAULT_MAX_CHANGES, FIX_COUNT_FIELDS, KIND_ORDER, LOAD, REST, WorkerTally
from benchmarks import generate
from schedule_checker import hard_constraint_violations
from tinyscheg.csp.problem import build_problem
from tinyscheg.csp.search import find_first_schedule
from tinyscheg.parsing.input_reader import parse_input, read_input
from tinyscheg.scoring.constants import build_constants
from tinyscheg.timing.datetime_range import DateTimeRange

SEEDS = range(5)
HOURS = 12


# --- the generator ---

@pytest.mark.parametrize("seed", SEEDS)
def test_generated_inputs_meet_the_requirements_and_have_a_legal_schedule(seed: int) -> None:
    generated = generate.generate(seed, HOURS)
    if generated is None:
        return
    document, knobs = generated
    generate.check_requirements(document)
    problem = build_problem(parse_input(document))
    assignment = find_first_schedule(problem).assignment
    assert assignment is not None
    assert hard_constraint_violations(parse_input(document), problem.slots, assignment) == []
    assert knobs["workers"] == len(document["workers"]) == knobs["minimum_staff"] + knobs["slack"]


def test_generation_is_deterministic() -> None:
    assert generate.generate(1, HOURS) == generate.generate(1, HOURS)


def test_inputs_lacking_a_requirement_are_caught() -> None:
    generated = next(generate.generate(seed, HOURS) for seed in SEEDS if generate.generate(seed, HOURS))
    assert generated is not None
    document = copy.deepcopy(generated[0])
    for worker in document["workers"]:
        worker["likes"], worker["dislikes"] = [], []
    with pytest.raises(AssertionError, match="preferences"):
        generate.check_requirements(document)
    document = copy.deepcopy(generated[0])
    document["posts"] = document["posts"][:1]
    with pytest.raises(AssertionError, match="2 posts"):
        generate.check_requirements(document)


def test_written_inputs_read_back_the_same(tmp_path: pathlib.Path) -> None:
    generated = next(generate.generate(seed, HOURS) for seed in SEEDS if generate.generate(seed, HOURS))
    assert generated is not None
    path = tmp_path / "input.yml"
    generate.write_input(path, *generated)
    assert path.read_text(encoding="utf-8").startswith("# Benchmark input")
    assert read_input(path) == parse_input(generated[0])


def test_a_tier_keeps_the_same_inputs_for_any_number_of_jobs(tmp_path: pathlib.Path,
                                                              monkeypatch: pytest.MonkeyPatch) -> None:
    # solving is faked (an odd number of workers is "over the limit"), so the test is fast and doesn't depend on timing
    processes_used = set()

    def fake_solve(document: dict, limit: float, processes: int = 1) -> tuple[float, float, int, int] | None:
        processes_used.add(processes)
        return None if len(document["workers"]) % 2 else (1.0, 0.5, 10, 2)
    monkeypatch.setattr(generate, "solve_within", fake_solve)
    monkeypatch.setattr(generate, "default_processes", lambda: 4)
    tier = generate.Tier("test", (HOURS,), 3, 0, 1.0, generate.STAFFED)
    one_at_a_time = dataclasses.replace(tier, one_at_a_time=True)  # tried in turn, each search in 4 processes
    results = {}
    for jobs, each_tier in ((1, tier), (3, tier), ("in turn", one_at_a_time)):
        monkeypatch.setattr(generate, "INPUTS", tmp_path / str(jobs))
        (tmp_path / str(jobs)).mkdir()
        results[jobs] = generate.build_tier(each_tier, 3 if jobs == "in turn" else jobs)
    assert results[1] == results[3] == results["in turn"]
    assert processes_used == {4}  # the pool's searches ran in other processes, out of this set's reach
    assert sum(1 for row in results[1] if row["name"]) == tier.count
    assert sorted(path.name for path in (tmp_path / "3").iterdir()) == ["test_01.yml", "test_02.yml", "test_03.yml"]


def test_writing_a_tier_replaces_only_its_own_manifest_rows(tmp_path: pathlib.Path,
                                                             monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(generate, "MANIFEST", tmp_path / "manifest.csv")
    generate.write_manifest("sweep", [{"name": "sweep_01", "tier": "sweep"}, {"name": "sweep_02", "tier": "sweep"}])
    generate.write_manifest("confirm", [{"name": "confirm_01", "tier": "confirm"}])
    generate.write_manifest("sweep", [{"name": "sweep_01", "tier": "sweep"}])
    with open(tmp_path / "manifest.csv", encoding="utf-8", newline="") as file:
        assert [row["name"] for row in csv.DictReader(file)] == ["confirm_01", "sweep_01"]


# --- the tuning runner ---

def test_a_weight_share_keeps_the_other_weights_ratio() -> None:
    weights = tune._with_share(0.4, "likes_weight")
    assert sum(weights.values()) == pytest.approx(1)
    assert weights["likes_weight"] == 0.4
    assert weights["workload_weight"] / weights["rest_weight"] == pytest.approx(
        tune.DEFAULT_WORKLOAD_WEIGHT / tune.DEFAULT_REST_WEIGHT)


def test_every_sensitivity_setting_is_valid_and_named_uniquely() -> None:
    settings = tune.sensitivity_settings()
    assert len({setting.name for setting in settings}) == len(settings)
    for setting in settings:
        setting.parameters()  # raises if invalid, e.g. a neutral partner of 1/2 or more


def result_row(setting: str, input_name: str, holdout: str = "False", max_changes: int = 3, assignment: str = "0 1",
               by_worker: str = "[]", **measures: float) -> dict[str, str]:
    """A results row of a finished first period: every audit measure 0 but those given (by field name)."""
    row = {"setting": setting, "input": input_name, "tier": "sweep", "holdout": holdout, "status": "done",
           "seconds": "1", "liked_pairings": "2", "max_changes": str(max_changes), "assignment": assignment,
           "by_worker": by_worker}
    return row | {field: str(measures.get(field, 0)) for field in tune.KIND_FIELDS}


def test_each_kinds_measures_are_means_over_the_inputs_in_the_stages_order() -> None:
    rows = [result_row("b", "x", load_events=2), result_row("a", "x", load_events=1),
            result_row("b", "y", load_events=4), result_row("b", "z", holdout="True", load_events=9)]
    summaries = tune.kind_summaries(rows)
    assert [summary["setting"] for summary in summaries] == ["b", "a"]  # no ranking
    assert summaries[0]["inputs"] == 2 and summaries[0]["load_events"] == 3  # held-back inputs left out by default
    assert tune.kind_summaries(rows, include_holdout=True)[0]["inputs"] == 3
    assert summaries[0]["k"] == [3] and summaries[0]["liked_pairings"] == 2


def test_a_setting_is_dominated_only_if_no_better_in_any_measure_and_worse_in_one() -> None:
    rows = [result_row("defaults", "x", load_events=2, rest_hours=4.5),
            result_row("worse", "x", load_events=3, rest_hours=4.5),           # dominated by defaults
            result_row("trade", "x", load_events=1, rest_hours=6.0),           # better at load, worse at rest
            result_row("equal", "x", load_events=2, rest_hours=4.5 + 1e-12)]   # the same as the defaults
    assert tune.dominated_by(rows) == {"defaults": [], "worse": ["defaults", "equal"], "trade": [], "equal": []}


def test_dominance_compares_only_the_inputs_both_finished_and_never_across_k() -> None:
    rows = [result_row("defaults", "x", load_events=1), result_row("defaults", "y", load_events=9),
            result_row("other", "x", load_events=2),                          # worse on x; y never finished
            result_row("deeper", "x", max_changes=4, load_events=5)]           # audited with another K
    assert tune.dominated_by(rows) == {"defaults": [], "other": ["defaults"], "deeper": []}
    mixed = rows + [result_row("defaults", "z", max_changes=4)]  # the defaults now audited with two K values
    assert tune.dominated_by(mixed) == {"defaults": [], "other": [], "deeper": []}
    assert "WARNING: audited with different K" in "\n".join(tune.describe_audit(mixed, False, "", "first period"))


LOAD_EVENT_HOURS = 2.0  # the extra hours of each load event in worker_json


def worker_json(*workers: tuple[str, int, float]) -> str:
    """
    The by_worker field of workers, each (name, load events with only transfers, each LOAD_EVENT_HOURS extra hours,
    rest hours short in 1 event)
    """
    tallies = []
    for name, load, rest_hours in workers:
        counts = {kind: dict.fromkeys(FIX_COUNT_FIELDS, 0) for kind in KIND_ORDER}
        counts[LOAD] |= {"events": load, "transfers": load}
        counts[REST] |= {"events": int(rest_hours > 0), "transfers": int(rest_hours > 0)}
        tallies.append(WorkerTally(name, counts, {LOAD: LOAD_EVENT_HOURS * load, REST: rest_hours},
                                   {LOAD: 0.0, REST: 0.0}))
    return "[" + ",".join(tune.json.dumps(tune.tally_json(tallied)) for tallied in tallies) + "]"


def test_compare_shows_both_tables_on_the_inputs_whose_schedules_differ() -> None:
    first = worker_json(("Anne", 1, 2.5), ("Jack", 2, 0))
    second = worker_json(("Anne", 1, 4.0), ("Jack", 1, 0))
    rows = [result_row("defaults", "x", assignment="0 1", by_worker=first),
            result_row("trial", "x", assignment="1 0", by_worker=second),
            result_row("defaults", "y", assignment="0 1", by_worker=first),
            result_row("trial", "y", assignment="0 1", by_worker=first),
            result_row("defaults", "z", by_worker=first)]
    text = tune.compare_settings(rows, "defaults", "trial")
    assert text.startswith("defaults | trial: 1 of 2 inputs give different first-period schedules")
    lines = text.splitlines()
    block = lines[lines.index("x"):]
    assert "defaults" in block[1] and block[1].index("trial") > block[1].index("defaults")
    anne = next(line for line in block if line.startswith("Anne"))
    assert "1 (0/1/0/0) 2.5 h short" in anne and "1 (0/1/0/0) 4 h short" in anne  # every worker's cells
    differences = block.index("differences:")
    assert block[differences + 1:differences + 4] == ["  Anne rest: 1 (0/1/0/0) 2.5 h short → 1 (0/1/0/0) 4 h short",
                                                      "  Jack load: 2 (0/2/0/0) 4 h more → 1 (0/1/0/0) 2 h more", ""]
    assert "same schedule under both: y" in lines and "finished under only one: z (defaults)" in lines
    with pytest.raises(ValueError, match="no finished runs"):
        tune.compare_settings(rows, "defaults", "nothing")
    with pytest.raises(ValueError, match="different K"):
        tune.compare_settings(rows + [result_row("trial", "w", max_changes=2)], "defaults", "trial")


def test_one_run_finds_and_audits_the_best_schedule(tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch) -> None:
    generated = next(generate.generate(seed, HOURS) for seed in SEEDS if generate.generate(seed, HOURS))
    assert generated is not None
    (tmp_path / "inputs").mkdir()
    generate.write_input(tmp_path / "inputs" / "small.yml", *generated)
    monkeypatch.setattr(tune, "BENCHMARKS", tmp_path)
    row = tune.run_one("baseline", tune.DEFAULTS, tune.Benchmark("small", "sweep", False))
    assert row["status"] == "done" and row["penalty"] >= 0
    assert set(row) <= set(tune.RESULT_FIELDS)
    assert len(row["assignment"].split()) == len(build_problem(parse_input(generated[0])).slots)
    assert row["max_changes"] == DEFAULT_MAX_CHANGES and set(tune.KIND_FIELDS) <= set(row)
    tallies = tune.tallies_from_json(row["by_worker"])
    assert [tallied.name for tallied in tallies] == [worker["name"] for worker in generated[0]["workers"]]
    assert row["load_events"] == sum(tallied.counts[LOAD]["events"] for tallied in tallies)


def test_one_run_continues_for_a_second_period(tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch) -> None:
    # day 2: the input continued for the same hours a day later (the period is 12 hours), with the first's schedule
    # as its history; a first period that leaves the second no legal schedule is recorded as such
    generated = next(generate.generate(seed, HOURS) for seed in SEEDS if generate.generate(seed, HOURS))
    assert generated is not None
    (tmp_path / "inputs").mkdir()
    generate.write_input(tmp_path / "inputs" / "small.yml", *generated)
    monkeypatch.setattr(tune, "BENCHMARKS", tmp_path)
    row = tune.run_one("baseline", tune.DEFAULTS, tune.Benchmark("small", "sweep", False))
    assert row["day2_status"] in ("done", "no schedule")
    first = parse_input(generated[0])
    second = tune.next_period(first, tuple(int(worker) for worker in row["assignment"].split()))
    assert second.settings.period.start == first.settings.period.start + dt.timedelta(days=1)
    assert second.settings.period.duration == first.settings.period.duration
    assert second.history[0].schedule_input == first
    if row["day2_status"] == "done":
        whole = build_problem(second)
        assert len(row["day2_assignment"].split()) == len(whole.slots)  # both periods
        assert row["day2_rests"] >= row["rests"]


def test_measures_that_dont_come_from_the_audit() -> None:
    # 2-hour shifts from 00:00 to 12:00, one desk worker at a time, minimum rest 2 hours. Anne works 00-02, 04-06 and
    # 08-10 (rests 2 and 2, both at the minimum); Bob 02-04 and 10-12 (rest 6); Cy 06-08 and is away 08-12. Bob
    # dislikes Anne, but they never share a shift (one worker per shift), so no pairings.
    document = {"settings": {"time": ["2025-01-01T00:00", "2025-01-01T12:00"], "min_rest": 2},
                "workers": [{"name": "Anne"}, {"name": "Bob", "dislikes": ["Anne"]},
                            {"name": "Cy", "unavailable": [["2025-01-01T08:00", "2025-01-01T12:00"]]}],
                "posts": [{"name": "desk", "roles": {"any": 1}, "length": 2}]}
    schedule_input = parse_input(document)
    problem = build_problem(schedule_input)
    constants = build_constants(schedule_input.settings, problem.workers, problem.shifts, problem.slots,
                                problem.scoring_domains)
    anne, bob, cy = 0, 1, 2
    measures = tune.measure_fields(problem, constants, (anne, bob, anne, cy, anne, bob))
    assert measures["rests"] == 3 and measures["rests_at_minimum"] == 2 and measures["rest_median"] == 2
    assert measures["shortest_rest_spread"] == 4      # Bob's shortest 6, Anne's 2; Cy has one shift
    assert measures["peer_hours_gap"] == 2            # Anne 6 h, Bob 4 h; Cy isn't fully available
    assert measures["peer_shifts_gap"] == 1
    assert measures["liked_pairings"] == measures["disliked_pairings"] == 0


def test_unit_tradeoffs_follow_the_formulas() -> None:
    # at the defaults, a like costs alpha / beta of the likes weight and a dislike 1 - alpha / beta; with workload
    # power 2, one extra average shift costs one workload unit and moving one shift between equal workers two
    tradeoffs = tune.unit_tradeoffs(tune.DEFAULTS)
    parameters = tune.DEFAULTS.parameters()
    assert tradeoffs["like"] == pytest.approx(parameters.likes_weight * parameters.neutral_partner)
    assert tradeoffs["dislike"] == pytest.approx(parameters.likes_weight * (1 - parameters.neutral_partner))
    assert tradeoffs["extra_shift"] == pytest.approx(parameters.workload_weight)
    assert tradeoffs["outrage"] == pytest.approx(2 * parameters.workload_weight)
    assert tradeoffs["second_short_rest"] == pytest.approx(3 * tradeoffs["first_short_rest"])  # squared: 4 - 1
    # one worker resting at the minimum twice: short twice by two average shifts' target less the minimum, squared
    schedule_input = read_input(tune.EXAMPLE)
    problem = build_problem(schedule_input)
    constants = build_constants(schedule_input.settings, problem.workers, problem.shifts, problem.slots,
                                problem.scoring_domains)
    shift_hours = statistics.fmean(constants.slot_hours)
    shortfall = 2 * (constants.rest_factor * shift_hours - constants.min_rest)
    assert tradeoffs["twice_at_minimum"] == pytest.approx(parameters.rest_weight * shortfall ** 2
                                                          / constants.rest_scale)
    assert tradeoffs["outrage_per_twice_at_minimum"] == pytest.approx(tradeoffs["outrage"]
                                                                      / tradeoffs["twice_at_minimum"])
    # each rule check can fail: at a much lighter workload weight an outrage outweighs neither three dislikes nor one
    # worker resting at the minimum twice; at a much heavier rest weight a like is worth far less than a short rest
    assert all(tradeoffs[check] for check in tune.RULE_CHECKS)
    lighter = tune.unit_tradeoffs(tune.Setting("lighter", workload_weight=0.2))
    assert not lighter["outrage_outweighs_pairings"]
    assert not lighter["outrage_outweighs_twice_at_minimum"]
    assert not tune.unit_tradeoffs(tune.Setting("heavier rest", rest_weight=1))["like_about_one_short_rest"]


def test_reaudit_redoes_the_audit_of_a_finished_stage_only(tmp_path: pathlib.Path,
                                                           monkeypatch: pytest.MonkeyPatch) -> None:
    generated = next(generate.generate(seed, HOURS) for seed in SEEDS if generate.generate(seed, HOURS))
    assert generated is not None
    (tmp_path / "inputs").mkdir()
    generate.write_input(tmp_path / "inputs" / "small.yml", *generated)
    monkeypatch.setattr(tune, "BENCHMARKS", tmp_path)
    monkeypatch.setattr(tune, "RESULTS", tmp_path / "results")
    tune.RESULTS.mkdir()
    row = tune.run_one("baseline", tune.DEFAULTS, tune.Benchmark("small", "sweep", False))
    stale = {key: value for key, value in row.items() if key not in tune.AUDIT_FIELDS}
    stale |= {"complaints": 999, "easy_fix_severity": 999}  # as if audited by an older audit, with its columns
    with open(tune.results_path("baseline"), "w", encoding="utf-8", newline="") as file:
        writer = csv.DictWriter(file, list(stale))
        writer.writeheader()
        writer.writerow(stale)
    assert tune.main(["report", "baseline"]) == 1  # older columns: re-audit first
    tune.status_path("baseline").write_text('{"finished": false}', encoding="utf-8")
    with pytest.raises(ValueError, match="still running"):
        tune.reaudit_stage("baseline", 1)
    tune.status_path("baseline").write_text('{"finished": true}', encoding="utf-8")
    tune.reaudit_stage("baseline", 1)
    [reaudited] = tune.read_results("baseline")
    assert "complaints" not in reaudited
    assert all(reaudited[field] == str(row[field]) for field in tune.AUDIT_FIELDS)
    assert reaudited["penalty"] == str(row["penalty"]) and reaudited["assignment"] == row["assignment"]
    [kept] = tune.RESULTS.glob("baseline.csv.*.bak")  # the old file, named by the time of the re-audit
    assert "complaints" in kept.read_text(encoding="utf-8")


def test_compare_cards_prints_both_full_audit_reports(tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch,
                                                       capsys: pytest.CaptureFixture[str]) -> None:
    generated = next(generate.generate(seed, HOURS) for seed in SEEDS if generate.generate(seed, HOURS))
    assert generated is not None
    (tmp_path / "inputs").mkdir()
    generate.write_input(tmp_path / "inputs" / "small.yml", *generated)
    monkeypatch.setattr(tune, "BENCHMARKS", tmp_path)
    monkeypatch.setattr(tune, "RESULTS", tmp_path / "results")
    tune.RESULTS.mkdir()
    row = tune.run_one("trial", tune.DEFAULTS, tune.Benchmark("small", "sweep", False))
    with open(tune.results_path("trial"), "w", encoding="utf-8", newline="") as file:
        writer = csv.DictWriter(file, tune.RESULT_FIELDS)
        writer.writeheader()
        writer.writerows([row, {**row, "setting": "copy"}])
    assert tune.main(["compare", "trial", "defaults", "copy", "--cards", "small"]) == 0
    text = capsys.readouterr().out
    assert text.startswith("=== defaults, on small (first period) ===\n\nfixes searched up to 3 changes")
    assert "=== copy, on small (first period) ===" in text and text.count("events by kind") == 2
    assert tune.main(["compare", "trial", "defaults", "copy"]) == 0
    assert "same schedule under both: small" in capsys.readouterr().out
    assert tune.main(["compare", "trial", "defaults", "copy", "--cards", "missing"]) == 1


def test_a_setting_from_the_command_line_is_named_by_its_parameters_in_field_order() -> None:
    setting = tune.parse_setting("shift_share=0.25, neutral_partner=0.25")
    assert setting == tune.Setting("neutral_partner=0.25,shift_share=0.25", neutral_partner=0.25, shift_share=0.25)
    assert tune.parse_setting("workload_power=3").workload_power == 3
    assert tune.parse_setting("defaults") is tune.DEFAULTS
    for bad in ("", "shift_share", "speed=2", "rest_factor=2.5", "shift_share=0.2,shift_share=0.3", "shift_share=2",
                "workload_power=2.5"):
        with pytest.raises(ValueError):
            tune.parse_setting(bad)


def test_input_groups_split_the_manifest() -> None:
    tuning, holdout, confirm, multiday = (tune.group_inputs(group) for group in tune.INPUT_GROUPS)
    assert tuning and holdout and confirm
    assert all(b.tier == "sweep" and not b.holdout for b in tuning)
    assert all(b.holdout for b in holdout) and all(b.tier == "confirm" for b in confirm)
    assert all(b.tier == "multiday" for b in multiday)
    assert not {b.name for b in tuning} & ({b.name for b in holdout} | {b.name for b in confirm}
                                           | {b.name for b in multiday})


def test_a_round_runs_its_settings_as_its_own_resumable_stage(tmp_path: pathlib.Path,
                                                              monkeypatch: pytest.MonkeyPatch) -> None:
    generated = next(generate.generate(seed, HOURS) for seed in SEEDS if generate.generate(seed, HOURS))
    assert generated is not None
    (tmp_path / "inputs").mkdir()
    generate.write_input(tmp_path / "inputs" / "small.yml", *generated)
    monkeypatch.setattr(tune, "BENCHMARKS", tmp_path)
    monkeypatch.setattr(tune, "RESULTS", tmp_path / "results")
    monkeypatch.setattr(tune, "benchmarks", lambda: [tune.Benchmark("small", "sweep", False)])
    tune.run_round("trial", ["shift_share=0.5"], "tuning", 1)
    tune.run_round("trial", ["shift_share=0.5", "neutral_partner=0.25,shift_share=0.5"], "tuning", 1)  # adds one
    rows = tune.read_results("trial")
    assert [(row["stage"], row["setting"]) for row in rows] == [
        ("trial", "shift_share=0.5"), ("trial", "neutral_partner=0.25,shift_share=0.5")]
    assert all(row["status"] == "done" for row in rows)
    assert "trial" in tune.stages()
    for bad_name in ("baseline", "two words", "../escape"):
        with pytest.raises(ValueError, match="name"):
            tune.run_round(bad_name, ["shift_share=0.5"], "tuning", 1)


@pytest.mark.skipif(not sys.platform.startswith("linux"), reason="forks a parallel search inside the test process")
def test_a_round_run_one_at_a_time_in_parallel_gives_the_same_results(tmp_path: pathlib.Path,
                                                                     monkeypatch: pytest.MonkeyPatch) -> None:
    generated = next(generate.generate(seed, HOURS) for seed in SEEDS if generate.generate(seed, HOURS))
    assert generated is not None
    (tmp_path / "inputs").mkdir()
    generate.write_input(tmp_path / "inputs" / "small.yml", *generated)
    monkeypatch.setattr(tune, "BENCHMARKS", tmp_path)
    monkeypatch.setattr(tune, "RESULTS", tmp_path / "results")
    monkeypatch.setattr(tune, "benchmarks", lambda: [tune.Benchmark("small", "sweep", False)])
    tune.run_round("alone", ["defaults"], "tuning", 1)
    tune.run_round("together", ["defaults"], "tuning", 1, processes=2)
    timing = {"stage", "seconds", "nodes", f"{tune.DAY2}seconds", f"{tune.DAY2}nodes"}
    alone, together = tune.read_results("alone"), tune.read_results("together")
    assert len(alone) == len(together) == 1 and alone[0]["setting"] == "defaults"
    assert ({key: value for key, value in alone[0].items() if key not in timing}
            == {key: value for key, value in together[0].items() if key not in timing})


def test_the_next_period_covers_the_same_hours_right_after_a_period_of_whole_days() -> None:
    # 48 hours: the next period starts where the first ends; 30 hours: two days after the first starts
    first = parse_input({"settings": {"time": ["2025-01-01T08:00", "2025-01-03T08:00"], "min_rest": 6},
                         "workers": [{"name": "Anne", "unavailable": [["2025-01-01T10:00", "2025-01-01T12:00"]]}],
                         "posts": [{"name": "desk", "roles": {"any": 1}, "length": 4}]})
    second = tune.next_period(first, ())
    assert second.settings.period.start == first.settings.period.end
    assert second.workers[0].unavailable[0].start == first.workers[0].unavailable[0].start + dt.timedelta(days=2)
    longer = dataclasses.replace(first, settings=dataclasses.replace(first.settings, period=DateTimeRange(
        first.settings.period.start, first.settings.period.start + dt.timedelta(hours=30))))
    assert tune.next_period(longer, ()).settings.period.start == first.settings.period.start + dt.timedelta(days=2)
