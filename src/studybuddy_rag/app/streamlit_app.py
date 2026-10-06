"""Streamlit UI: login, chat (text or browser-recorded voice), personal dashboard, instructor view.

Run with ``studybuddy ui`` (or ``streamlit run src/studybuddy_rag/app/streamlit_app.py``).
Every page resolves the session token through ``StudyBuddy.whoami`` first (session guard), so an
expired or missing session always lands on the login form.
"""
from __future__ import annotations

import streamlit as st

from studybuddy_rag.auth import AuthError, PermissionDenied, Principal
from studybuddy_rag.config import Settings, load_dotenv
from studybuddy_rag.service import StudyBuddy, VoiceDisabled, build_app

TOKEN_KEY = "studybuddy_token"


@st.cache_resource(show_spinner="Loading the study material...")
def get_app() -> StudyBuddy:
    load_dotenv()
    return build_app(Settings.from_env())


def guard(app: StudyBuddy) -> Principal | None:
    token = st.session_state.get(TOKEN_KEY)
    if not token:
        return None
    try:
        return app.whoami(token)
    except AuthError as exc:
        st.session_state.pop(TOKEN_KEY, None)
        st.warning(str(exc))
        return None


def login_form(app: StudyBuddy) -> None:
    st.title("StudyBuddy")
    st.caption("Log in to ask questions and see your own progress.")
    with st.form("login"):
        username = st.text_input("Username")
        password = st.text_input("Password", type="password")
        if st.form_submit_button("Log in"):
            try:
                session = app.login(username, password)
            except AuthError as exc:
                st.error(str(exc))
            else:
                st.session_state[TOKEN_KEY] = session.token
                st.rerun()


def show_answer(answer) -> None:
    with st.chat_message("assistant"):
        st.markdown(answer.text)
        if answer.route is not None:
            st.caption(f"Subject: {answer.route.subject.value} ({answer.route.method}, "
                       f"confidence {answer.route.confidence:.2f})")
        if answer.cited:
            st.markdown("**Sources**")
            for c in answer.cited:
                st.markdown(f"- {c.label()}")
        elif answer.kind == "ungrounded":
            st.info("This answer is not grounded in the study material.")


def chat_page(app: StudyBuddy, principal: Principal) -> None:
    st.header("Ask a question")
    token = st.session_state[TOKEN_KEY]
    if app.speech is not None:
        recorder = getattr(st, "audio_input", None)
        if recorder is not None:
            audio = recorder("Or record your question")
            if audio is not None:
                try:
                    transcript, answer = app.ask_voice(token, audio.getvalue(), mime_type=audio.type or "audio/wav")
                except (VoiceDisabled, ValueError) as exc:
                    st.error(str(exc))
                else:
                    with st.chat_message("user"):
                        st.markdown(f"(voice) {transcript}")
                    show_answer(answer)
    question = st.chat_input("Type your question")
    if question:
        with st.chat_message("user"):
            st.markdown(question)
        try:
            show_answer(app.ask(token, question))
        except AuthError:
            st.session_state.pop(TOKEN_KEY, None)
            st.rerun()


def dashboard_page(app: StudyBuddy, principal: Principal) -> None:
    token = st.session_state[TOKEN_KEY]
    dash = app.dashboard(token)
    st.header(f"My progress - {dash.student}")
    c1, c2, c3 = st.columns(3)
    c1.metric("Grade point average", "-" if dash.gpa is None else f"{dash.gpa:.2f}")
    c2.metric("Questions asked", sum(dash.questions_by_subject.values()))
    c3.metric("Answers with sources", "-" if dash.grounded_rate is None else f"{dash.grounded_rate:.0%}")
    if dash.grades:
        rows = [{"course": g.course, "subject": g.subject, "grade": g.grade, "points": g.points,
                 "course average": dash.course_averages.get(g.course)} for g in dash.grades]
        st.dataframe(rows, hide_index=True)
        st.caption("Course averages appear only when enough students are graded to keep them anonymous.")
        if dash.strongest:
            st.write("Strongest: " + ", ".join(dash.strongest))
        if dash.weakest:
            st.write("Needs practice: " + ", ".join(dash.weakest))
    if dash.questions_by_subject:
        st.subheader("My questions by subject")
        st.bar_chart(dash.questions_by_subject)
    if dash.top_terms:
        st.subheader("Topics I asked about most")
        st.write(", ".join(f"{t} ({n})" for t, n in dash.top_terms))
    if st.toggle("Personalised summary (uses the LLM, only your own grades)"):
        st.write(app.summary(token, use_llm=True))
    if dash.recent:
        st.subheader("Recent questions")
        for item in dash.recent:
            st.markdown(f"- `{item.asked_at}` **{item.question}** ({item.subject}, {item.input_mode})")


def instructor_page(app: StudyBuddy, principal: Principal) -> None:
    st.header("Class overview (aggregates only)")
    try:
        view = app.instructor_view(st.session_state[TOKEN_KEY])
    except PermissionDenied:
        st.error("Instructor access only.")
        return
    for course, dist in view.grade_distribution.items():
        st.subheader(course)
        st.bar_chart({g: dist.get(g, 0) for g in "ABCDF"})
    if view.suppressed_courses:
        st.caption("Hidden (too few students to stay anonymous): " + ", ".join(view.suppressed_courses))
    if view.questions_by_subject:
        st.subheader("Questions by subject")
        st.bar_chart(view.questions_by_subject)


def main() -> None:
    st.set_page_config(page_title="StudyBuddy", layout="wide")
    app = get_app()
    principal = guard(app)
    if principal is None:
        login_form(app)
        return
    st.sidebar.write(f"Signed in as **{principal.display_name}** ({principal.role})")
    pages = ["Chat", "My dashboard"] + (["Class overview"] if principal.is_instructor else [])
    choice = st.sidebar.radio("Go to", pages)
    if st.sidebar.button("Log out"):
        app.logout(st.session_state.pop(TOKEN_KEY, None))
        st.rerun()
    if choice == "Chat":
        chat_page(app, principal)
    elif choice == "My dashboard":
        dashboard_page(app, principal)
    else:
        instructor_page(app, principal)


main()
