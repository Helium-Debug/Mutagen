"""
MUTAGEN CLI — Terminal-first interface.

Built with Typer + Rich for a polished developer experience.
Enforces authentication, user-specific isolation, programmatic unified diffs,
and complete evolution reports.
"""

from __future__ import annotations

import difflib
import json
import sys
from pathlib import Path
from typing import Optional

import typer
from rich.progress import Progress, SpinnerColumn, TextColumn

from mutagen import __version__
from mutagen.cli.display import (
    console, err_console, print_banner, print_success, print_error,
    print_warning, print_info, print_key_value, print_json_output,
    print_status, create_results_table, confirm_action, format_improvement,
    print_diff, print_evolution_report,
)
from mutagen.config import get_settings, reset_settings, MutagenSettings
from mutagen.core.auth import CredentialsManager
from mutagen.exceptions import MutagenAuthenticationError, MutagenError, MutagenValidationError
from mutagen.schemas import OptimizationObjective, ProgrammingLanguage
from mutagen.services import (
    AuthService, AnalysisService, ProjectService, ExperimentService,
    ExportService, CertificateService, DiffService, ApplyService,
    get_ai_provider,
)

# ── App Setup ────────────────────────────────────────────────
app = typer.Typer(
    name="mutagen",
    help="MUTAGEN — The Experimental Evolution Engine for Code",
    no_args_is_help=True,
    rich_markup_mode="rich",
    pretty_exceptions_enable=True,
    pretty_exceptions_show_locals=False,
)


def app_entry():
    """Entry point for the mutagen CLI."""
    try:
        app()
    except MutagenError as e:
        print_error(str(e))
        raise SystemExit(e.exit_code)
    except KeyboardInterrupt:
        print_warning("\nOperation cancelled.")
        raise SystemExit(1)


# ── Authentication Enforcement ───────────────────────────────

def require_auth() -> dict:
    """
    Ensure the CLI user is authenticated before executing protected operations.

    Stops execution before analyzing source code, calling AI, or creating experiments.
    """
    creds = CredentialsManager.load()
    if not creds or not creds.get("access_token"):
        console.print("\n[bold red]Authentication required.[/bold red]\n")
        console.print("Please log in before analyzing, testing, or optimizing code.\n")
        console.print("Run:\n    [bold bright_cyan]mutagen login[/bold bright_cyan]\n")
        console.print("If the user has no account, run:\n    [bold bright_cyan]mutagen register[/bold bright_cyan]\n")
        raise typer.Exit(code=1)

    auth_svc = AuthService()
    try:
        user = auth_svc.get_current_user_from_token(creds["access_token"])
        return user
    except MutagenAuthenticationError:
        # Attempt transparent refresh if refresh token is available
        if creds.get("refresh_token"):
            try:
                tokens = auth_svc.refresh(creds["refresh_token"])
                user = auth_svc.get_current_user_from_token(tokens["access_token"])
                CredentialsManager.save(
                    user_id=user["id"],
                    username=user["username"],
                    email=user["email"],
                    access_token=tokens["access_token"],
                    refresh_token=tokens.get("refresh_token"),
                )
                return user
            except Exception:
                pass

        console.print("\n[bold red]Authentication required.[/bold red]\n")
        console.print("Please log in before analyzing, testing, or optimizing code.\n")
        console.print("Run:\n    [bold bright_cyan]mutagen login[/bold bright_cyan]\n")
        console.print("If the user has no account, run:\n    [bold bright_cyan]mutagen register[/bold bright_cyan]\n")
        raise typer.Exit(code=1)


# ── Account & Authentication Commands ────────────────────────

@app.command("register")
def register(
    username: Optional[str] = typer.Option(None, "--username", "-u", help="Username"),
    email: Optional[str] = typer.Option(None, "--email", "-e", help="Email address"),
    password: Optional[str] = typer.Option(None, "--password", "-p", help="Password"),
):
    """Create a new individual MUTAGEN user account."""
    print_banner()
    u = username or typer.prompt("Username")
    e = email or typer.prompt("Email address")
    p = password or typer.prompt("Password", hide_input=True)
    confirm = p if password else typer.prompt("Confirm password", hide_input=True)

    auth_svc = AuthService()
    try:
        user = auth_svc.register(username=u, email=e, password=p, password_confirm=confirm)
        print_success(f"Account '{user['username']}' registered successfully.")

        # Automatically log in and save credentials
        tokens = auth_svc.login(username_or_email=u, password=p)
        CredentialsManager.save(
            user_id=user["id"],
            username=user["username"],
            email=user["email"],
            access_token=tokens["access_token"],
            refresh_token=tokens.get("refresh_token"),
        )
        print_info("Session credentials stored securely.")
    except MutagenValidationError as err:
        print_error(str(err))
        raise typer.Exit(code=1)


@app.command("login")
def login(
    username: Optional[str] = typer.Option(None, "--username", "-u", help="Username or email"),
    identifier: Optional[str] = typer.Option(None, "--identifier", "-i", help="Username or email"),
    password: Optional[str] = typer.Option(None, "--password", "-p", help="Password"),
):
    """Authenticate with your MUTAGEN account and start a session."""
    print_banner()
    ident = username or identifier or typer.prompt("Username or Email")
    pwd = password or typer.prompt("Password", hide_input=True)

    auth_svc = AuthService()
    try:
        tokens = auth_svc.login(username_or_email=ident, password=pwd)
        user = tokens["user"]
        CredentialsManager.save(
            user_id=user["id"],
            username=user["username"],
            email=user["email"],
            access_token=tokens["access_token"],
            refresh_token=tokens.get("refresh_token"),
        )
        print_success(f"Welcome back, {user['username']}! Session active.")
    except MutagenAuthenticationError as err:
        print_error(str(err))
        raise typer.Exit(code=1)


@app.command("logout")
def logout():
    """End the current MUTAGEN session and revoke local tokens."""
    print_banner()
    creds = CredentialsManager.load()
    if creds:
        auth_svc = AuthService()
        auth_svc.logout(raw_refresh_token=creds.get("refresh_token"), user_id=creds.get("user_id"))
        CredentialsManager.clear()
        print_success("Successfully logged out. Local session credentials removed.")
    else:
        print_info("No active session found.")


@app.command("whoami")
def whoami():
    """Display information about the currently authenticated user."""
    user = require_auth()
    print_banner()
    console.print("[bold bright_cyan]Active User Session[/]\n")
    print_key_value("Username", user["username"])
    print_key_value("Email", user["email"])
    print_key_value("User ID", user["id"])


@app.command("account")
def account():
    """Display detailed user account status and resource usage."""
    user = require_auth()
    print_banner()
    console.print(f"[bold bright_cyan]User Account: {user['username']}[/]\n")
    print_key_value("User ID", user["id"])
    print_key_value("Username", user["username"])
    print_key_value("Email", user["email"])
    print_key_value("Status", "Active" if user.get("is_active", True) else "Inactive")
    if user.get("created_at"):
        print_key_value("Created", str(user["created_at"])[:19])

    proj_svc = ProjectService()
    projects = proj_svc.list_projects(user_id=user["id"])
    exp_svc = ExperimentService()
    experiments = exp_svc.list_experiments(user_id=user["id"])

    print_key_value("Total Projects", len(projects))
    print_key_value("Total Experiments", len(experiments))


# ── Top-level Commands ───────────────────────────────────────

@app.command()
def version():
    """Show MUTAGEN version."""
    print_banner()
    print_key_value("Version", __version__)


@app.command()
def init(
    force: bool = typer.Option(False, "--force", "-f", help="Overwrite existing configuration"),
):
    """Initialize MUTAGEN configuration in the current directory."""
    print_banner()
    env_file = Path(".env")

    if env_file.exists() and not force:
        print_warning(".env file already exists. Use --force to overwrite.")
        raise typer.Exit(code=2)

    example = Path(__file__).parent.parent.parent.parent / ".env.example"
    if example.exists():
        content = example.read_text()
    else:
        content = _default_env_content()

    env_file.write_text(content)
    print_success("Created .env configuration file")
    print_info("Edit .env to set your GROQ_API_KEY, GEMINI_API_KEY, and database settings")
    print_info("Run 'mutagen doctor' to check your setup")


@app.command()
def doctor():
    """Check MUTAGEN dependencies and configuration status."""
    print_banner()
    err_console.print("[bold]Checking MUTAGEN configuration...[/]\n")

    checks = []

    py_ver = f"{sys.version_info.major}.{sys.version_info.minor}.{sys.version_info.micro}"
    py_ok = sys.version_info >= (3, 10)
    checks.append(("Python version", py_ver, py_ok))
    checks.append(("MUTAGEN package", __version__, True))

    settings = get_settings()

    # AI Provider
    ai_ok = settings.ai_configured()
    ai_desc = f"{settings.ai_provider.value} ({settings.ai_model})"
    if not ai_ok:
        ai_desc += " [missing API key]"
    checks.append(("AI Provider", ai_desc, ai_ok))

    # Database
    from mutagen.db.session import check_database_connection
    db_ok, db_msg = check_database_connection()
    checks.append(("Database", db_msg, db_ok))

    # Docker Sandbox
    from mutagen.sandbox.docker_manager import DockerSandbox
    sandbox = DockerSandbox()
    docker_ok, docker_msg = sandbox.check_availability()
    checks.append(("Docker", docker_msg, docker_ok))

    # Artifact directory
    art_ok = settings.artifact_dir.exists()
    checks.append(("Artifact dir", str(settings.artifact_dir), art_ok))

    table = create_results_table("Dependency Status")
    table.add_column("Component", style="bold")
    table.add_column("Status")
    table.add_column("Result")

    for name, desc, ok in checks:
        status_text = "[mutagen.status.valid]✓ OK[/]" if ok else "[mutagen.status.failed]✗ FAIL[/]"
        table.add_row(name, str(desc), status_text)

    err_console.print(table)
    err_console.print()

    all_ok = all(ok for _, _, ok in checks)
    if all_ok:
        print_success("All checks passed!")
    else:
        failed = [name for name, _, ok in checks if not ok]
        print_warning(f"Issues found: {', '.join(failed)}")
        print_info("Some features may be unavailable. Fix issues and run 'mutagen doctor' again.")


# ── Config Commands ──────────────────────────────────────────

config_app = typer.Typer(name="config", help="Configuration management")
app.add_typer(config_app)


@config_app.command("show")
def config_show(
    format: str = typer.Option("text", "--format", "-f", help="Output format: text or json"),
):
    """Show current configuration (secrets redacted). Requires authentication."""
    user = require_auth()
    settings = get_settings()

    config_data = {
        "user": user["username"],
        "ai_provider": settings.ai_provider.value,
        "ai_model": settings.ai_model,
        "ai_configured": settings.ai_configured(),
        "database_url": _redact_url(settings.database_url),
        "redis_url": _redact_url(settings.redis_url),
        "log_level": settings.log_level.value,
        "artifact_dir": str(settings.artifact_dir),
        "max_generations": settings.max_generations,
        "population_size": settings.population_size,
        "benchmark_repetitions": settings.benchmark_repetitions,
        "execution_timeout": settings.execution_timeout,
        "memory_limit_mb": settings.memory_limit,
        "max_source_size": settings.max_source_size,
        "sandbox_image": settings.sandbox_image,
        "sandbox_network_disabled": settings.sandbox_network_disabled,
    }

    if format == "json":
        print_json_output(config_data)
    else:
        err_console.print(f"[bold]MUTAGEN Configuration (Account: {user['username']})[/]\n")
        for key, value in config_data.items():
            print_key_value(key, value)


@config_app.command("validate")
def config_validate():
    """Validate the current configuration."""
    require_auth()
    try:
        settings = get_settings()
        print_success("Configuration is valid")
        print_key_value("Provider", settings.ai_provider.value)
        print_key_value("Model", settings.ai_model)
        print_key_value("AI configured", settings.ai_configured())
    except Exception as e:
        print_error(f"Configuration validation failed: {e}")
        raise typer.Exit(code=2)


# ── Protected Operations: Analyze, Test, Evaluate, Optimize ──

@app.command()
def analyze(
    file_path: str = typer.Argument(..., help="Path to source file to analyze"),
    verbose: bool = typer.Option(False, "--verbose", "-v", help="Show detailed analysis"),
    format: str = typer.Option("text", "--format", "-f", help="Output format: text or json"),
):
    """Analyze a source code file. Authentication required."""
    user = require_auth()

    try:
        service = AnalysisService()
        analysis = service.analyze_file(file_path)
    except MutagenError as e:
        print_error(str(e))
        raise typer.Exit(code=e.exit_code)

    if format == "json":
        print_json_output(analysis.model_dump())
        return

    print_banner()
    err_console.print(f"[bold]Analysis: {file_path} (User: {user['username']})[/]\n")

    print_key_value("Language", analysis.language.value)
    print_key_value("Source hash", analysis.source_hash[:16] + "...")
    print_key_value("Syntax valid", "✓" if analysis.syntax_valid else "✗")

    if analysis.syntax_errors:
        for err in analysis.syntax_errors:
            print_error(f"  {err}")

    err_console.print()
    err_console.print("[bold bright_cyan]Complexity & Structure[/]")
    print_key_value("Total lines", analysis.lines_total)
    print_key_value("Code lines", analysis.lines_code)
    print_key_value("Comment lines", analysis.lines_comment)
    print_key_value("Blank lines", analysis.lines_blank)
    print_key_value("Cyclomatic Complexity", f"{analysis.complexity_score:.1f}")
    print_key_value("Estimated Time Complexity", analysis.estimated_time_complexity)
    print_key_value("Estimated Space Complexity", analysis.estimated_space_complexity)
    print_key_value("Max Loop Nesting Depth", str(analysis.max_loop_depth))

    # Real-Time Resource & Runtime Metrics
    if analysis.runtime_seconds is not None or analysis.memory_peak_mb is not None:
        err_console.print()
        err_console.print("[bold bright_cyan]Real-Time Resource & Execution Profile[/]")
        if analysis.runtime_seconds is not None:
            print_key_value("Wall Execution Time", f"{analysis.runtime_seconds * 1000:.2f} ms ({analysis.runtime_seconds:.4f}s)")
        if analysis.cpu_time_seconds is not None:
            print_key_value("CPU Time (User+Sys)", f"{analysis.cpu_time_seconds * 1000:.2f} ms ({analysis.cpu_time_seconds:.4f}s)")
        if analysis.memory_peak_mb is not None:
            print_key_value("Peak Memory Usage (RAM)", f"{analysis.memory_peak_mb:.3f} MB ({analysis.memory_peak_mb * 1024:.1f} KB)")

    if analysis.functions:
        err_console.print(f"\n[bold]Functions ({len(analysis.functions)}):[/]")
        for func in analysis.functions:
            complexity = f" (complexity: {func.complexity})" if verbose else ""
            async_label = "async " if func.is_async else ""
            err_console.print(
                f"  {async_label}{func.name}({', '.join(func.args)})"
                f" @ line {func.lineno}{complexity}"
            )

    if analysis.classes:
        err_console.print(f"\n[bold]Classes ({len(analysis.classes)}):[/]")
        for cls in analysis.classes:
            bases = f"({', '.join(cls.bases)})" if cls.bases else ""
            err_console.print(f"  {cls.name}{bases} @ line {cls.lineno}")
            if verbose:
                for method in cls.methods:
                    err_console.print(f"    .{method.name}()")

    if analysis.public_interface:
        err_console.print(f"\n[bold]Public Interface:[/]")
        err_console.print(f"  {', '.join(analysis.public_interface)}")

    print_success("Analysis complete")


@app.command("test")
def test_command(
    target: str = typer.Argument(..., help="Path to project or source file to test"),
):
    """Run tests against code under isolated sandbox conditions. Authentication required."""
    user = require_auth()
    path = Path(target).resolve()
    if not path.exists():
        print_error(f"File or directory not found: {path}")
        raise typer.Exit(code=2)

    print_banner()
    err_console.print(f"[bold]Testing target: {path.name} (User: {user['username']})[/]\n")

    content = path.read_text(encoding="utf-8") if path.is_file() else ""
    from mutagen.sandbox.docker_manager import DockerSandbox
    from mutagen.testing.test_runner import TestRunner

    sandbox = DockerSandbox()
    runner = TestRunner(sandbox)
    result = runner.run_tests("baseline", content)

    if result.all_passed:
        print_success(f"All tests PASSED in {result.duration_seconds:.3f}s")
    else:
        print_error(f"Tests FAILED: {result.failed} failed, {result.errors} errors")
        if result.failure_summaries:
            err_console.print()
            for summary in result.failure_summaries:
                err_console.print(f"[bold red]Failure Details:[/]\n{summary.strip()}")


@app.command("evaluate")
def evaluate(
    target: str = typer.Argument(..., help="Path to source file or project to evaluate"),
    objective: str = typer.Option("balanced", "--objective", "-o", help="Optimization objective: speed, memory, balanced"),
    generations: int = typer.Option(1, "--generations", "-g", help="Generations to evaluate"),
    population: int = typer.Option(4, "--population", "-p", help="Population size"),
    format: str = typer.Option("text", "--format", "-f", help="Output format: text or json"),
):
    """
    Evaluate code through mutation and benchmarking, displaying the complete code change report directly in terminal.
    Authentication required.
    """
    user = require_auth()
    _run_evolution_with_report(
        target=target,
        user=user,
        objective=objective,
        generations=generations,
        population=population,
        format_type=format,
        command_label="EVALUATION",
    )


@app.command("optimize")
def optimize(
    target: str = typer.Argument(..., help="Path to source file or project to optimize"),
    objective: str = typer.Option("balanced", "--objective", "-o", help="Optimization objective: speed, memory, balanced"),
    generations: int = typer.Option(3, "--generations", "-g", help="Number of generations to evolve"),
    population: int = typer.Option(4, "--population", "-p", help="Candidates per generation"),
    format: str = typer.Option("text", "--format", "-f", help="Output format: text or json"),
):
    """
    Optimize code and clearly display the complete code changes and diff in the terminal.
    Authentication required.
    """
    user = require_auth()
    _run_evolution_with_report(
        target=target,
        user=user,
        objective=objective,
        generations=generations,
        population=population,
        format_type=format,
        command_label="OPTIMIZATION",
    )


def _run_evolution_with_report(
    target: str,
    user: dict,
    objective: str,
    generations: int,
    population: int,
    format_type: str,
    command_label: str,
):
    """Internal runner for evaluate/optimize with unified report display."""
    from mutagen.analysis.language_detector import detect_language
    from mutagen.evolution.engine import EvolutionEngine
    from mutagen.schemas import ExperimentConfig

    settings = get_settings()

    try:
        obj = OptimizationObjective(objective)
    except ValueError:
        print_error(f"Invalid objective: {objective}. Use: speed, memory, balanced")
        raise typer.Exit(code=2)

    path = Path(target).resolve()
    if not path.exists():
        print_error(f"Target not found: {path}")
        raise typer.Exit(code=2)

    language = detect_language(path)
    settings.require_ai()
    provider = get_ai_provider()

    print_banner()
    err_console.print(f"[bold]Starting {command_label}: {path.name} (User: {user['username']})[/]\n")

    config = ExperimentConfig(
        source_file=str(path),
        user_id=user["id"],
        language=language,
        objective=obj,
        generations=generations,
        population_size=population,
        benchmark_repetitions=settings.benchmark_repetitions,
        execution_timeout=settings.execution_timeout,
        memory_limit_mb=settings.memory_limit,
    )

    def progress_callback(stage: str, message: str):
        err_console.print(f"  [dim]›[/] {message}")

    engine = EvolutionEngine(
        ai_provider=provider,
        config=config,
        progress_callback=progress_callback,
    )

    summary = engine.run()

    exp_svc = ExperimentService()
    results = exp_svc.get_experiment_results(summary.experiment_id, user_id=user["id"])
    if not results:
        print_error("Failed to retrieve experiment outcome.")
        raise typer.Exit(code=1)

    best_cand = results.get("best_candidate")
    candidates = results.get("candidates", [])
    target_cand = best_cand or (candidates[0] if candidates else None)

    if not target_cand:
        print_warning("No candidates were generated.")
        return

    diff_report = exp_svc.get_candidate_diff(target_cand["id"], user_id=user["id"])

    if format_type == "json":
        print_json_output({
            "experiment": summary.model_dump(),
            "report": diff_report,
        })
        return

    # Print full terminal evolution report with unified diff
    print_evolution_report(diff_report)


@app.command()
def evolve(
    file_path: str = typer.Argument(..., help="Path to source file to evolve"),
    generations: int = typer.Option(None, "--generations", "-g", help="Number of generations"),
    population: int = typer.Option(None, "--population", "-p", help="Population size per generation"),
    objective: str = typer.Option("balanced", "--objective", "-o", help="Optimization objective: speed, memory, balanced"),
    dry_run: bool = typer.Option(False, "--dry-run", help="Show what would be done without executing"),
    format: str = typer.Option("text", "--format", "-f", help="Output format: text or json"),
    test_command: Optional[str] = typer.Option(None, "--test-cmd", help="Test command to run"),
):
    """Evolve a source file through AI-powered mutation and selection. Authentication required."""
    user = require_auth()
    from mutagen.analysis.language_detector import detect_language
    from mutagen.evolution.engine import EvolutionEngine
    from mutagen.schemas import ExperimentConfig

    settings = get_settings()

    try:
        obj = OptimizationObjective(objective)
    except ValueError:
        print_error(f"Invalid objective: {objective}. Use: speed, memory, balanced")
        raise typer.Exit(code=2)

    path = Path(file_path).resolve()
    if not path.exists():
        print_error(f"File not found: {path}")
        raise typer.Exit(code=2)

    language = detect_language(path)

    config = ExperimentConfig(
        source_file=str(path),
        user_id=user["id"],
        language=language,
        objective=obj,
        generations=generations or settings.max_generations,
        population_size=population or settings.population_size,
        benchmark_repetitions=settings.benchmark_repetitions,
        execution_timeout=settings.execution_timeout,
        memory_limit_mb=settings.memory_limit,
        test_command=test_command,
        dry_run=dry_run,
    )

    if dry_run:
        print_banner()
        err_console.print(f"[bold]Dry Run — Evolution Configuration (User: {user['username']})[/]\n")
        for key, value in config.model_dump().items():
            print_key_value(key, value)
        print_info("No experiment will be executed in dry-run mode.")
        return

    settings.require_ai()
    provider = get_ai_provider()
    print_banner()

    def progress_callback(stage: str, message: str):
        err_console.print(f"  [dim]›[/] {message}")

    engine = EvolutionEngine(
        ai_provider=provider,
        config=config,
        progress_callback=progress_callback,
    )
    summary = engine.run()

    if format == "json":
        print_json_output(summary.model_dump())
        return

    err_console.print()
    err_console.print("[bold]Experiment Results[/]\n")
    print_key_value("Experiment ID", summary.experiment_id)
    print_key_value("Status", summary.status.value.upper())
    print_key_value("Generations", f"{summary.generations_completed}/{summary.generations_total}")
    print_key_value("Candidates tested", summary.total_candidates)
    print_key_value("Eligible candidates", summary.valid_candidates)

    if summary.best_candidate_id:
        print_key_value("Best candidate", summary.best_candidate_id)
    if summary.best_improvement_percent is not None:
        imp = format_improvement(summary.best_improvement_percent)
        print_key_value("Best improvement", imp)

    if summary.status.value == "succeeded":
        print_success("Evolution succeeded! Use 'mutagen apply' to inspect and apply optimized code.")


# ── Top-level Diff, Show, History, Apply, Export-Patch ───────

@app.command("diff")
def diff_cmd(
    experiment_id: str = typer.Argument(..., help="Experiment ID"),
    candidate_id: Optional[str] = typer.Option(None, "--candidate", "-c", help="Specific candidate ID"),
    file_path: Optional[str] = typer.Option(None, "--file", "-f", help="Filter by file path"),
    context: int = typer.Option(3, "--context", help="Number of context lines"),
    output: Optional[str] = typer.Option(None, "--output", "-o", help="Save diff to a patch file"),
):
    """View programmatic unified diff for an experiment candidate. Authentication required."""
    user = require_auth()
    exp_svc = ExperimentService()
    exp = exp_svc.get_experiment(experiment_id, user_id=user["id"])
    if not exp:
        print_error(f"Experiment '{experiment_id}' not found.")
        raise typer.Exit(code=2)

    cid = candidate_id or exp.get("best_candidate_id")
    if not cid:
        print_error(f"No candidate found for experiment '{experiment_id}'.")
        raise typer.Exit(code=2)

    diff_data = exp_svc.get_candidate_diff(cid, user_id=user["id"], context=context)
    if not diff_data:
        print_error(f"Diff for candidate '{cid}' not found.")
        raise typer.Exit(code=2)

    diff_text = diff_data["diff_text"]
    if output:
        DiffService.export_patch_file(diff_text, output)
        print_success(f"Patch saved to: {output}")
        return

    console.print(f"\n[bold bright_cyan]MUTAGEN DIFF — Experiment {experiment_id} (Candidate {cid[:8]})[/]\n")
    print_diff(diff_text)


@app.command("show")
def show_cmd(
    experiment_id: str = typer.Argument(..., help="Experiment ID"),
    candidate_id: Optional[str] = typer.Option(None, "--candidate", "-c", help="Specific candidate ID"),
    original: bool = typer.Option(False, "--original", help="Show original source code"),
):
    """Show complete original or candidate source code with syntax highlighting. Authentication required."""
    user = require_auth()
    exp_svc = ExperimentService()
    exp = exp_svc.get_experiment(experiment_id, user_id=user["id"])
    if not exp:
        print_error(f"Experiment '{experiment_id}' not found.")
        raise typer.Exit(code=2)

    from rich.syntax import Syntax
    if original:
        console.print(f"\n[bold bright_cyan]Original Source Code ({exp['source_file']}):[/]\n")
        syntax = Syntax(exp["source_content"], exp.get("language", "python"), theme="monokai", line_numbers=True)
        console.print(syntax)
        return

    cid = candidate_id or exp.get("best_candidate_id")
    if not cid:
        print_error(f"No candidate found for experiment '{experiment_id}'.")
        raise typer.Exit(code=2)

    cand = exp_svc.get_candidate(cid, user_id=user["id"])
    if not cand:
        print_error(f"Candidate '{cid}' not found.")
        raise typer.Exit(code=2)

    console.print(f"\n[bold bright_cyan]Candidate Code — {cid} (Strategy: {cand.get('strategy', 'general')}):[/]\n")
    syntax = Syntax(cand.get("source_code", ""), exp.get("language", "python"), theme="monokai", line_numbers=True)
    console.print(syntax)


@app.command("history")
def history_cmd(
    limit: int = typer.Option(20, "--limit", "-l", help="Number of experiments to list"),
):
    """View experiment history for current user. Authentication required."""
    user = require_auth()
    exp_svc = ExperimentService()
    experiments = exp_svc.list_experiments(user_id=user["id"])

    table = create_results_table(f"Evolution History — {user['username']}")
    table.add_column("Experiment ID", style="bright_cyan")
    table.add_column("Source File", style="white")
    table.add_column("Status", style="bold")
    table.add_column("Generations", justify="center")
    table.add_column("Candidates", justify="right")
    table.add_column("Improvement", justify="right")
    table.add_column("Created", style="dim")

    for e in experiments[:limit]:
        table.add_row(
            e["id"],
            e["source_file"],
            e["status"].upper(),
            e["generations"],
            str(e["candidates"]),
            str(e["best_improvement"]),
            str(e["created_at"])[:19],
        )

    console.print(table)


@app.command("results")
def results_cmd(
    experiment_id: str = typer.Argument(..., help="Experiment ID"),
    format: str = typer.Option("text", "--format", "-f", help="Output format: text or json"),
):
    """View detailed results for an experiment. Authentication required."""
    user = require_auth()
    exp_svc = ExperimentService()
    results = exp_svc.get_experiment_results(experiment_id, user_id=user["id"])
    if not results:
        print_error(f"Experiment '{experiment_id}' not found.")
        raise typer.Exit(code=2)

    if format == "json":
        print_json_output(results)
        return

    exp = results["experiment"]
    console.print(f"\n[bold bright_cyan]Experiment Results — {experiment_id}[/]\n")
    print_key_value("Status", exp["status"].upper())
    print_key_value("Source file", exp["source_file"])
    print_key_value("Total candidates", exp["total_candidates"])
    print_key_value("Valid candidates", exp["valid_candidates"])
    if exp.get("best_candidate_id"):
        print_key_value("Best candidate", exp["best_candidate_id"])
    if exp.get("best_improvement_percent") is not None:
        print_key_value("Improvement", format_improvement(exp["best_improvement_percent"]))


@app.command("apply")
def apply_cmd(
    experiment_id: str = typer.Argument(..., help="Experiment ID"),
    candidate_id: Optional[str] = typer.Option(None, "--candidate", "-c", help="Candidate ID to apply"),
    file_path: Optional[str] = typer.Option(None, "--file", "-f", help="Target file path override"),
    dry_run: bool = typer.Option(False, "--dry-run", help="Display planned changes without modifying files"),
    yes: bool = typer.Option(False, "--yes", "-y", help="Confirm application without prompt"),
    force: bool = typer.Option(False, "--force", help="Overwrite even if source file has changed on disk"),
):
    """
    Apply optimized code to source file with conflict detection and automated backup.
    Authentication required.
    """
    user = require_auth()
    apply_svc = ApplyService()
    try:
        plan = apply_svc.plan_apply(
            experiment_id=experiment_id,
            candidate_id=candidate_id,
            target_file=file_path,
            user_id=user["id"],
        )

        console.print(f"\n[bold bright_cyan]Planned Changes for {plan['file_path']}:[/]\n")
        print_diff(plan["diff_text"])

        if plan["has_conflict"]:
            print_warning(
                f"Source file on disk has changed since experiment was run!\n"
                f"Expected: {plan['original_hash'][:16]}...\n"
                f"On disk:  {plan['current_on_disk_hash'][:16]}..."
            )
            if not force:
                print_error("Aborting to avoid overwriting unreviewed changes. Use --force to proceed.")
                raise typer.Exit(code=1)

        if dry_run:
            print_info("Dry-run mode: no changes were written to disk.")
            return

        if not yes:
            if not confirm_action(f"Apply candidate {plan['candidate_id'][:8]} to {plan['file_path']}?"):
                print_warning("Application cancelled.")
                return

        result = apply_svc.apply_candidate(
            experiment_id=experiment_id,
            candidate_id=candidate_id,
            target_file=file_path,
            dry_run=False,
            backup=True,
            force=force,
            user_id=user["id"],
        )
        print_success(f"Applied candidate {result['candidate_id'][:8]} to {result['file_path']}")
        if result.get("backup_path"):
            print_info(f"Backup preserved at: {result['backup_path']}")

    except MutagenError as err:
        print_error(str(err))
        raise typer.Exit(code=1)


@app.command("export-patch")
def export_patch_cmd(
    experiment_id: str = typer.Argument(..., help="Experiment ID"),
    candidate_id: Optional[str] = typer.Option(None, "--candidate", "-c", help="Candidate ID"),
    output: str = typer.Option("changes.patch", "--output", "-o", help="Output patch file path"),
):
    """Export candidate changes as a unified patch file. Authentication required."""
    user = require_auth()
    exp_svc = ExperimentService()
    exp = exp_svc.get_experiment(experiment_id, user_id=user["id"])
    if not exp:
        print_error(f"Experiment '{experiment_id}' not found.")
        raise typer.Exit(code=2)

    cid = candidate_id or exp.get("best_candidate_id")
    if not cid:
        print_error(f"No candidate found for experiment '{experiment_id}'.")
        raise typer.Exit(code=2)

    diff_data = exp_svc.get_candidate_diff(cid, user_id=user["id"])
    if not diff_data:
        print_error("Candidate diff not available.")
        raise typer.Exit(code=2)

    DiffService.export_patch_file(diff_data["diff_text"], output)
    print_success(f"Patch file saved to: {output}")


@app.command("certificate")
def certificate_cmd(
    experiment_id: str = typer.Argument(..., help="Experiment ID"),
    format: str = typer.Option("text", "--format", "-f", help="Output format"),
):
    """Generate an optimization certificate for an experiment. Authentication required."""
    user = require_auth()
    cert_svc = CertificateService()

    try:
        cert = cert_svc.generate_certificate(experiment_id, user_id=user["id"])
    except MutagenError as e:
        print_error(str(e))
        raise typer.Exit(code=e.exit_code)

    if not cert:
        print_error(f"Cannot generate certificate for experiment {experiment_id}")
        print_info("Ensure the experiment has an eligible candidate.")
        raise typer.Exit(code=5)

    if format == "json":
        print_json_output(cert)
    else:
        err_console.print("[bold]Optimization Certificate[/]\n")
        for key, value in cert.items():
            print_key_value(key, value)


@app.command("verify")
def verify_cmd(
    experiment_id: str = typer.Argument(..., help="Experiment ID"),
    format: str = typer.Option("text", "--format", "-f", help="Output format"),
):
    """Verify an optimization certificate. Authentication required."""
    user = require_auth()
    cert_svc = CertificateService()

    try:
        result = cert_svc.verify_certificate(experiment_id, user_id=user["id"])
    except MutagenError as e:
        print_error(str(e))
        raise typer.Exit(code=e.exit_code)

    if format == "json":
        print_json_output(result)
    else:
        if result["verified"]:
            print_success("Certificate verification PASSED")
        else:
            print_error(f"Certificate verification FAILED: {result.get('error', 'Tampering detected')}")
            raise typer.Exit(code=5)


# ── Project Sub-commands ─────────────────────────────────────

project_app = typer.Typer(name="project", help="Project management")
app.add_typer(project_app)


@project_app.command("create")
def project_create(
    name: str = typer.Argument(..., help="Project name"),
    description: str = typer.Option("", "--description", "-d", help="Project description"),
    language: str = typer.Option("python", "--language", "-l", help="Programming language"),
    source: Optional[str] = typer.Option(None, "--source", "-s", help="Initial source file"),
    format: str = typer.Option("text", "--format", "-f", help="Output format"),
):
    """Create a new project isolated to the authenticated user."""
    user = require_auth()
    service = ProjectService()
    try:
        result = service.create_project(name, description, language, source, user_id=user["id"])
    except MutagenError as e:
        print_error(str(e))
        raise typer.Exit(code=e.exit_code)

    if format == "json":
        print_json_output(result)
    else:
        print_success(f"Project '{name}' created")
        print_key_value("ID", result["id"])


@project_app.command("list")
def project_list(
    format: str = typer.Option("text", "--format", "-f", help="Output format"),
):
    """List projects for the authenticated user."""
    user = require_auth()
    service = ProjectService()
    projects = service.list_projects(user_id=user["id"])

    if format == "json":
        print_json_output(projects)
        return

    if not projects:
        print_info("No projects found. Create one with 'mutagen project create'")
        return

    table = create_results_table(f"Projects — {user['username']}")
    table.add_column("ID", style="bold")
    table.add_column("Name")
    table.add_column("Language")
    table.add_column("Created")

    for p in projects:
        table.add_row(p["id"][:12] + "...", p["name"], p["language"], p["created_at"][:19])

    console.print(table)


@project_app.command("show")
def project_show(
    project_id: str = typer.Argument(..., help="Project ID"),
    format: str = typer.Option("text", "--format", "-f", help="Output format"),
):
    """Show project details."""
    user = require_auth()
    service = ProjectService()
    project = service.get_project(project_id, user_id=user["id"])

    if not project:
        print_error(f"Project not found: {project_id}")
        raise typer.Exit(code=2)

    if format == "json":
        print_json_output(project)
    else:
        err_console.print("[bold]Project Details[/]\n")
        for key, value in project.items():
            print_key_value(key, value)


@project_app.command("delete")
def project_delete(
    project_id: str = typer.Argument(..., help="Project ID"),
    yes: bool = typer.Option(False, "--yes", "-y", help="Skip confirmation"),
):
    """Delete a project owned by the authenticated user."""
    user = require_auth()
    if not yes:
        if not confirm_action(f"Delete project {project_id}? This cannot be undone."):
            print_info("Cancelled.")
            return

    service = ProjectService()
    if service.delete_project(project_id, user_id=user["id"]):
        print_success(f"Project {project_id} deleted")
    else:
        print_error(f"Project not found: {project_id}")
        raise typer.Exit(code=2)


# ── Experiment Sub-commands ──────────────────────────────────

experiment_app = typer.Typer(name="experiment", help="Experiment management")
app.add_typer(experiment_app)


@experiment_app.command("list")
def experiment_list(
    limit: int = typer.Option(20, "--limit", "-l", help="Number of experiments to show"),
    format: str = typer.Option("text", "--format", "-f", help="Output format"),
):
    """List experiments for current user."""
    user = require_auth()
    service = ExperimentService()
    experiments = service.list_experiments(user_id=user["id"])

    if format == "json":
        print_json_output(experiments)
        return

    if not experiments:
        print_info("No experiments found. Run 'mutagen evolve' or 'mutagen optimize' to start one.")
        return

    table = create_results_table(f"Experiments — {user['username']}")
    table.add_column("ID", style="bold")
    table.add_column("File")
    table.add_column("Status")
    table.add_column("Generations")
    table.add_column("Candidates")
    table.add_column("Best Impr.")

    for e in experiments[:limit]:
        table.add_row(
            e["id"],
            e["source_file"],
            e["status"].upper(),
            e["generations"],
            str(e["candidates"]),
            str(e["best_improvement"]),
        )

    console.print(table)


# ── Mutation Sub-commands ────────────────────────────────────

mutation_app = typer.Typer(name="mutation", help="Mutation candidate management")
app.add_typer(mutation_app)


@mutation_app.command("list")
def mutation_list(
    experiment_id: str = typer.Argument(..., help="Experiment ID"),
    format: str = typer.Option("text", "--format", "-f", help="Output format"),
):
    """List mutation candidates for an experiment."""
    user = require_auth()
    service = ExperimentService()
    candidates = service.list_candidates(experiment_id, user_id=user["id"])

    if format == "json":
        print_json_output(candidates)
        return

    if not candidates:
        print_info(f"No candidates found for experiment {experiment_id}")
        return

    table = create_results_table(f"Candidates for {experiment_id}")
    table.add_column("ID", style="bold")
    table.add_column("Gen", justify="center")
    table.add_column("Strategy")
    table.add_column("Status")
    table.add_column("Fitness", justify="right")
    table.add_column("Speed Impr.", justify="right")

    for c in candidates:
        fitness_str = f"{c['fitness_score']:.3f}" if c.get("fitness_score") is not None else "-"
        speed_str = format_improvement(c["speed_improvement"]) if c.get("speed_improvement") is not None else "-"
        table.add_row(
            c["id"][:12] + "...",
            str(c["generation"]),
            c["strategy"],
            c["status"].upper(),
            fitness_str,
            speed_str,
        )

    console.print(table)


@mutation_app.command("diff")
def mutation_diff(
    mutation_id: str = typer.Argument(..., help="Mutation candidate ID"),
):
    """Show programmatic diff for a mutation candidate."""
    user = require_auth()
    service = ExperimentService()
    diff_data = service.get_candidate_diff(mutation_id, user_id=user["id"])

    if not diff_data:
        print_error(f"Candidate not found: {mutation_id}")
        raise typer.Exit(code=2)

    console.print(f"\n[bold]Diff for {mutation_id[:12]}... (Strategy: {diff_data.get('strategy', 'general')})[/]\n")
    print_diff(diff_data["diff_text"])


# ── Memory Sub-commands ──────────────────────────────────────

memory_app = typer.Typer(name="memory", help="Evolutionary memory management")
app.add_typer(memory_app)


@memory_app.command("list")
def memory_list():
    """List memory records for current user."""
    user = require_auth()
    from mutagen.memory import MemoryManager
    from mutagen.db.session import get_session

    with get_session() as session:
        mgr = MemoryManager(session, user_id=user["id"])
        stats = mgr.get_stats(user_id=user["id"])

    print_banner()
    console.print(f"[bold bright_cyan]Evolutionary Memory Summary — {user['username']}[/]\n")
    for mtype, count in stats.items():
        print_key_value(f"{mtype.title()} memories", count)


@memory_app.command("search")
def memory_search(
    query: str = typer.Argument(..., help="Search query"),
    limit: int = typer.Option(10, "--limit", "-l", help="Max results"),
):
    """Search evolutionary memory records for current user."""
    user = require_auth()
    from mutagen.memory import MemoryManager
    from mutagen.db.session import get_session

    with get_session() as session:
        mgr = MemoryManager(session, user_id=user["id"])
        results = mgr.search_memories(query, user_id=user["id"], limit=limit)

    if not results:
        print_info(f"No memories matched '{query}'")
        return

    console.print(f"\n[bold bright_cyan]Memory Search Results for '{query}':[/]\n")
    for r in results:
        console.print(f"  [bold magenta]›[/] [{r.memory_type.value.upper()}] {r.content[:160]}...")


# ── Helpers ──────────────────────────────────────────────────

def _redact_url(url: str) -> str:
    """Redact credentials from a database URL."""
    import re
    return re.sub(r"://([^:]+):([^@]+)@", r"://\1:***@", url)


def _default_env_content() -> str:
    """Default .env template content."""
    return """# MUTAGEN Configuration
MUTAGEN_AI_PROVIDER=groq
MUTAGEN_AI_MODEL=llama-3.3-70b-versatile
GROQ_API_KEY=your-api-key-here
GEMINI_API_KEY=
MUTAGEN_DATABASE_URL=postgresql+psycopg://mutagen:mutagen@localhost:5432/mutagen
MUTAGEN_REDIS_URL=redis://localhost:6379/0
MUTAGEN_LOG_LEVEL=INFO
MUTAGEN_ARTIFACT_DIR=./artifacts
MUTAGEN_MAX_GENERATIONS=5
MUTAGEN_POPULATION_SIZE=4
MUTAGEN_BENCHMARK_REPETITIONS=5
MUTAGEN_EXECUTION_TIMEOUT=30
"""


if __name__ == "__main__":
    app_entry()

