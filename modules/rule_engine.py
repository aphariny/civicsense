"""Module 2: knowledge-based routing and explanation engine.

An expert system with three parts:
  knowledge base   -> rules/rules.yaml (IF-THEN rules, editable by officials)
  inference engine -> forward chaining (match facts, pick one rule, fire it, repeat)
  explanation      -> a trace listing every rule that fired and what it changed

Conflict resolution: among all applicable rules, the one with the highest
salience fires first; ties go to the more specific rule (more conditions),
then to the rule listed first. Each rule fires at most once.
"""
import os
import re
import yaml

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
RULES_PATH = os.path.join(ROOT, "rules", "rules.yaml")
WARDS_PATH = os.path.join(ROOT, "rules", "wards.yaml")

LEVELS = ["low", "medium", "high", "critical"]
OPS = {
    "eq": lambda a, b: a == b, "ne": lambda a, b: a != b,
    "gt": lambda a, b: a is not None and a > b, "gte": lambda a, b: a is not None and a >= b,
    "lt": lambda a, b: a is not None and a < b, "lte": lambda a, b: a is not None and a <= b,
    "in": lambda a, b: a in b,
}
ACTIONS = {"assert", "set", "min_priority", "raise_priority", "score_boost", "flag"}


# ---------------------------------------------------------------- knowledge base
def _check_condition(cond, rule_id):
    if "any" in cond or "all" in cond:
        key = "any" if "any" in cond else "all"
        for c in cond[key]:
            _check_condition(c, rule_id)
    else:
        if "fact" not in cond or cond.get("op") not in OPS or "value" not in cond:
            raise ValueError(f"Rule {rule_id}: bad condition {cond}. Use fact, op ({', '.join(OPS)}), value.")


def load_rules(path=RULES_PATH):
    with open(path, encoding="utf-8") as f:
        rules = yaml.safe_load(f)["rules"]
    seen = set()
    for r in rules:
        for key in ("id", "name", "salience", "when", "then"):
            if key not in r:
                raise ValueError(f"Rule {r.get('id', '?')} is missing '{key}'")
        if r["id"] in seen:
            raise ValueError(f"Duplicate rule id {r['id']}")
        seen.add(r["id"])
        for c in r["when"]:
            _check_condition(c, r["id"])
        bad = set(r["then"]) - ACTIONS
        if bad:
            raise ValueError(f"Rule {r['id']}: unknown action(s) {sorted(bad)}. Allowed: {sorted(ACTIONS)}")
        for lvl in (r["then"].get("min_priority"),):
            if lvl is not None and lvl not in LEVELS:
                raise ValueError(f"Rule {r['id']}: priority must be one of {LEVELS}")
    return rules


def load_ward_population(path=WARDS_PATH):
    with open(path, encoding="utf-8") as f:
        return {int(k): v for k, v in yaml.safe_load(f)["ward_population"].items()}


# ---------------------------------------------------------------- fact extraction
PATTERNS = {
    "near_school": r"\b(school|college|kindergarten|anganwadi)\b",
    "near_hospital": r"\b(hospital|clinic|dispensary|health cent(?:er|re))\b",
    "hazard_live_electric": r"live wire|wire fell|wires? (?:hanging|down)|spark|exposed (?:cable|wire)|electric line|short circuit|smoke",
    "hazard_open_manhole": r"manhole|drain cover|open pit|uncovered (?:pit|drain)",
    "hazard_structural": r"caved in|sinkhole|collapse",
    "hazard_medical_waste": r"medical waste|syringe|biomedical",
    "hazard_contamination": r"contaminated|sewage mixing|stomach|diarrh|\bill\b|\bsick\b",
    "child_risk": r"\b(child|children|kid|kids|student|students)\b",
}


# Same lists as modules/places.py (a test checks they agree). Kept here so this file also runs on its own.
SCHOOL_TYPES, HOSPITAL_TYPES = {"school"}, {"hospital"}
PUBLIC_PLACE_TYPES = {"market", "bus_stand", "railway_station", "temple", "park"}
# "near the market", "outside the bus stand"... but not a street name such as "at Temple Street"
PUBLIC_PLACE_TEXT = re.compile(
    r"\b(?:near|at|beside|opposite|outside|in front of|next to|behind)\s+(?:the\s+)?(?:local\s+|main\s+|weekly\s+)?"
    r"(?:market|bazaar|bus stand|bus stop|bus station|railway station|temple|park)\b"
    r"(?!\s+(?:street|road|avenue|lane|main|nagar|colony))", re.I)


def extract_facts(text, category, ml_priority, needs_review=False, context=None):
    """Turn a complaint (plus Module 1's output and surrounding context) into facts.

    Places count whether the words mention them ("near the school") or the pin is close to one (context['places_near']).
    """
    ctx = context or {}
    facts = {name: bool(re.search(p, text, re.I)) for name, p in PATTERNS.items()}
    kinds = {p["type"] for p in ctx.get("places_near") or []}
    facts["near_school"] = facts["near_school"] or bool(kinds & SCHOOL_TYPES)
    facts["near_hospital"] = facts["near_hospital"] or bool(kinds & HOSPITAL_TYPES)
    facts["near_public_place"] = bool(PUBLIC_PLACE_TEXT.search(text)) or bool(kinds & PUBLIC_PLACE_TYPES)
    facts.update(
        category=category,
        needs_review=bool(needs_review),
        priority_level=LEVELS.index(ml_priority),
        ml_priority=ml_priority,
        duplicate_count=ctx.get("duplicate_count", 0),
        repeat_count=ctx.get("repeat_count", 0),
        age_days=ctx.get("age_days", 0),
        reopened_count=ctx.get("reopened_count", 0),
        ward_reporting_ratio=ctx.get("ward_reporting_ratio", 1.0),
    )
    return facts


def ward_reporting_ratio(ward, complaints_per_ward, ward_population):
    """Share of all complaints coming from a ward divided by its share of the population.
    Below 1 means the ward complains less than its size suggests."""
    total_c, total_p = sum(complaints_per_ward.values()), sum(ward_population.values())
    if total_c == 0 or ward not in ward_population:
        return 1.0
    return (complaints_per_ward.get(ward, 0) / total_c) / (ward_population[ward] / total_p)


# ---------------------------------------------------------------- inference engine
def _holds(cond, facts):
    if "any" in cond:
        return any(_holds(c, facts) for c in cond["any"])
    if "all" in cond:
        return all(_holds(c, facts) for c in cond["all"])
    return OPS[cond["op"]](facts.get(cond["fact"]), cond["value"])


def _size(cond):  # specificity = number of simple tests in a rule
    if "any" in cond:
        return sum(_size(c) for c in cond["any"])
    if "all" in cond:
        return sum(_size(c) for c in cond["all"])
    return 1


def _fire(rule, memory, state):
    """Apply a rule's actions; return a list of human-readable changes."""
    changes, act = [], rule["then"]
    for fact, value in act.get("assert", {}).items():
        if memory.get(fact) != value:
            memory[fact] = value
            changes.append(f"new fact: {fact} = {value}")
    for field, value in act.get("set", {}).items():
        if field not in state:                       # first (highest-salience) rule wins
            state[field] = value
            changes.append(f"{field} = {value}")
        else:
            changes.append(f"{field} already decided by an earlier rule ({state[field]}); kept")
    if "min_priority" in act:
        new = max(memory["priority_level"], LEVELS.index(act["min_priority"]))
        if new != memory["priority_level"]:
            changes.append(f"priority {LEVELS[memory['priority_level']]} -> {LEVELS[new]}")
            memory["priority_level"] = new
    if "raise_priority" in act:
        new = min(3, memory["priority_level"] + act["raise_priority"])
        if new != memory["priority_level"]:
            changes.append(f"priority {LEVELS[memory['priority_level']]} -> {LEVELS[new]}")
            memory["priority_level"] = new
    if "score_boost" in act:
        state["boost"] = state.get("boost", 0) + act["score_boost"]
        changes.append(f"score +{act['score_boost']}")
    if "flag" in act:
        state.setdefault("flags", []).append(act["flag"])
        changes.append("flag added")
    return changes


def run(facts, rules=None):
    """Forward chaining. Returns department, priority, score, flags and the full trace."""
    rules = rules if rules is not None else load_rules()
    memory, state, trace, fired = dict(facts), {}, [], set()
    order = {r["id"]: i for i, r in enumerate(rules)}
    while True:
        applicable = [r for r in rules if r["id"] not in fired and all(_holds(c, memory) for c in r["when"])]
        if not applicable:
            break
        # conflict resolution: salience, then specificity, then file order
        rule = min(applicable, key=lambda r: (-r["salience"], -sum(_size(c) for c in r["when"]), order[r["id"]]))
        fired.add(rule["id"])
        trace.append({"step": len(trace) + 1, "rule": rule["id"], "name": rule["name"],
                      "why": rule.get("why", ""), "changes": _fire(rule, memory, state)})
    if "department" not in state:
        state["department"] = "Control Room (manual review)"
        state.setdefault("flags", []).append("No routing rule matched: sent to manual review")
    level = memory["priority_level"]
    score = level * 100 + memory.get("duplicate_count", 0) * 3 + memory.get("age_days", 0) * 2 + state.get("boost", 0)
    return {"department": state["department"], "priority": LEVELS[level], "priority_level": level,
            "score": score, "flags": state.get("flags", []), "trace": trace, "facts": memory}


def explain(result):
    """Plain-language explanation for the dashboard's 'why this decision' panel."""
    lines = [f"Department: {result['department']}   Priority: {result['priority'].upper()}   Score: {result['score']}"]
    for t in result["trace"]:
        detail = "; ".join(t["changes"]) if t["changes"] else "no change"
        lines.append(f"  {t['step']}. [{t['rule']}] {t['name']} -- {t['why']} ({detail})")
    for f in result["flags"]:
        lines.append(f"  ! {f}")
    return "\n".join(lines)


if __name__ == "__main__":
    demo = extract_facts("Open manhole near the government school, a child almost fell in",
                         category="Road", ml_priority="medium", context={"duplicate_count": 1})
    print(explain(run(demo)))
