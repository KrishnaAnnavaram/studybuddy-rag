"""Reference problems 4-6: per-student isolation, a correct 'you', one summary function, aggregates only."""
import json
from datetime import datetime, timezone

import pytest

from studybuddy_rag.analytics import grade_summary, my_history, purge_old_queries
from studybuddy_rag.auth import PermissionDenied
from studybuddy_rag.providers.fakes import ScriptedLLM
from tests.conftest import login


@pytest.fixture
def graded(app, users):
    db = app.db
    math = db.upsert_course("Mathematics 1", "mathematics")
    art = db.upsert_course("Visual Arts 1", "arts")
    small = db.upsert_course("Seminar", "science")
    grades = {"student_a": ("A", "C"), "student_b": ("B", "A"), "student_c": ("C", "B")}
    for name, (g_math, g_art) in grades.items():
        db.set_grade(users[name].user_id, math, g_math)
        db.set_grade(users[name].user_id, art, g_art)
    db.set_grade(users["student_a"].user_id, small, "B")   # only one student: must stay hidden
    return users


def test_student_only_sees_own_history(app, graded):
    tok_a, tok_b = login(app, "student_a"), login(app, "student_b")
    app.ask(tok_a, "How does photosynthesis work in plants?")
    app.ask(tok_b, "What is a vanishing point in perspective drawing?")
    app.ask(tok_b, "How do I add 1/3 and 1/4?")
    hist_a = my_history(app.db, app.whoami(tok_a))
    assert [h.question for h in hist_a] == ["How does photosynthesis work in plants?"]
    dash_b = app.dashboard(tok_b)
    assert sum(dash_b.questions_by_subject.values()) == 2
    assert "photosynthesis" not in dict(dash_b.top_terms)


def test_dashboard_is_about_the_logged_in_student(app, graded):
    """The prototype labelled the *last student in a loop* as 'You'."""
    dash = app.dashboard(login(app, "student_b"))
    assert dash.student == "Student B"
    assert {(g.course, g.grade) for g in dash.grades} == {("Mathematics 1", "B"), ("Visual Arts 1", "A")}
    assert dash.strongest == ("Visual Arts 1",) and dash.weakest == ("Mathematics 1",)
    assert dash.gpa == 3.5


def test_course_averages_are_k_anonymous(app, graded):
    dash = app.dashboard(login(app, "student_a"))
    assert dash.course_averages == {"Mathematics 1": 3.0, "Visual Arts 1": 3.0}
    assert "Seminar" not in dash.course_averages          # fewer than k=3 students
    assert "Seminar" in {g.course for g in dash.grades}    # but the student still sees their own grade


def test_dashboard_has_no_other_students_fields(app, graded):
    dash = app.dashboard(login(app, "student_a"))
    serialised = json.dumps(dash, default=lambda o: o.__dict__)
    assert "Student B" not in serialised and "Student C" not in serialised


def test_instructor_view_is_aggregate_and_role_gated(app, graded):
    with pytest.raises(PermissionDenied):
        app.instructor_view(login(app, "student_a"))
    view = app.instructor_view(login(app, "teacher"))
    assert view.grade_distribution["Mathematics 1"] == {"A": 1, "B": 1, "C": 1}
    assert view.suppressed_courses == ("Seminar",)


def test_single_summary_function_uses_llm_only_on_own_data(app, graded):
    a = app.whoami(login(app, "student_a"))
    assert "Mathematics 1 (mathematics): A" in grade_summary(app.db, a)
    llm = ScriptedLLM([json.dumps({"summary": "Great work in maths."})])
    assert grade_summary(app.db, a, llm) == "Great work in maths."
    prompt = llm.calls[0]["prompt"]
    assert "Mathematics 1 (mathematics): A" in prompt and "Student B" not in prompt
    assert "Visual Arts 1 (arts): A" not in prompt     # student_b's art grade must not leak


def test_summary_falls_back_when_llm_output_is_bad(app, graded):
    a = app.whoami(login(app, "student_a"))
    assert grade_summary(app.db, a, ScriptedLLM(["not json"])).startswith("Grade point average")


def test_retention_policy_purges_old_logs(app, graded):
    token = login(app, "student_a")
    long_ago = datetime(2020, 1, 1, tzinfo=timezone.utc)
    app.db.insert_query(graded["student_a"].user_id, long_ago, "text", "old question", "science", "llm",
                        "old answer", [], False)
    app.auth.clock = lambda: datetime.now(timezone.utc)
    token = login(app, "student_a")
    app.ask(token, "How does photosynthesis work in plants?")
    assert purge_old_queries(app.db, retention_days=365) == 1
    assert [h.question for h in my_history(app.db, app.whoami(token))] == ["How does photosynthesis work in plants?"]
