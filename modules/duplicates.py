"""Module 1 (part 2): duplicate complaint detection.

Two complaints are duplicates when their text is similar (TF-IDF + cosine
similarity) AND they were reported within a small distance of each other.
"""
import os
import numpy as np
import pandas as pd
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.metrics.pairwise import cosine_similarity

try:
    from modules.geo import haversine_m          # when imported from the project root
except ImportError:                              # when run directly: python modules/duplicates.py
    from geo import haversine_m

TEXT_THRESHOLD = 0.40     # tuned on synthetic data: precision 0.90, recall 0.84 (see __main__)
DISTANCE_METRES = 100


class DuplicateDetector:
    def __init__(self, text_threshold=TEXT_THRESHOLD, distance_m=DISTANCE_METRES):
        self.text_threshold, self.distance_m = text_threshold, distance_m
        self.vectorizer = TfidfVectorizer(ngram_range=(1, 2), stop_words="english", sublinear_tf=True)

    def fit(self, texts):
        self.vectorizer.fit(texts)
        return self

    def find_all(self, text, lat, lon, complaints):
        """Every earlier complaint that is a duplicate of this one, best match first, as (id, similarity).

        complaints: DataFrame with complaint_id, text, lat, lon.
        """
        if complaints.empty:
            return []
        sims = cosine_similarity(self.vectorizer.transform([text]),
                                 self.vectorizer.transform(complaints["text"]))[0]
        found = []
        for sim, row in zip(sims, complaints.itertuples()):
            if sim >= self.text_threshold and haversine_m(lat, lon, row.lat, row.lon) <= self.distance_m:
                found.append((int(row.complaint_id), float(sim)))
        return sorted(found, key=lambda m: -m[1])

    def find(self, text, lat, lon, open_complaints):
        """Return (complaint_id, similarity) of the best matching complaint, or None."""
        found = self.find_all(text, lat, lon, open_complaints)
        return found[0] if found else None


def evaluate(csv_path, thresholds=(0.2, 0.3, 0.35, 0.4, 0.5, 0.6)):
    """Replay the dataset in order: each complaint is checked against all earlier ones."""
    df = pd.read_csv(csv_path)
    root = df["duplicate_of"].fillna(df["complaint_id"]).astype(float)
    truth = {int(i): int(g) for i, g in zip(df["complaint_id"], root)}
    texts = df["text"].tolist()
    print(f"{'text thr':>8} {'precision':>10} {'recall':>8}")
    for thr in thresholds:
        det = DuplicateDetector(text_threshold=thr).fit(texts)
        tp = fp = fn = 0
        for idx in range(len(df)):
            row = df.iloc[idx]
            match = det.find(row["text"], row["lat"], row["lon"], df.iloc[:idx])
            is_dup = truth[int(row["complaint_id"])] != int(row["complaint_id"])
            if match and truth[match[0]] == truth[int(row["complaint_id"])]:
                tp += 1
            elif match:
                fp += 1
                if is_dup:
                    fn += 1
            elif is_dup:
                fn += 1
        p = tp / (tp + fp) if tp + fp else 0
        r = tp / (tp + fn) if tp + fn else 0
        print(f"{thr:>8} {p:>10.3f} {r:>8.3f}")


if __name__ == "__main__":
    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    evaluate(os.path.join(root, "data", "complaints.csv"))
