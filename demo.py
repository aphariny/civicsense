"""Module 1 -> Module 2 demo: classify each hard-case complaint, then run the rule engine."""
import pandas as pd
from modules import classifier, rule_engine as eng

LEVELS = eng.LEVELS


def process(text, **ctx):
    ml = classifier.predict(text)
    facts = eng.extract_facts(text, ml["category"], ml["priority"], ml["needs_review"], ctx)
    return ml, eng.run(facts)


if __name__ == "__main__":
    df = pd.read_csv("tests/hard_cases.csv").fillna("")
    clear = df[df["vague"] == 0]
    before = after = within_before = within_after = 0
    for _, r in clear.iterrows():
        ml, res = process(r["text"])
        gold = LEVELS.index(r["priority"])
        before += ml["priority"] == r["priority"]
        after += res["priority"] == r["priority"]
        within_before += abs(LEVELS.index(ml["priority"]) - gold) <= 1
        within_after += abs(res["priority_level"] - gold) <= 1
    n = len(clear)
    print(f"Priority on {n} hard cases (exact):            ML alone {before/n:.2f}  ->  ML + rules {after/n:.2f}")
    print(f"Priority on {n} hard cases (within 1 level):   ML alone {within_before/n:.2f}  ->  ML + rules {within_after/n:.2f}\n")
    for text in ["Open pit dug by cable people not covered, risky for kids",
                 "Transformer making loud noise and smoke coming out",
                 "Pls fix it"]:
        print(f'"{text}"')
        print(eng.explain(process(text)[1]), "\n")
