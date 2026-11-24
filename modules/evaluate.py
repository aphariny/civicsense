"""Honest evaluation of the complaint classifier.

Six models are trained on the synthetic complaints and tested twice:
  * on a held-out part of the synthetic data (easy: it was made from the same templates), and
  * on hand-written 'hard cases' (tests/hard_cases.csv): typos, shorthand, Tanglish, unusual wording.
A 'most common answer' baseline shows what no learning at all would score. Results go to models/evaluation.json,
which the officer dashboard displays.   Run:  python modules/evaluate.py
"""
import json
import os
import sys
import time
import warnings
import datetime as dt

import numpy as np
import pandas as pd
from sklearn.dummy import DummyClassifier
from sklearn.ensemble import RandomForestClassifier
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import accuracy_score, confusion_matrix, f1_score, precision_recall_fscore_support
from sklearn.naive_bayes import MultinomialNB
from sklearn.neural_network import MLPClassifier
from sklearn.pipeline import Pipeline
from sklearn.svm import LinearSVC
from sklearn.tree import DecisionTreeClassifier

try:
    from modules import classifier
except ImportError:                                  # when run directly: python modules/evaluate.py
    import classifier

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
HARD_PATH = os.path.join(ROOT, "tests", "hard_cases.csv")
OUT_PATH = os.path.join(ROOT, "models", "evaluation.json")
TARGETS = {"category": ["Drainage", "Electricity", "Road", "Sanitation", "Water Supply"],
           "priority": ["low", "medium", "high", "critical"]}


def candidate_models():
    """name -> a fresh, untrained classifier. 'production' ones are the two the live system chooses between."""
    return {
        "Most common answer (baseline)": DummyClassifier(strategy="most_frequent"),
        "Logistic Regression": classifier.candidates()["Logistic Regression"],
        "Decision Tree": classifier.candidates()["Decision Tree"],
        "Linear SVM": LinearSVC(C=1.0, random_state=0),
        "Naive Bayes": MultinomialNB(alpha=0.1),
        "Random Forest": RandomForestClassifier(n_estimators=150, random_state=0, n_jobs=1),
        "Neural network (MLP)": MLPClassifier(hidden_layer_sizes=(64,), max_iter=300, random_state=0),
    }


def _scores(y_true, y_pred, labels, target):
    out = {"accuracy": float(accuracy_score(y_true, y_pred)),
           "macro_f1": float(f1_score(y_true, y_pred, labels=labels, average="macro", zero_division=0))}
    if target == "priority":                                    # a near miss is better than a far miss
        order = {l: i for i, l in enumerate(labels)}
        out["within_one"] = float(np.mean([abs(order[a] - order[b]) <= 1 for a, b in zip(y_true, y_pred)]))
    return out


def _per_class(y_true, y_pred, labels):
    p, r, f, s = precision_recall_fscore_support(y_true, y_pred, labels=labels, zero_division=0)
    return {l: {"precision": float(p[i]), "recall": float(r[i]), "f1": float(f[i]), "support": int(s[i])} for i, l in enumerate(labels)}


def evaluate(model_names=None, save=True, hard_path=HARD_PATH, out_path=OUT_PATH):
    """Train and test the models. model_names limits which ones run (default: all). Returns the results dict."""
    warnings.filterwarnings("ignore")
    df = classifier.load_training_frame()
    train_df, test_df = classifier.split_frame(df)
    hard = pd.read_csv(hard_path).fillna("")
    clear, vague = hard[hard["vague"].astype(int) == 0], hard[hard["vague"].astype(int) == 1]
    models = candidate_models()
    if model_names:
        models = {k: v for k, v in models.items() if k in model_names}
    results = {"generated_at": dt.datetime.now().isoformat(timespec="seconds"), "n_train": len(train_df), "n_test": len(test_df),
               "n_hard": len(clear), "n_vague": len(vague), "targets": {}, "production": {}, "review": {}}
    for target, labels in TARGETS.items():
        block = {"labels": labels, "models": {}, "confusion": {"synthetic": {}, "hard": {}}, "per_class": {}, "errors": {}}
        winners = {}
        for name, model in models.items():
            started = time.time()
            pipe = Pipeline([("features", classifier.make_features()), ("clf", model)]).fit(train_df["text"], train_df[target])
            syn_pred, hard_pred = pipe.predict(test_df["text"]), pipe.predict(clear["text"])
            block["models"][name] = {"synthetic": _scores(test_df[target], syn_pred, labels, target),
                                     "hard": _scores(clear[target], hard_pred, labels, target), "seconds": round(time.time() - started, 1)}
            block["confusion"]["synthetic"][name] = confusion_matrix(test_df[target], syn_pred, labels=labels).tolist()
            block["confusion"]["hard"][name] = confusion_matrix(clear[target], hard_pred, labels=labels).tolist()
            block["per_class"][name] = _per_class(clear[target], hard_pred, labels)
            block["errors"][name] = [{"text": t, "true": a, "predicted": b}
                                     for t, a, b in zip(clear["text"], clear[target], hard_pred) if a != b][:60]
            if name in ("Logistic Regression", "Decision Tree"):
                winners[name] = block["models"][name]["synthetic"]["macro_f1"]
            if name == "Logistic Regression":
                proba = pipe.predict_proba
                conf_clear = proba(clear["text"]).max(axis=1)
                conf_vague = proba(vague["text"]).max(axis=1) if len(vague) else np.array([])
                if target == "category":
                    results["review"] = {"threshold": classifier.CONFIDENCE_THRESHOLD,
                                         "vague_sent_to_review": float(np.mean(conf_vague < classifier.CONFIDENCE_THRESHOLD)) if len(vague) else None,
                                         "clear_sent_to_review": float(np.mean(conf_clear < classifier.CONFIDENCE_THRESHOLD))}
        # the live system picks the better of its two candidates by synthetic macro-F1 (see classifier.train)
        results["production"][target] = max(winners, key=winners.get) if winners else None
        results["targets"][target] = block
    if save:
        with open(out_path, "w", encoding="utf-8") as f:
            json.dump(results, f, indent=1)
    return results


def load_results(path=OUT_PATH):
    """The last saved evaluation, or None if it has not been run yet."""
    if not os.path.exists(path):
        return None
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def summary_table(results, target):
    """One row per model, best on the hard cases first, as a DataFrame for display."""
    rows = []
    for name, m in results["targets"][target]["models"].items():
        acc = m["hard"]["accuracy"]
        row = {"model": name, "synthetic accuracy": m["synthetic"]["accuracy"], "hard-case accuracy": acc,
               "plus or minus": 1.96 * (acc * (1 - acc) / results["n_hard"]) ** 0.5,        # 95% range: few cases, so be careful
               "hard-case macro-F1": m["hard"]["macro_f1"], "seconds": m["seconds"]}
        if target == "priority":
            row["hard-case within one level"] = m["hard"]["within_one"]
        row["in the live system"] = "yes" if name == results["production"][target] else ""
        rows.append(row)
    return pd.DataFrame(rows).sort_values("hard-case macro-F1", ascending=False).reset_index(drop=True)


if __name__ == "__main__":
    res = evaluate()
    for target in TARGETS:
        print(f"\n=== {target} ({res['n_test']} synthetic test, {res['n_hard']} hard cases) ===")
        print(summary_table(res, target).round(3).to_string(index=False))
    print("\nreview:", res["review"])
    print(f"saved to {OUT_PATH}")
