"""Create a demo database with synthetic users and grades (no real people, no real records).

Demo passwords are never stored in the repository: they come from ``STUDYBUDDY_DEMO_PASSWORD`` or
are generated randomly and printed once.
"""
from __future__ import annotations

import random
import secrets

from .auth import AuthService
from .db import Database

DEMO_STUDENTS = [("student_a", "Student A"), ("student_b", "Student B"), ("student_c", "Student C"),
                 ("student_d", "Student D")]
DEMO_INSTRUCTOR = ("instructor_demo", "Demo Instructor")
DEMO_COURSES = [("Mathematics 1", "mathematics"), ("Science 1", "science"), ("Visual Arts 1", "arts"),
                ("Music 1", "arts")]


def seed_demo(db: Database, *, password: str | None = None, seed: int = 7) -> dict[str, str]:
    """Insert demo users, courses and grades. Returns ``{username: password}`` (same password for all).

    Idempotent for users: existing usernames are skipped.
    """
    password = password or secrets.token_urlsafe(9)
    auth = AuthService(db)
    rng = random.Random(seed)
    course_ids = [db.upsert_course(name, subject) for name, subject in DEMO_COURSES]
    created: dict[str, str] = {}
    for username, display in DEMO_STUDENTS:
        if db.user_by_username(username) is not None:
            continue
        principal = auth.register(username, password, role="student", display_name=display)
        created[username] = password
        for cid in course_ids:
            db.set_grade(principal.user_id, cid, rng.choices("ABCDF", weights=[4, 4, 3, 1, 1])[0])
    username, display = DEMO_INSTRUCTOR
    if db.user_by_username(username) is None:
        auth.register(username, password, role="instructor", display_name=display)
        created[username] = password
    return created
