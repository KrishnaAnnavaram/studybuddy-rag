"""Reference problem 3: hashed passwords, a session guard, logout and expiry."""
import pytest

from studybuddy_rag.auth import AuthError, hash_password, verify_password
from tests.conftest import PASSWORD, login


def test_password_hash_is_salted_and_verifiable():
    h1, h2 = hash_password(PASSWORD), hash_password(PASSWORD)
    assert h1 != h2 and PASSWORD not in h1 and h1.startswith("scrypt$")
    assert verify_password(PASSWORD, h1)
    assert not verify_password("wrong-password", h1)
    assert not verify_password(PASSWORD, "garbage")


def test_short_passwords_are_rejected():
    with pytest.raises(ValueError):
        hash_password("short")


def test_database_never_stores_plaintext(app, users):
    rows = app.db.conn.execute("SELECT password_hash FROM users").fetchall()
    assert rows and all(PASSWORD not in r[0] for r in rows)


def test_login_failures_do_not_reveal_which_part_was_wrong(app, users):
    with pytest.raises(AuthError) as e1:
        app.login("student_a", "not-the-password")
    with pytest.raises(AuthError) as e2:
        app.login("nobody", PASSWORD)
    assert str(e1.value) == str(e2.value)


def test_every_action_requires_a_valid_session(app, users):
    for call in (lambda: app.ask(None, "hi there friend"), lambda: app.dashboard("forged-token"),
                 lambda: app.summary(""), lambda: app.ask_voice(None, b"TEXT:hello")):
        with pytest.raises(AuthError):
            call()


def test_session_expires_and_logout_revokes(app, users, clock):
    token = login(app, "student_a")
    assert app.whoami(token).username == "student_a"
    clock.advance(minutes=61)
    with pytest.raises(AuthError, match="expired"):
        app.whoami(token)
    token = login(app, "student_a")
    app.logout(token)
    with pytest.raises(AuthError):
        app.whoami(token)


def test_only_token_hashes_are_stored(app, users):
    token = login(app, "student_a")
    stored = [r[0] for r in app.db.conn.execute("SELECT token_hash FROM sessions")]
    assert token not in stored and len(stored) == 1
