"""``studybuddy`` command-line entry point."""
from __future__ import annotations

import argparse
import getpass
import json
import os
import subprocess
import sys
from pathlib import Path

from .analytics import purge_old_queries
from .config import DEFAULT_EVAL_SET, Settings, load_dotenv
from .db import Database
from .evaluate import evaluate, load_eval_set
from .providers import build_embedder, build_llm
from .router import CentroidRouter, LLMRouter
from .seed import seed_demo
from .service import build_app, build_index
from .tutor import Tutor


def _cmd_init(settings: Settings, args: argparse.Namespace) -> int:
    db = Database(settings.db_path)
    created = seed_demo(db, password=args.password or os.environ.get("STUDYBUDDY_DEMO_PASSWORD") or None)
    index = build_index(settings)
    index.save(settings.db_path)
    print(f"database: {settings.db_path}")
    print(f"indexed {len(index)} chunks from {settings.corpus_dir} with {index.embedder.name}")
    if created:
        pw = next(iter(created.values()))
        print(f"demo users: {', '.join(created)} (password: {pw})")
        print("These are synthetic demo accounts. Do not reuse this password anywhere.")
    else:
        print("demo users already exist")
    return 0


def _cmd_ingest(settings: Settings, args: argparse.Namespace) -> int:
    index = build_index(settings)
    index.save(settings.db_path)
    print(f"indexed {len(index)} chunks ({', '.join(sorted(s.value for s in index.subjects()))})")
    return 0


def _cmd_ask(settings: Settings, args: argparse.Namespace) -> int:
    app = build_app(settings)
    password = os.environ.get("STUDYBUDDY_PASSWORD") or getpass.getpass(f"password for {args.user}: ")
    session = app.login(args.user, password)
    try:
        answer = app.ask(session.token, " ".join(args.question))
    finally:
        app.logout(session.token)
    route = answer.route
    if route is not None:
        print(f"[subject: {route.subject.value} via {route.method}, confidence {route.confidence:.2f}]")
    print(answer.text)
    for c in answer.cited:
        print("  " + c.label())
    if not answer.grounded and answer.kind != "greeting":
        print("  (not grounded in the study material)")
    for note in answer.notes:
        print(f"  note: {note}")
    return 0


def _cmd_eval(settings: Settings, args: argparse.Namespace) -> int:
    embedder = build_embedder(settings)
    index = build_index(settings, embedder)
    llm = build_llm(settings)
    centroid = CentroidRouter.from_index(index)
    router = centroid if args.router == "centroid" else LLMRouter(llm, fallback=centroid)
    tutor = Tutor(llm, index, router, top_k=args.k, min_score=settings.min_score)
    report = evaluate(load_eval_set(args.eval_set), router, index, k=args.k, tutor=tutor)
    if args.json:
        print(json.dumps(report.as_dict(), indent=2))
    else:
        print(f"items: {report.n}  router: {args.router}")
        print(f"router accuracy: {report.router_accuracy:.3f}")
        print(f"retrieval recall@{report.k}: {report.recall_at_k:.3f}  MRR: {report.mrr:.3f}")
        print(f"answers with a valid citation: {report.citation_rate}")
        print("confusion (gold -> predicted):", json.dumps(report.confusion))
    return 0


def _cmd_purge(settings: Settings, args: argparse.Namespace) -> int:
    n = purge_old_queries(Database(settings.db_path), settings.log_retention_days)
    print(f"deleted {n} query-log rows older than {settings.log_retention_days} days")
    return 0


def _cmd_ui(settings: Settings, args: argparse.Namespace) -> int:
    app_path = Path(__file__).parent / "app" / "streamlit_app.py"
    extra = list(args.streamlit_args)
    if extra[:1] == ["--"]:
        # `studybuddy ui -- --server.port 8502`: the separator is for argparse. Streamlit would pass
        # everything after a `--` to the script instead of reading it as its own options.
        extra = extra[1:]
    return subprocess.call([sys.executable, "-m", "streamlit", "run", str(app_path), *extra])


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="studybuddy", description="Subject-routed RAG tutor with citations")
    p.add_argument("--env-file", default=".env", help="optional .env file to load (default: .env)")
    sub = p.add_subparsers(dest="command", required=True)

    s = sub.add_parser("init", help="create the demo database, synthetic users and the index")
    s.add_argument("--password", help="demo password (default: STUDYBUDDY_DEMO_PASSWORD or random)")
    s.set_defaults(func=_cmd_init)

    s = sub.add_parser("ingest", help="(re)build the retrieval index from the corpus")
    s.set_defaults(func=_cmd_ingest)

    s = sub.add_parser("ask", help="ask one question as a user (password from STUDYBUDDY_PASSWORD or prompt)")
    s.add_argument("-u", "--user", required=True)
    s.add_argument("question", nargs="+")
    s.set_defaults(func=_cmd_ask)

    s = sub.add_parser("eval", help="router accuracy, retrieval recall@k and citation rate")
    s.add_argument("--eval-set", default=str(DEFAULT_EVAL_SET))
    s.add_argument("--k", type=int, default=4)
    s.add_argument("--router", choices=["llm", "centroid"], default="llm")
    s.add_argument("--json", action="store_true")
    s.set_defaults(func=_cmd_eval)

    s = sub.add_parser("purge-logs", help="apply the query-log retention policy")
    s.set_defaults(func=_cmd_purge)

    s = sub.add_parser("ui", help="launch the Streamlit app (needs the 'ui' extra), e.g. ui -- --server.port 8502")
    s.add_argument("streamlit_args", nargs=argparse.REMAINDER)
    s.set_defaults(func=_cmd_ui)
    return p


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    load_dotenv(args.env_file)
    settings = Settings.from_env()
    try:
        return int(args.func(settings, args) or 0)
    except Exception as exc:  # noqa: BLE001 - print a clean error for CLI users
        print(f"error: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
