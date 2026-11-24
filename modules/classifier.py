"""Module 1: complaint classification and priority prediction.

TF-IDF features (word + character n-grams, so typos still match) feed a
supervised classifier. A Decision Tree and Logistic Regression are compared;
the best one per task is saved. Predictions below CONFIDENCE_THRESHOLD are
flagged for human review.
"""
import os
import sys
import joblib
import numpy as np
import pandas as pd
from sklearn.compose import ColumnTransformer
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import accuracy_score, classification_report, f1_score
from sklearn.model_selection import GroupShuffleSplit
from sklearn.pipeline import FeatureUnion, Pipeline
from sklearn.tree import DecisionTreeClassifier

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
MODEL_PATH = os.path.join(ROOT, "models", "classifier.joblib")
CONFIDENCE_THRESHOLD = 0.60
PRIORITY_ORDER = ["low", "medium", "high", "critical"]


def make_features():
    return FeatureUnion([
        ("word", TfidfVectorizer(ngram_range=(1, 2), lowercase=True, sublinear_tf=True)),
        ("char", TfidfVectorizer(analyzer="char_wb", ngram_range=(2, 4), lowercase=True, sublinear_tf=True)),
    ])


def candidates():
    return {
        "Logistic Regression": LogisticRegression(max_iter=2000, C=5),
        "Decision Tree": DecisionTreeClassifier(max_depth=25, random_state=0),
    }


CORRECTIONS_PATH = os.path.join(ROOT, "data", "corrections.csv")


def load_training_frame(csv_path=os.path.join(ROOT, "data", "complaints.csv"), corrections_path=CORRECTIONS_PATH):
    """The synthetic complaints plus any officer corrections saved by the dashboard (human in the loop)."""
    df = pd.read_csv(csv_path)
    if os.path.exists(corrections_path):
        extra = pd.read_csv(corrections_path).dropna(subset=["text", "category", "priority"])
        if len(extra):
            extra = extra.assign(complaint_id=range(100000, 100000 + len(extra)), duplicate_of=float("nan"))
            df = pd.concat([df, extra[["complaint_id", "text", "category", "priority", "duplicate_of"]]], ignore_index=True)
            print(f"including {len(extra)} officer corrections in training")
    return df


def split_frame(df):
    """The same train/test split everywhere. A complaint and its duplicates stay on the same side (no leakage)."""
    groups = df["duplicate_of"].fillna(df["complaint_id"]).astype(float)
    tr, te = next(GroupShuffleSplit(n_splits=1, test_size=0.2, random_state=1).split(df, groups=groups))
    return df.iloc[tr], df.iloc[te]


def train(csv_path=os.path.join(ROOT, "data", "complaints.csv"), corrections_path=CORRECTIONS_PATH):
    df = load_training_frame(csv_path, corrections_path)
    train_df, test_df = split_frame(df)
    print(f"train={len(train_df)}  test={len(test_df)}\n")

    best = {}
    for target in ("category", "priority"):
        print(f"=== {target.upper()} ===")
        scores = {}
        for name, model in candidates().items():
            pipe = Pipeline([("features", make_features()), ("clf", model)])
            pipe.fit(train_df["text"], train_df[target])
            pred = pipe.predict(test_df["text"])
            acc, f1 = accuracy_score(test_df[target], pred), f1_score(test_df[target], pred, average="macro")
            scores[name] = (f1, acc, pipe)
            print(f"{name:20s} accuracy={acc:.3f}  macro-F1={f1:.3f}")
        winner = max(scores, key=lambda k: scores[k][0])
        print(f"-> selected: {winner}\n")
        pipe = scores[winner][2]
        print(classification_report(test_df[target], pipe.predict(test_df["text"]), digits=3))
        best[target] = pipe
    joblib.dump(best, MODEL_PATH)
    print(f"saved model to {MODEL_PATH}")
    return best


_models = None

def _load():
    global _models
    if _models is None:
        _models = joblib.load(MODEL_PATH)
    return _models


def predict(text):
    """Return category, priority, their confidences, and whether a human should review."""
    m = _load()
    out = {}
    for target in ("category", "priority"):
        proba = m[target].predict_proba([text])[0] if hasattr(m[target], "predict_proba") else None
        classes = m[target].classes_
        if proba is None:
            out[target], out[f"{target}_conf"] = m[target].predict([text])[0], 1.0
        else:
            i = int(np.argmax(proba))
            out[target], out[f"{target}_conf"] = classes[i], float(proba[i])
    out["needs_review"] = out["category_conf"] < CONFIDENCE_THRESHOLD
    return out


def evaluate_hard_cases(path=os.path.join(ROOT, "tests", "hard_cases.csv")):
    """Hand-written messy complaints the model never saw: a more honest test than synthetic data."""
    df = pd.read_csv(path).fillna("")
    rows = []
    for _, r in df.iterrows():
        p = predict(r["text"])
        rows.append((r, p))
    clear = [(r, p) for r, p in rows if not int(r["vague"])]
    vague = [(r, p) for r, p in rows if int(r["vague"])]
    cat_ok = np.mean([p["category"] == r["category"] for r, p in clear])
    pri_ok = np.mean([p["priority"] == r["priority"] for r, p in clear])
    pri_near = np.mean([abs(PRIORITY_ORDER.index(p["priority"]) - PRIORITY_ORDER.index(r["priority"])) <= 1
                        for r, p in clear])
    flagged = np.mean([p["needs_review"] for r, p in vague])
    print(f"\nHARD CASES ({len(clear)} clear, {len(vague)} vague)")
    print(f"category accuracy: {cat_ok:.2f} | priority exact: {pri_ok:.2f} | priority within one level: {pri_near:.2f}")
    print(f"vague complaints sent to human review: {flagged:.2f}\n")
    for r, p in rows:
        mark = "" if int(r["vague"]) else ("OK " if p["category"] == r["category"] else "XX ")
        print(f"{mark}{r['text'][:58]:58s} -> {p['category']:12s}({p['category_conf']:.2f}) "
              f"{p['priority']:8s} review={p['needs_review']}")


if __name__ == "__main__":
    if "--eval-only" not in sys.argv:
        train()
    evaluate_hard_cases()
