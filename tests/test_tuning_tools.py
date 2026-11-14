"""Tests for the tuning tools: tools/benchmarks/generate.py and tools/tune.py."""
import copy
import csv
import pathlib

import pytest

import tune
from benchmarks import generate
from schedule_checker import hard_constraint_violations
from tinyscheg.csp.problem import build_problem
from tinyscheg.csp.search import find_first_schedule
from tinyscheg.parsing.input_reader import parse_input, read_input
from tinyscheg.scoring.constants import build_constants

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
    def fake_solve(document: dict, limit: float) -> tuple[float, float, int, int] | None:
        return None if len(document["workers"]) % 2 else (1.0, 0.5, 10, 2)
    monkeypatch.setattr(generate, "solve_within", fake_solve)
    tier = generate.Tier("test", (HOURS,), 3, 0, 1.0, generate.STAFFED)
    results = {}
    for jobs in (1, 3):
        monkeypatch.setattr(generate, "INPUTS", tmp_path / str(jobs))
        (tmp_path / str(jobs)).mkdir()
        results[jobs] = generate.build_tier(tier, jobs)
    assert results[1] == results[3]
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


def test_settings_are_ranked_by_the_tuning_priorities() -> None:
    def row(setting: str, easy: float, concentration: float, holdout: str = "False") -> dict[str, str]:
        return {"setting": setting, "status": "done", "holdout": holdout, "easy_fix_severity": str(easy),
                "no_fix_severity": "1", "concentration": str(concentration), "complaints": "3",
                "separate_severity": "0", "seconds": "1"}
    rows = [row("a", 2, 0.1), row("b", 1, 0.9), row("c", 1, 0.5), row("c", 1, 0.5, holdout="True")]
    assert [summary["setting"] for summary in tune.setting_summaries(rows)] == ["c", "b", "a"]
    assert tune.setting_summaries(rows)[0]["inputs"] == 1  # held-back inputs are left out by default
    assert tune.setting_summaries(rows, include_holdout=True)[0]["inputs"] == 2


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


def test_one_run_continues_for_a_second_period(tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch) -> None:
    # day 2: the input continued right after the first period, with the first's schedule as its history; a first
    # period that leaves the second no legal schedule is recorded as such
    generated = next(generate.generate(seed, HOURS) for seed in SEEDS if generate.generate(seed, HOURS))
    assert generated is not None
    (tmp_path / "inputs").mkdir()
    generate.write_input(tmp_path / "inputs" / "small.yml", *generated)
    monkeypatch.setattr(tune, "BENCHMARKS", tmp_path)
    row = tune.run_one("baseline", tune.DEFAULTS, tune.Benchmark("small", "sweep", False))
    assert row["day2_status"] in ("done", "no schedule")
    first = parse_input(generated[0])
    second = tune.next_period(first, tuple(int(worker) for worker in row["assignment"].split()))
    assert second.settings.period.start == first.settings.period.end
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
    # the defaults let three dislikes outweigh an outrage; a heavier workload weight doesn't
    assert not tradeoffs["outrage_outweighs_pairings"]
    heavier = tune.Setting("heavier", workload_weight=0.6)
    assert tune.unit_tradeoffs(heavier)["outrage_outweighs_pairings"]


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
    stale = {**row, "complaints": 999, "easy_fix_severity": 999}  # as if audited by an older audit
    with open(tune.results_path("baseline"), "w", encoding="utf-8", newline="") as file:
        writer = csv.DictWriter(file, tune.RESULT_FIELDS)
        writer.writeheader()
        writer.writerow(stale)
    tune.status_path("baseline").write_text('{"finished": false}', encoding="utf-8")
    with pytest.raises(ValueError, match="still running"):
        tune.reaudit_stage("baseline", 1)
    tune.status_path("baseline").write_text('{"finished": true}', encoding="utf-8")
    tune.reaudit_stage("baseline", 1)
    [reaudited] = tune.read_results("baseline")
    assert reaudited["complaints"] == str(row["complaints"])
    assert reaudited["easy_fix_severity"] == str(row["easy_fix_severity"])
    assert reaudited["penalty"] == str(row["penalty"]) and reaudited["assignment"] == row["assignment"]
    assert tune.results_path("baseline").with_suffix(".csv.bak").exists()


def test_a_setting_from_the_command_line_is_named_by_its_parameters_in_field_order() -> None:
    setting = tune.parse_setting("shift_share=0.25, neutral_partner=0.25")
    assert setting == tune.Setting("neutral_partner=0.25,shift_share=0.25", neutral_partner=0.25, shift_share=0.25)
    assert tune.parse_setting("workload_power=3").workload_power == 3
    for bad in ("", "shift_share", "speed=2", "rest_factor=2.5", "shift_share=0.2,shift_share=0.3", "shift_share=2",
                "workload_power=2.5"):
        with pytest.raises(ValueError):
            tune.parse_setting(bad)


def test_input_groups_split_the_manifest() -> None:
    tuning, holdout, confirm = (tune.group_inputs(group) for group in tune.INPUT_GROUPS)
    assert tuning and holdout and confirm
    assert all(b.tier == "sweep" and not b.holdout for b in tuning)
    assert all(b.holdout for b in holdout) and all(b.tier == "confirm" for b in confirm)
    assert not {b.name for b in tuning} & ({b.name for b in holdout} | {b.name for b in confirm})


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
