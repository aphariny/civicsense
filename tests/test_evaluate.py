"""Tests for the model evaluation. Run:  python tests/test_evaluate.py   (or: pytest tests)"""
import csv
import json
import os
import sys
import tempfile
import warnings
warnings.filterwarnings("ignore")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from modules import evaluate

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
FAST = ["Most common answer (baseline)", "Logistic Regression", "Decision Tree"]
_cache = {}


def result():
    if "r" not in _cache:
        _cache["r"] = evaluate.evaluate(FAST, save=False)
    return _cache["r"]


def test_the_benchmark_file_is_clean_and_big_enough():
    rows = list(csv.DictReader(open(os.path.join(ROOT, "tests", "hard_cases.csv"), encoding="utf-8")))
    clear = [r for r in rows if r["vague"] == "0"]
    assert len(clear) >= 80 and len(rows) - len(clear) >= 6
    assert len({r["text"] for r in rows}) == len(rows)                                   # no duplicate sentences
    for r in clear:
        assert r["category"] in evaluate.TARGETS["category"] and r["priority"] in evaluate.TARGETS["priority"], r
    for target in ("category", "priority"):
        counts = {l: sum(1 for r in clear if r[target] == l) for l in evaluate.TARGETS[target]}
        assert min(counts.values()) >= 10, counts                                           # every class has real examples


def test_confusion_matrices_add_up_to_the_number_of_cases():
    r = result()
    for target, block in r["targets"].items():
        for name in FAST:
            assert sum(map(sum, block["confusion"]["synthetic"][name])) == r["n_test"]
            assert sum(map(sum, block["confusion"]["hard"][name])) == r["n_hard"]
            assert sum(c["support"] for c in block["per_class"][name].values()) == r["n_hard"]


def test_scores_agree_with_the_confusion_matrix():
    r = result()
    block = r["targets"]["category"]
    m = block["confusion"]["hard"]["Logistic Regression"]
    right = sum(m[i][i] for i in range(len(m)))
    assert abs(block["models"]["Logistic Regression"]["hard"]["accuracy"] - right / r["n_hard"]) < 1e-9
    assert len(block["errors"]["Logistic Regression"]) == r["n_hard"] - right                # every mistake is listed


def test_learning_beats_the_do_nothing_baseline_on_both_test_sets():
    r = result()
    for target in ("category", "priority"):
        m = r["targets"][target]["models"]
        assert m["Logistic Regression"]["synthetic"]["accuracy"] > m["Most common answer (baseline)"]["synthetic"]["accuracy"] + 0.2
        assert m["Logistic Regression"]["hard"]["macro_f1"] > m["Most common answer (baseline)"]["hard"]["macro_f1"]


def test_the_easy_test_overstates_how_well_it_will_do_on_real_complaints():
    r = result()["targets"]["category"]["models"]["Logistic Regression"]
    assert r["synthetic"]["accuracy"] - r["hard"]["accuracy"] > 0.10                          # the headline finding, kept honest


def test_review_rates_are_reported():
    review = result()["review"]
    assert 0 <= review["clear_sent_to_review"] <= 1 and 0 <= review["vague_sent_to_review"] <= 1
    assert review["vague_sent_to_review"] > review["clear_sent_to_review"]                    # vague ones are caught more often


def test_the_live_model_is_chosen_like_the_classifier_does():
    r = result()
    for target in ("category", "priority"):
        scores = {n: r["targets"][target]["models"][n]["synthetic"]["macro_f1"] for n in ("Logistic Regression", "Decision Tree")}
        assert r["production"][target] == max(scores, key=scores.get)


def test_results_are_reproducible():
    again = evaluate.evaluate(["Most common answer (baseline)", "Logistic Regression"], save=False)
    r = result()
    for target in ("category", "priority"):
        for name in ("Most common answer (baseline)", "Logistic Regression"):
            assert again["targets"][target]["models"][name]["hard"]["accuracy"] == r["targets"][target]["models"][name]["hard"]["accuracy"]


def test_saving_and_loading_round_trip():
    path = os.path.join(tempfile.mkdtemp(), "eval.json")
    assert evaluate.load_results(path) is None
    saved = evaluate.evaluate(["Most common answer (baseline)", "Logistic Regression"], save=True, out_path=path)
    assert evaluate.load_results(path) == json.loads(json.dumps(saved))


def test_summary_table_is_sorted_and_marks_the_live_model():
    r = result()
    for target in ("category", "priority"):
        table = evaluate.summary_table(r, target)
        assert list(table["hard-case macro-F1"]) == sorted(table["hard-case macro-F1"], reverse=True)
        assert (table["in the live system"] == "yes").sum() == 1
        assert (table["plus or minus"] > 0).all() and (table["plus or minus"] < 0.25).all()
    assert "hard-case within one level" in evaluate.summary_table(r, "priority").columns


def test_the_shipped_results_cover_every_model_and_both_targets():
    saved = evaluate.load_results()
    assert saved is not None, "run: python modules/evaluate.py"
    assert set(saved["targets"]) == {"category", "priority"} and len(saved["targets"]["category"]["models"]) == 7
    assert saved["n_hard"] >= 80 and saved["production"]["category"] in saved["targets"]["category"]["models"]


def test_a_class_a_model_never_predicts_still_gets_a_row():
    per_class = result()["targets"]["category"]["per_class"]["Most common answer (baseline)"]
    assert set(per_class) == set(evaluate.TARGETS["category"]) and any(c["recall"] == 0 for c in per_class.values())


if __name__ == "__main__":
    tests = [(n, f) for n, f in sorted(globals().items()) if n.startswith("test_")]
    failed = 0
    for name, fn in tests:
        try:
            fn(); print("PASS", name)
        except Exception as e:
            failed += 1; print("FAIL", name, type(e).__name__, e)
    print(f"\n{len(tests) - failed}/{len(tests)} passed")
    sys.exit(1 if failed else 0)
