"""Command-line interface for Scholar Watch."""

import argparse
import logging
import os
import sys
from logging.handlers import RotatingFileHandler
from pathlib import Path

from .config import load_config, load_server_config
from .database import get_session, init_db, reset_engine


def setup_logging(verbose: bool = False, log_dir: str | None = None) -> None:
    level = logging.DEBUG if verbose else logging.INFO
    fmt = "%(asctime)s [%(levelname)s] %(name)s: %(message)s"
    datefmt = "%Y-%m-%d %H:%M:%S"

    handlers: list[logging.Handler] = [logging.StreamHandler()]

    # File logging: defaults to <project>/logs/scholar_watch.log
    if log_dir is None:
        log_dir = os.path.join(Path(__file__).resolve().parent.parent, "logs")
    Path(log_dir).mkdir(parents=True, exist_ok=True)
    file_handler = RotatingFileHandler(
        os.path.join(log_dir, "scholar_watch.log"),
        maxBytes=5 * 1024 * 1024,  # 5 MB
        backupCount=5,
    )
    file_handler.setLevel(logging.DEBUG)
    handlers.append(file_handler)

    logging.basicConfig(level=level, format=fmt, datefmt=datefmt, handlers=handlers)


def cmd_init_db(args: argparse.Namespace) -> None:
    """Create database tables."""
    config = load_config(args.config)
    init_db(config)
    print(f"Database initialized: {config.database.uri}")


def cmd_add_researcher(args: argparse.Namespace) -> None:
    """Add a researcher to track."""
    from .models import Researcher

    config = load_config(args.config)
    init_db(config)
    session = get_session(config)

    try:
        existing = session.query(Researcher).filter(
            Researcher.scholar_id == args.scholar_id
        ).first()
        if existing:
            print(f"Researcher '{args.scholar_id}' already exists: {existing.name}")
            return

        researcher = Researcher(
            scholar_id=args.scholar_id,
            name=args.name or args.scholar_id,
        )
        session.add(researcher)
        session.commit()
        print(f"Added researcher: {researcher.name} ({researcher.scholar_id})")
    finally:
        session.close()


def cmd_list_researchers(args: argparse.Namespace) -> None:
    """List all tracked researchers."""
    from .models import Researcher

    config = load_config(args.config)
    init_db(config)
    session = get_session(config)

    try:
        researchers = session.query(Researcher).all()
        if not researchers:
            print("No researchers tracked.")
            return

        print(f"{'Scholar ID':<20} {'Name':<30} {'Active':<8} {'Last Scraped':<20}")
        print("-" * 78)
        for r in researchers:
            last = r.last_scraped_at.strftime("%Y-%m-%d %H:%M") if r.last_scraped_at else "Never"
            active = "Yes" if r.is_active else "No"
            print(f"{r.scholar_id:<20} {r.name:<30} {active:<8} {last:<20}")
    finally:
        session.close()


def cmd_scrape(args: argparse.Namespace) -> None:
    """Run a scrape of Google Scholar."""
    from .scraper import ScholarScraper

    config = load_config(args.config)
    init_db(config)
    session = get_session(config)

    try:
        scraper = ScholarScraper(config, session)

        if args.researcher:
            run = scraper.scrape_one(args.researcher)
        else:
            run = scraper.scrape_all()

        print(f"Scrape run #{run.id}: {run.status}")
        print(f"  Researchers scraped: {run.researchers_scraped}")
        print(f"  Publications found: {run.publications_found}")
        if run.error_message:
            print(f"  Error: {run.error_message}")
    finally:
        session.close()


def cmd_metrics(args: argparse.Namespace) -> None:
    """Print computed metrics for a researcher."""
    from .metrics import MetricsCalculator

    config = load_config(args.config)
    init_db(config)
    session = get_session(config)

    try:
        calc = MetricsCalculator(session)
        metrics = calc.compute(args.scholar_id)

        if not metrics:
            print(f"No data found for '{args.scholar_id}'")
            sys.exit(1)

        print(f"Metrics for {metrics.name} ({metrics.scholar_id})")
        print("=" * 60)
        print(f"  Total Citations:      {metrics.total_citations}")
        print(f"  h-index:              {metrics.h_index}")
        print(f"  i10-index:            {metrics.i10_index}")
        print(f"  Publications:         {metrics.num_publications}")
        print(f"  Citation Velocity:    {metrics.citation_velocity:.4f} cites/day")
        print(f"  Citation Acceleration:{metrics.citation_acceleration:.4f}")
        print(f"  Citation Half-Life:   {metrics.citation_half_life or 'N/A'} years")

        if metrics.trending_papers:
            print(f"\n  Trending Papers (top {len(metrics.trending_papers)}):")
            for i, p in enumerate(metrics.trending_papers, 1):
                print(f"    {i}. [{p.current_citations} cites, +{p.velocity:.3f}/day] {p.title[:70]}")

        if metrics.declining_papers:
            print(f"\n  Declining Papers ({len(metrics.declining_papers)}):")
            for i, p in enumerate(metrics.declining_papers[:5], 1):
                print(f"    {i}. [{p.current_citations} cites, {p.citation_delta}] {p.title[:70]}")
    finally:
        session.close()


def cmd_report(args: argparse.Namespace) -> None:
    """Generate and send an email report."""
    from .email_report import send_report

    config = load_config(args.config)
    init_db(config)
    session = get_session(config)

    try:
        success = send_report(config, session)
        if success:
            print("Report sent successfully.")
        else:
            print("Report not sent (check config or logs).")
            sys.exit(1)
    finally:
        session.close()


def cmd_create_user(args: argparse.Namespace) -> None:
    """Create a user account."""
    import getpass
    from .auth import hash_password
    from .models import User

    config = load_config(args.config)
    init_db(config)
    session = get_session(config)

    try:
        email = args.email.strip().lower()
        existing = session.query(User).filter(User.email == email).first()
        if existing:
            print(f"User with email '{email}' already exists.")
            sys.exit(1)

        if args.password:
            password = args.password
        else:
            password = getpass.getpass("Password: ")
            confirm = getpass.getpass("Confirm password: ")
            if password != confirm:
                print("Passwords do not match.")
                sys.exit(1)

        if len(password) < 8:
            print("Password must be at least 8 characters.")
            sys.exit(1)

        user = User(
            email=email,
            display_name=args.name or email.split("@")[0],
            password_hash=hash_password(password),
        )
        session.add(user)
        session.commit()
        print(f"Created user: {user.display_name} ({user.email})")
    finally:
        session.close()


def cmd_dashboard(args: argparse.Namespace) -> None:
    """Launch the web dashboard."""
    from .dashboard import create_app

    config = load_config(args.config)
    server_config = load_server_config()
    host = args.host or server_config.host
    port = args.port or server_config.port

    app = create_app(config, server_config)
    print(f"Starting dashboard at http://{host}:{port}")
    app.run(host=host, port=port, debug=args.debug)


def main() -> None:
    parser = argparse.ArgumentParser(
        prog="scholar-watch",
        description="Track citation performance of researchers on Google Scholar",
    )
    parser.add_argument("-c", "--config", help="Path to config YAML file")
    parser.add_argument("-v", "--verbose", action="store_true", help="Enable debug logging")

    subparsers = parser.add_subparsers(dest="command", help="Available commands")

    # init-db
    subparsers.add_parser("init-db", help="Create database tables")

    # add-researcher
    add_p = subparsers.add_parser("add-researcher", help="Add a researcher to track")
    add_p.add_argument("scholar_id", help="Google Scholar ID")
    add_p.add_argument("--name", "-n", help="Display name")

    # list-researchers
    subparsers.add_parser("list-researchers", help="List all tracked researchers")

    # scrape
    scrape_p = subparsers.add_parser("scrape", help="Scrape Google Scholar data")
    scrape_p.add_argument("--researcher", "-r", help="Scrape only this Scholar ID")

    # metrics
    metrics_p = subparsers.add_parser("metrics", help="Print metrics for a researcher")
    metrics_p.add_argument("scholar_id", help="Google Scholar ID")

    # report
    subparsers.add_parser("report", help="Generate and send email report")

    # create-user
    user_p = subparsers.add_parser("create-user", help="Create a user account")
    user_p.add_argument("email", help="User email address")
    user_p.add_argument("--name", "-n", help="Display name")
    user_p.add_argument("--password", "-p", help="Password (omit to prompt)")

    # dashboard
    dash_p = subparsers.add_parser("dashboard", help="Launch web dashboard")
    dash_p.add_argument("--host", help="Host to bind to")
    dash_p.add_argument("--port", type=int, help="Port to bind to")
    dash_p.add_argument("--debug", action="store_true", help="Enable debug mode")

    args = parser.parse_args()
    setup_logging(args.verbose)

    if not args.command:
        parser.print_help()
        sys.exit(1)

    # Reset engine for each CLI invocation (clean state)
    reset_engine()

    commands = {
        "init-db": cmd_init_db,
        "add-researcher": cmd_add_researcher,
        "list-researchers": cmd_list_researchers,
        "scrape": cmd_scrape,
        "metrics": cmd_metrics,
        "report": cmd_report,
        "create-user": cmd_create_user,
        "dashboard": cmd_dashboard,
    }

    cmd_func = commands.get(args.command)
    if cmd_func:
        cmd_func(args)
    else:
        parser.print_help()
        sys.exit(1)


if __name__ == "__main__":
    main()
