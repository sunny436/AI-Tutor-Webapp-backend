"""The practice record's rules (app/progress/practice.py), on hand-computed values and no database:
Bayesian knowledge tracing per concept, what counts as evidence, the revision ladder and its cap
for a weak topic, the order of revisions, and the day's plan."""

import uuid
from datetime import UTC, date, datetime, timedelta

from app.learning.context import PlanProfile
from app.progress import practice
from app.progress.practice import Answer, Record, Topic

TODAY = date(2026, 10, 22)
RECALLED, LAPSED = (3, 4), (2, 4)  # a review day's (right, answered): 75% is recalled


def ist(moment: str) -> datetime:
    """A moment in India time."""
    return datetime.fromisoformat(moment + "+05:30").astimezone(UTC)


def answer(question: str, right: bool, moment: str, topic: str = "T1", concept: str = "alpha", revised=False):
    return Answer(uuid.uuid4(), question, topic, concept, right, "A" if right else "B", ist(moment), revised)


def topic(topic_id: str, subject: str = "science", chapter: str = "SCI-CH01") -> Topic:
    return Topic(
        topic_id, 1, f"Topic {topic_id}", chapter, 1, f"Chapter {chapter}", "b", "Book", subject, 10, "english"
    )


# ------------------------------------------------------------------- mastery
def test_bkt_gives_the_hand_computed_estimates():
    # Right from the prior 0.2: 0.2 * 0.9 / (0.18 + 0.8 * 0.25) = 0.4737, then learning: + 0.5263 * 0.15 = 0.5526.
    estimate, estimates = practice.PRIOR, []
    for _ in range(3):
        estimate = practice.bkt(estimate, True)
        estimates.append(round(estimate, 3))
    assert estimates == [0.553, 0.844, 0.958]
    # Wrong from the prior: 0.02 / (0.02 + 0.8 * 0.75) = 0.0323, then + 0.9677 * 0.15 = 0.1774.
    assert round(practice.bkt(practice.PRIOR, False), 3) == 0.177


def test_a_concept_is_mastered_only_with_enough_answers_and_questions():
    def concept(*answers):
        return practice.concepts(list(answers))[("T1", "alpha")]

    three = concept(*(answer(f"Q{n}", True, f"2026-10-0{n}T10:00") for n in (1, 2, 3)))
    assert practice.concept_state(three, servable=5) == "mastered"  # 0.958, 3 answers, 3 questions
    one_question = concept(*(answer("Q1", True, f"2026-10-0{n}T10:00") for n in (1, 2, 3)))
    assert practice.concept_state(one_question, servable=5) == "learning"  # the same question 3 times
    assert practice.concept_state(one_question, servable=1) == "mastered"  # the only one the concept has
    assert practice.concept_state(concept(answer("Q1", False, "2026-10-01T10:00")), servable=5) == "weak"
    assert practice.concept_state(concept(answer("Q1", True, "2026-10-01T10:00")), servable=5) == "not_enough_evidence"


def test_only_the_first_answer_to_a_question_on_an_india_day_is_evidence():
    late = answer("Q1", True, "2026-10-20T23:59")
    again = answer("Q1", False, "2026-10-20T23:59:30")  # the same India day: not evidence again
    next_day = answer("Q1", False, "2026-10-21T00:00")  # a new India day
    edited = answer("Q2", True, "2026-10-21T09:00", revised=True)  # its question was edited since
    assert (late.day, next_day.day) == (date(2026, 10, 20), date(2026, 10, 21))
    assert practice.counted([next_day, edited, again, late]) == [late, next_day]


# ------------------------------------------------------------------ revision
def test_the_revision_ladder_grows_with_each_recalled_day_and_restarts_after_a_lapse():
    assert [practice.interval([RECALLED] * days, weak=False) for days in range(1, 8)] == [1, 3, 7, 14, 30, 60, 60]
    assert practice.interval([RECALLED, RECALLED, LAPSED], weak=False) == 1
    assert practice.interval([RECALLED, LAPSED, RECALLED, RECALLED], weak=False) == 3
    assert practice.interval([RECALLED] * 5, weak=True) == 3  # a weak topic comes back within 3 days
    assert practice.recall(7, 7) == 1 / (1 + 7 / 63)  # 0.9 on the day it is due


def test_revisions_overdue_and_due_come_first_most_at_risk_first():
    def reviewed(topic_id: str, *days: date):  # every day recalled
        return practice.review(topic_id, dict.fromkeys(days, RECALLED), TODAY, weak=False)

    items = [
        reviewed("upcoming", date(2026, 10, 20), date(2026, 10, 21)),  # 3 days after 10-21: 10-24
        reviewed("due", date(2026, 10, 21)),  # 1 day after: today
        reviewed("done", date(2026, 10, 21), TODAY),  # due today and reviewed today
        reviewed("a little overdue", date(2026, 10, 15), date(2026, 10, 16)),  # due 10-19; recall (1 + 6/27)^-1
        reviewed("long overdue", date(2026, 10, 10)),  # due 10-11; recall (1 + 12/9)^-1
    ]
    ordered = sorted(items, key=lambda item: practice.revision_order(item, None))
    assert [(item.topic_id, item.state) for item in ordered] == [
        ("long overdue", "overdue"),
        ("a little overdue", "overdue"),
        ("due", "due"),
        ("done", "done"),
        ("upcoming", "upcoming"),
    ]
    assert [round(item.recall, 4) for item in ordered[:2]] == [0.4286, 0.8182]
    assert (ordered[0].due, ordered[-1].due) == (date(2026, 10, 11), date(2026, 10, 24))


def test_answers_on_one_day_are_one_review_and_no_answers_are_no_revision():
    four = [answer(f"Q{n}", True, f"2026-10-21T{9 + n:02d}:00") for n in range(4)]
    [item] = practice.schedule(four, TODAY)
    assert (item.reviews, item.interval, item.due, item.state) == (1, 1, TODAY, "due")
    assert practice.schedule([], TODAY) == []
    [first] = practice.schedule([answer("Q1", False, "2026-10-22T08:00")], TODAY)  # first practised today
    assert (first.state, first.due) == ("upcoming", date(2026, 10, 23))


# ---------------------------------------------------------------------- plan
def record() -> Record:
    """10 answers. R: recalled on 10-19, due 10-20 (2 days overdue). D: recalled yesterday, due today.
    W: recalled on 10-20 and 10-21 (next review 10-24), but its concept beta was missed yesterday: weak."""
    answers = [
        answer("R1", True, "2026-10-19T10:00", topic="R"),
        answer("D1", True, "2026-10-21T10:00", topic="D"),
        *(answer(f"WA{n}", True, "2026-10-20T10:00", topic="W") for n in (1, 2, 3)),
        answer("WB1", True, "2026-10-20T10:05", topic="W", concept="beta"),
        *(answer(f"WA{n}", True, "2026-10-21T10:00", topic="W") for n in (4, 5, 6)),
        answer("WB2", False, "2026-10-21T10:05", topic="W", concept="beta"),
    ]
    topics = {topic_id: topic(topic_id) for topic_id in ("R", "D", "W")}
    concepts = {(topic_id, tag): ("An objective.", 3) for topic_id in topics for tag in ("alpha", "beta")}
    return Record(answers, topics, concepts)


BANK = [
    topic("M1", "mathematics", "MAT-CH01"),
    *(topic(t) for t in ("R", "D", "W", "S1")),
    topic("S2", chapter="SCI-CH02"),
]
STUDENT = PlanProfile(class_level=10, subjects=("science", "mathematics"))


def tasks(plan: dict) -> list[tuple[str, str, str]]:
    return [(task["kind"], task["reason"], task["topic_id"]) for task in plan["tasks"]]


def test_the_plan_revises_strengthens_then_starts_new_topics_within_the_budget():
    plan = practice.build_plan(record(), STUDENT, BANK, TODAY)
    assert (plan["budget_minutes"], plan["budget_source"], plan["needs_profile"]) == (30, "default", False)
    assert tasks(plan) == [("revise", "overdue", "R"), ("revise", "due", "D"), ("strengthen", "weak_concept", "W")]
    assert plan["tasks"][0]["overdue_days"] == 2 and plan["tasks"][2]["concept_tag"] == "beta"
    assert not plan["insufficient_history"] and plan["summary"]["answered"] == 10
    hour = practice.build_plan(record(), PlanProfile(10, subjects=STUDENT.subjects, daily_minutes_goal=60), BANK, TODAY)
    assert tasks(hour) == [
        ("revise", "overdue", "R"),
        ("revise", "due", "D"),
        ("strengthen", "weak_concept", "W"),
        ("learn", "next_topic", "S1"),  # science first, in the chapter already begun
        ("learn", "next_topic", "M1"),
    ]
    many = Record([answer(f"Q{n}", True, "2026-10-19T10:00", topic=f"T{n}") for n in range(8)], {}, {})
    many.topics.update({f"T{n}": topic(f"T{n}") for n in range(8)})
    all_day = practice.build_plan(many, PlanProfile(10, daily_minutes_goal=720), BANK, TODAY)
    assert [task["kind"] for task in all_day["tasks"]] == ["revise"] * 6  # 8 overdue, at most 6 tasks
    assert hour["tasks"][3]["prompt"] == (
        'Test me on Class 10 Science (Book) Chapter 1 "Chapter SCI-CH01", topic "Topic S1": 5 questions.'
    )
    assert hour["tasks"][0]["prompt"].startswith('Help me revise Class 10 Science (Book) Chapter 1 "Chapter SCI-CH01"')
    assert practice.build_plan(record(), STUDENT, BANK, TODAY) == plan  # the same input, the same plan


def test_the_plan_holds_all_day_and_marks_what_was_done_today():
    morning = practice.build_plan(record(), STUDENT, BANK, TODAY)
    practised = record()
    practised.answers.extend(answer(f"R{n}", n != 2, f"2026-10-22T1{n}:00", topic="R") for n in range(1, 6))
    evening = practice.build_plan(practised, STUDENT, BANK, TODAY)
    assert tasks(evening) == tasks(morning) and evening["answered_today"] == 5
    assert (evening["tasks"][0]["answered_today"], evening["tasks"][0]["done"]) == (5, True)
    assert not evening["tasks"][1]["done"]


def test_near_the_exam_the_plan_starts_fewer_new_topics():
    def learn_tasks(days: int) -> int:
        exam = PlanProfile(10, subjects=STUDENT.subjects, daily_minutes_goal=60, exam_date=TODAY + timedelta(days=days))
        plan = practice.build_plan(record(), exam, BANK, TODAY)
        assert plan["days_to_exam"] == days
        return sum(task["kind"] == "learn" for task in plan["tasks"])

    assert [learn_tasks(days) for days in (31, 30, 8, 7, 0)] == [2, 1, 1, 0, 0]


def test_without_a_class_or_a_subject_in_the_bank_the_plan_says_so():
    no_class = practice.build_plan(record(), PlanProfile(), [], TODAY)
    assert no_class["needs_profile"] and all(task["kind"] != "learn" for task in no_class["tasks"])
    other_subject = practice.build_plan(Record([], {}, {}), PlanProfile(10, subjects=("history",)), BANK, TODAY)
    assert other_subject["needs_profile"] and other_subject["insufficient_history"]
    assert tasks(other_subject) == [("learn", "start_here", "M1"), ("learn", "start_here", "R")]
    assert other_subject["summary"]["answered"] == 0
