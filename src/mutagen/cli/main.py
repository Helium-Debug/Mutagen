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
from datetime import datetime
from pathlib import Path
from typing import Optional

import typer
from rich import box
from rich.progress import Progress, SpinnerColumn, TextColumn
from rich.table import Table

from mutagen import __version__
from mutagen.cli.display import (
    console, err_console, print_banner, print_success, print_error,
    print_warning, print_info, print_key_value, print_json_output,
    print_status, create_results_table, confirm_action, format_improvement,
    print_diff, print_evolution_report,
)
from mutagen.config import get_settings, reset_settings, MutagenSettings
from mutagen.core.auth import CredentialsManager
from mutagen.exceptions import (
    MutagenAuthenticationError, MutagenAuthorizationError, MutagenError, MutagenValidationError,
)
from mutagen.schemas import OptimizationObjective, ProgrammingLanguage
from mutagen.services import (
    AuthService, AnalysisService, ProjectService, ExperimentService,
    ExportService, CertificateService, DiffService, ApplyService,
    UsageService, get_ai_provider,
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
    print_info("Edit .env to set your GEMMA_BASE_URL, AI model, and database settings")
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
    ai_ok = False
    ai_desc = f"{settings.ai_provider.value} ({settings.ai_model})"
    try:
        provider = get_ai_provider()
        ai_ok, msg = provider.check_availability()
        ai_desc = f"{settings.ai_provider.value} ({settings.ai_model}) [{msg}]"
    except Exception as e:
        ai_desc += f" [check failed: {e}]"
    checks.append(("AI Provider", ai_desc, ai_ok))

    # Database
    from mutagen.db.session import check_database_connection
    db_ok, db_msg = check_database_connection()
    checks.append(("Database", db_msg, db_ok))

    # Docker Sandbox
    from mutagen.sandbox.docker_manager import DockerSandbox
    sandbox = DockerSandbox()
    docker_ok, docker_msg = sandbox.check_availability()
    checks.append(("Docker Daemon", docker_msg, docker_ok))
    if docker_ok:
        img_ok, img_msg = sandbox.check_image()
        checks.append(("Sandbox Image", f"{settings.sandbox_image} ({img_msg})", img_ok))
    else:
        checks.append(("Sandbox Image", f"{settings.sandbox_image} (Docker daemon unavailable)", False))

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


@app.command("docker")
def docker_command(
    launch: bool = typer.Option(True, "--launch/--no-launch", help="Attempt to launch Docker if it is currently off"),
    wait: int = typer.Option(15, "--wait", "-w", help="Seconds to wait for engine to initialize"),
    up: bool = typer.Option(False, "--up", help="Start background services (PostgreSQL & Redis) via Docker Compose"),
    down: bool = typer.Option(False, "--down", help="Stop background services via Docker Compose"),
):
    """Check Docker engine status, inspect Mutagen containers, and manage background services."""
    import subprocess
    from mutagen.sandbox.docker_manager import DockerSandbox

    sandbox = DockerSandbox()
    is_on, msg = sandbox.check_availability()

    if is_on:
        console.print()
        console.print("[bold green]● Docker engine is ON[/bold green]")
        console.print(f"[green]  Status: {msg}[/green]")

        img_ok, img_msg = sandbox.check_image()
        if img_ok:
            console.print(f"[green]  Sandbox Image: {img_msg}[/green]")
        else:
            console.print(f"[yellow]  Sandbox Image: {img_msg}[/yellow]")

        # Handle --up
        if up:
            console.print("\n[bold cyan]Starting MUTAGEN persistent services via Docker Compose...[/bold cyan]")
            try:
                subprocess.run(["docker", "compose", "up", "-d"], check=True)
                console.print("[bold green]✓ Background services started![/bold green]")
            except Exception as e:
                console.print(f"[bold red]Failed to start docker compose: {e}[/bold red]")

        # Handle --down
        if down:
            console.print("\n[bold cyan]Stopping MUTAGEN Docker Compose services...[/bold cyan]")
            try:
                subprocess.run(["docker", "compose", "down"], check=True)
                console.print("[bold green]✓ Background services stopped.[/bold green]")
            except Exception as e:
                console.print(f"[bold red]Failed to stop docker compose: {e}[/bold red]")

        # List active containers under Mutagen
        active_containers = []
        try:
            client = sandbox._get_client()
            active_containers = client.containers.list(all=True)
        except Exception:
            pass

        mutagen_containers = [
            c for c in active_containers
            if any("mutagen" in str(name).lower() for name in [c.name] + (c.attrs.get("Names") or []))
        ]

        if mutagen_containers:
            console.print("\n[bold cyan]Containers under 'mutagen' in Docker Desktop:[/bold cyan]")
            for c in mutagen_containers:
                status_color = "green" if c.status == "running" else "yellow"
                image_name = c.image.tags[0] if c.image.tags else c.short_id
                console.print(f"  • [bold]{c.name}[/bold] ({image_name}) -> [{status_color}]{c.status}[/{status_color}]")
        else:
            console.print("\n[dim]Persistent containers: None currently active.[/dim]")
            console.print("[dim]  To start background Postgres/Redis in Docker Desktop: [bold bright_cyan]mutagen docker --up[/bold bright_cyan][/dim]")

        console.print("\n[dim][italic]Note: Candidate sandbox containers are ephemeral by design.[/italic][/dim]")
        console.print("[dim]During evaluation ('mutagen test' / 'mutagen evaluate'), sandbox containers are spun up[/dim]")
        console.print("[dim]for isolated execution and automatically removed immediately after tests complete.[/dim]")
        console.print("[bold green]✓ Docker sandbox is ready for candidate execution and benchmarking.[/bold green]\n")
        return

    # Docker engine is OFF
    console.print()
    console.print("[bold red]● Docker engine is OFF[/bold red]")
    console.print(f"[red]  Status: {msg}[/red]")

    if not launch:
        console.print("[red]Docker daemon is not running. Please start Docker Desktop to enable candidate sandboxing.[/red]\n")
        raise typer.Exit(code=1)

    # Attempt to start Docker and notify
    console.print("[bold yellow]› Attempting to start Docker...[/bold yellow]")
    started, launch_msg = sandbox.launch_docker_daemon()
    if started:
        console.print(f"[cyan]  {launch_msg}[/cyan]")
        console.print(f"[dim]  Waiting up to {wait}s for Docker engine to become ready...[/dim]")

        with Progress(
            SpinnerColumn(),
            TextColumn("[progress.description]{task.description}"),
            transient=True,
        ) as progress:
            progress.add_task("Waiting for Docker engine to initialize...", total=None)
            is_ready = sandbox.wait_for_daemon(timeout=wait, poll_interval=1.5)

        if is_ready:
            console.print("[bold green]● Docker engine is now ON[/bold green]")
            console.print("[bold green]✓ Docker engine started successfully and daemon is reachable![/bold green]\n")
            return
        else:
            console.print("[bold red]● Docker engine is OFF[/bold red]")
            console.print(
                "[red]Docker was launched but the daemon is still initializing in the background.[/red]\n"
                "[red]Please wait a moment for Docker Desktop to finish booting, then run 'mutagen docker' again.[/red]\n"
            )
            raise typer.Exit(code=1)
    else:
        console.print(f"[bold red]✗ Could not automatically start Docker: {launch_msg}[/bold red]")
        console.print("[red]Please start Docker Desktop manually.[/red]\n")
        raise typer.Exit(code=1)


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
    ai: bool = typer.Option(False, "--ai", help="Include AI model structural, bottleneck, and optimization analysis"),
    format: str = typer.Option("text", "--format", "-f", help="Output format: text or json"),
):
    """Analyze a source code file. Authentication required."""
    user = require_auth()

    try:
        service = AnalysisService()
        if ai:
            combined = service.analyze_with_ai(file_path)
            analysis = service.analyze_file(file_path)
            ai_data = combined.get("ai_analysis", {})
        else:
            analysis = service.analyze_file(file_path)
            ai_data = None
    except MutagenError as e:
        print_error(str(e))
        raise typer.Exit(code=e.exit_code)

    if format == "json":
        output = analysis.model_dump()
        if ai_data:
            output["ai_analysis"] = ai_data
        print_json_output(output)
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

    # Display AI Analysis if requested
    if ai_data:
        err_console.print()
        err_console.print("[bold bright_magenta]AI Model Code Analysis (Gemma)[/]")
        complexity_info = ai_data.get("complexity", {})
        if "estimated_time_complexity" in complexity_info:
            print_key_value("AI Time Complexity", str(complexity_info.get("estimated_time_complexity")))
        if "estimated_space_complexity" in complexity_info:
            print_key_value("AI Space Complexity", str(complexity_info.get("estimated_space_complexity")))
        bottlenecks = complexity_info.get("bottlenecks", [])
        if bottlenecks:
            err_console.print("\n[bold yellow]Identified Bottlenecks:[/]")
            for b in bottlenecks:
                err_console.print(f"  • {b}")
        suggestions = ai_data.get("optimization_suggestions", [])
        if suggestions:
            err_console.print("\n[bold green]AI Optimization Proposals:[/]")
            for s in suggestions:
                desc = s.get("description", "")
                target = s.get("target_symbol", "module")
                strategy = s.get("strategy", "general")
                err_console.print(f"  • [{strategy}] {target}: {desc}")

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

        if path.is_file():
            err_console.print()
            print_info(f"Initiating automated code repair on {path.name} using local Gemma 2...")
            from mutagen.ai.repair import CodeRepairService
            repair_svc = CodeRepairService()
            rep_res = repair_svc.repair_file(path, failures=result.failure_summaries or ["Tests failed"])
            if rep_res.success and rep_res.changes_made:
                print_success(f"File {path.name} was successfully updated with corrected code via {rep_res.model_used}!")
                re_content = path.read_text(encoding="utf-8")
                re_result = runner.run_tests("repaired", re_content)
                if re_result.all_passed:
                    print_success(f"Re-test verified: All tests now PASS! (duration: {re_result.duration_seconds:.3f}s)")
                else:
                    print_warning("Re-test: Some tests still need manual review.")
            elif not rep_res.success:
                print_error(f"Repair attempt failed: {rep_res.error_message}")


@app.command("repair")
def repair_cmd(
    target: str = typer.Argument(..., help="Path to source file to test and repair if failing"),
    test_command: Optional[str] = typer.Option(None, "--test-cmd", help="Optional test command"),
):
    """Run tests on a file and automatically repair the code using local gemma2 if any test fails."""
    user = require_auth()
    path = Path(target).resolve()
    if not path.exists() or not path.is_file():
        print_error(f"File not found: {path}")
        raise typer.Exit(code=2)

    print_banner()
    err_console.print(f"[bold]Checking and repairing target: {path.name} (User: {user['username']})[/]\n")

    content = path.read_text(encoding="utf-8")
    from mutagen.sandbox.docker_manager import DockerSandbox
    from mutagen.testing.test_runner import TestRunner

    sandbox = DockerSandbox()
    runner = TestRunner(sandbox)
    result = runner.run_tests("baseline", content, test_command=test_command)

    if result.all_passed:
        print_success(f"All tests already PASS for {path.name}!")
        return

    print_warning(f"Tests FAILED ({result.failed} failed, {result.errors} errors). Updating code using local gemma2...")
    from mutagen.ai.repair import CodeRepairService
    repair_svc = CodeRepairService()
    rep_res = repair_svc.repair_file(path, failures=result.failure_summaries or ["Tests failed"])

    if rep_res.success and rep_res.changes_made:
        print_success(f"Updated {path.name} with corrected code using {rep_res.model_used}.")
        re_result = runner.run_tests("repaired", path.read_text(encoding="utf-8"), test_command=test_command)
        if re_result.all_passed:
            print_success(f"Re-test confirmed: All tests now PASS!")
        else:
            print_warning("Re-test: Some checks still require attention.")
    elif not rep_res.changes_made:
        print_info("No changes were made by the repair model.")
    else:
        print_error(f"Repair failed: {rep_res.error_message}")
        raise typer.Exit(code=1)


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
    stop_on_stagnation: bool = typer.Option(False, "--stop-on-stagnation", help="Stop evolution early if stagnation is reached"),
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
        stop_on_stagnation=stop_on_stagnation,
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

    # Show candidates table and results
    exp_svc = ExperimentService()
    results = exp_svc.get_experiment_results(summary.experiment_id, user_id=user["id"])
    if results:
        candidates = results.get("candidates", [])
        if candidates:
            err_console.print()
            table = Table(
                title=f"Evaluated Candidates for {summary.experiment_id}",
                box=box.ROUNDED,
                border_style="bright_cyan",
                header_style="bold bright_white",
            )
            table.add_column("Candidate ID", style="cyan")
            table.add_column("Gen", justify="center")
            table.add_column("Strategy")
            table.add_column("Verdict", justify="center")
            table.add_column("Status", justify="center")
            table.add_column("Speed Imp.", justify="right")
            table.add_column("Eligible", justify="center")

            for c in candidates:
                verdict = c.get("verification_verdict") or "-"
                v_style = (
                    "bold green" if verdict == "ACCEPT"
                    else ("bold yellow" if verdict == "REVIEW"
                    else ("bold red" if verdict == "REJECT" else "white"))
                )
                v_str = f"[{v_style}]{verdict}[/{v_style}]" if verdict != "-" else "-"

                speed = c.get("speed_improvement")
                speed_str = format_improvement(speed) if speed is not None else "-"
                speed_style = "bold green" if (speed or 0) > 0 else ("bold red" if (speed or 0) < 0 else "white")
                speed_disp = f"[{speed_style}]{speed_str}[/{speed_style}]" if speed is not None else "-"

                is_el = c.get("is_eligible", False)
                el_disp = "[bold green]YES[/]" if is_el else "[dim]NO[/]"

                c_status = c.get("status", "")
                stat_style = "bold green" if c_status == "best_eligible" else "white"

                table.add_row(
                    c["id"][:12],
                    str(c.get("generation", 1)),
                    c.get("strategy", "unknown"),
                    v_str,
                    f"[{stat_style}]{c_status}[/]",
                    speed_disp,
                    el_disp,
                )
            err_console.print(table)

        best_cand_id = summary.best_candidate_id
        if best_cand_id:
            try:
                diff_report = exp_svc.get_candidate_diff(best_cand_id, user_id=user["id"])
                if diff_report:
                    err_console.print()
                    print_evolution_report(diff_report)
            except Exception:
                pass

    if summary.status.value == "succeeded":
        print_success("Evolution succeeded! Use 'mutagen apply' to inspect and apply optimized code.")
    else:
        print_info(f"Evolution complete with status: {summary.status.value.upper()}")


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

    candidates = results.get("candidates", [])
    if candidates:
        console.print("\n[bold bright_cyan]Candidate Verification & Evaluation Summary[/]")
        table = create_results_table(f"Candidates ({len(candidates)})")
        table.add_column("Candidate ID", style="bold bright_white")
        table.add_column("Strategy", style="dim")
        table.add_column("Verdict", style="bold")
        table.add_column("Fitness", justify="right")
        table.add_column("Speed", justify="right")
        table.add_column("Eligible")

        for c in candidates:
            verdict = c.get("verification_verdict") or ("ACCEPT" if c.get("verification_passed") else "-")
            v_style = "green" if verdict == "ACCEPT" else ("yellow" if verdict == "REVIEW" else ("red" if verdict == "REJECT" else "white"))
            fit = f"{c.get('fitness_score'):.3f}" if c.get("fitness_score") is not None else "-"
            spd = format_improvement(c.get("speed_improvement")) if c.get("speed_improvement") is not None else "-"
            elig = "✓" if c.get("is_eligible") else "✗"
            table.add_row(
                c["id"][:12],
                c.get("strategy", "-"),
                f"[{v_style}]{verdict}[/{v_style}]",
                fit,
                spd,
                f"[{'green' if c.get('is_eligible') else 'red'}]{elig}[/]",
            )
        console.print(table)

    best_cand = results.get("best_candidate")
    if best_cand and best_cand.get("verification_json"):
        from mutagen.verification.report import format_verification_report
        try:
            console.print("\n" + format_verification_report(best_cand["verification_json"]))
        except Exception:
            pass


@app.command("verify-candidate")
def verify_candidate_cmd(
    candidate_id: str = typer.Argument(..., help="Candidate ID"),
    format: str = typer.Option("text", "--format", "-f", help="Output format: text or json"),
):
    """View full correctness verification report for a candidate. Authentication required."""
    user = require_auth()
    exp_svc = ExperimentService()
    cand = exp_svc.get_candidate(candidate_id, user_id=user["id"])
    if not cand:
        print_error(f"Candidate '{candidate_id}' not found.")
        raise typer.Exit(code=2)

    verif = cand.get("verification_json")
    if not verif:
        print_warning(f"No verification report available for candidate '{candidate_id}'.")
        return

    if format == "json":
        print_json_output(verif)
    else:
        from mutagen.verification.report import format_verification_report
        console.print(format_verification_report(verif))


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



# ── Usage & Token Tracking Commands ──────────────────────────

def _render_usage_dashboard(data: dict) -> None:
    """Format and print the standard MUTAGEN usage dashboard."""
    if data.get("is_empty"):
        lines = [
            "-" * 50,
            "MUTAGEN TOKEN USAGE",
            "-" * 50,
            "",
            "No token usage or cache events recorded yet.",
            "",
            "Run an analysis or evolutionary optimization to generate usage records:",
            "    mutagen analyze <file>",
            "    mutagen optimize <file>",
            "",
            "-" * 50,
        ]
        console.print("\n" + "\n".join(lines) + "\n")
        return

    stats = data["analysis_statistics"]
    tokens = data["token_consumption"]
    opt = data["optimization"]
    hit_rate = f"{opt['cache_hit_rate']:.1f}%"

    lines = [
        "-" * 50,
        "MUTAGEN TOKEN USAGE",
        "-" * 50,
        "",
        "ANALYSIS STATISTICS",
        "",
        f"Total Analyses:                  {stats['total_analyses']:>12,}",
        f"Actual AI Requests:              {stats['actual_ai_requests']:>12,}",
        f"Successful Requests:             {stats['successful_requests']:>12,}",
        f"Failed Requests:                 {stats['failed_requests']:>12,}",
        f"Cache Hits:                      {stats['cache_hits']:>12,}",
        f"Cache Misses:                    {stats['cache_misses']:>12,}",
        f"Incremental Analyses:            {stats['incremental_analyses']:>12,}",
        "",
        "TOKEN CONSUMPTION",
        "",
        f"Actual Input Tokens:         {tokens['actual_input_tokens']:>15,}",
        f"Actual Output Tokens:        {tokens['actual_output_tokens']:>15,}",
        f"Actual Total Tokens:         {tokens['actual_total_tokens']:>15,}",
    ]

    if tokens.get("cached_input_tokens", 0) > 0:
        lines.append(f"Cached Input Tokens:         {tokens['cached_input_tokens']:>15,}")
    if tokens.get("estimated_total_tokens", 0) > 0:
        lines.append(f"Estimated Tokens (approx):   {tokens['estimated_total_tokens']:>15,}")
    if tokens.get("unavailable_measurements", 0) > 0:
        lines.append(f"Unavailable Measurements:    {tokens['unavailable_measurements']:>15,}")

    lines.extend([
        "",
        "OPTIMIZATION",
        "",
        f"AI Requests Avoided:             {opt['ai_requests_avoided']:>12,}",
        f"Estimated Tokens Saved:          {opt['estimated_tokens_saved']:>12,}",
        f"Cache Hit Rate:                  {hit_rate:>12}",
    ])

    if "total_work_tokens" in opt:
        lines.append(f"Work Equivalent:             {opt['total_work_tokens']:>15,}")
    if "efficiency_multiplier" in opt:
        lines.append(f"Efficiency Multiplier:       {opt['efficiency_multiplier']:>15}")

    lines.extend([
        "",
        "-" * 50,
    ])
    console.print("\n" + "\n".join(lines) + "\n")

    # 1. Log of WHERE and HOW tokens are saved (Storage Architecture)
    storage_info = data.get("storage_and_mechanisms", [])
    if storage_info:
        console.print("[bold bright_cyan]WHERE & HOW TOKENS ARE SAVED (Storage Architecture)[/bold bright_cyan]")
        console.print("[dim]-------------------------------------------------------------[/dim]")
        for i, item in enumerate(storage_info, 1):
            console.print(f"[bold bright_white]{i}. {item['layer']}[/bold bright_white]")
            console.print(f"   [dim]Where Saved:[/]   [bright_yellow]{item['storage_location']}[/bright_yellow]")
            console.print(f"   [dim]Mechanism:[/]     [white]{item['mechanism']}[/white]")
            console.print(f"   [dim]How Saved:[/]     [dim]{item['how_saved']}[/dim]")
        console.print()

    # 2. Token Savings Breakdown by Storage Layer
    breakdown = data.get("savings_breakdown", [])
    if breakdown:
        b_table = Table(
            title="Token Savings Breakdown by Storage Layer",
            box=box.ROUNDED,
            border_style="bright_cyan",
            header_style="bold bright_white",
            title_style="bold bright_cyan",
        )
        b_table.add_column("Storage Layer / Cache Type", style="cyan")
        b_table.add_column("Hits", justify="right", style="green")
        b_table.add_column("Misses", justify="right", style="dim")
        b_table.add_column("Requests Avoided", justify="right", style="bright_yellow")
        b_table.add_column("Estimated Tokens Saved", justify="right", style="bold green")

        for b in breakdown:
            b_table.add_row(
                b["cache_type"],
                f"{b['hits']:,}",
                f"{b['misses']:,}",
                f"{b['requests_avoided']:,}",
                f"+{b['tokens_avoided']:,}",
            )
        console.print(b_table)
        console.print()

    # 3. Recent Token Savings Audit Log
    recent_log = data.get("recent_savings_log", [])
    if recent_log:
        log_table = Table(
            title="Recent Token Savings Audit Log",
            box=box.ROUNDED,
            border_style="bright_cyan",
            header_style="bold bright_white",
            title_style="bold bright_cyan",
        )
        log_table.add_column("Timestamp", style="dim")
        log_table.add_column("Operation", style="cyan")
        log_table.add_column("Storage Layer", style="bright_yellow")
        log_table.add_column("Baseline / How Saved")
        log_table.add_column("Tokens Avoided", justify="right", style="bold green")

        for ev in recent_log:
            log_table.add_row(
                ev["timestamp"],
                ev["operation"],
                ev["cache_type"],
                ev.get("baseline", "Historical measured baseline"),
                f"+{ev['tokens_avoided']:,}",
            )
        console.print(log_table)
        console.print()


def _render_detailed_records(data: dict, page: int) -> None:
    """Format and display detailed usage records in a rich table."""
    records = data.get("records", [])
    pagination = data.get("pagination", {"page": page, "total_pages": 1, "total_records": 0})

    if not records:
        console.print("\n[dim]No detailed usage records found matching the criteria.[/dim]\n")
        return

    table = Table(
        title=f"MUTAGEN AI Usage Records — Page {pagination['page']} of {pagination['total_pages']} (Total: {pagination['total_records']})",
        box=box.ROUNDED,
        border_style="bright_cyan",
        header_style="bold bright_white",
        title_style="bold bright_cyan",
    )
    table.add_column("Timestamp", style="dim")
    table.add_column("Operation", style="bold bright_cyan")
    table.add_column("Provider/Model")
    table.add_column("Input", justify="right")
    table.add_column("Output", justify="right")
    table.add_column("Total", justify="right", style="bold")
    table.add_column("Source")
    table.add_column("Status")
    table.add_column("Latency", justify="right")

    for r in records:
        prov_model = f"{r.get('provider', '')}/{r.get('model', '')}" if r.get("provider") else "-"
        in_tok = f"{r['raw_input_tokens']:,}" if r.get("raw_input_tokens") is not None else str(r.get("input_tokens", "-"))
        out_tok = f"{r['raw_output_tokens']:,}" if r.get("raw_output_tokens") is not None else str(r.get("output_tokens", "-"))
        tot_tok = f"{r['raw_total_tokens']:,}" if r.get("raw_total_tokens") is not None else str(r.get("total_tokens", "-"))
        lat = f"{r['latency_ms']:.0f}ms" if r.get("latency_ms") is not None else "-"
        status_val = str(r.get("status", "-"))
        status_style = "green" if status_val == "success" else "red"

        table.add_row(
            r.get("timestamp", "-"),
            r.get("operation", "-"),
            prov_model,
            in_tok,
            out_tok,
            tot_tok,
            r.get("measurement_source", "-"),
            f"[{status_style}]{status_val}[/{status_style}]",
            lat,
        )

    console.print()
    console.print(table)
    if pagination["total_pages"] > 1:
        console.print(f"[dim]Showing page {pagination['page']} of {pagination['total_pages']}. Use --page <N> to view other pages.[/dim]\n")


def _render_cache_stats(data: dict) -> None:
    """Format and display cache event statistics."""
    summary = data.get("summary", {})
    breakdown = data.get("breakdown_by_type", {})

    console.print("\n[bold bright_cyan]MUTAGEN Cache & Optimization Statistics[/bold bright_cyan]\n")
    print_key_value("Total Lookups", f"{summary.get('total_lookups', 0):,}")
    print_key_value("Cache Hits", f"{summary.get('cache_hits', 0):,}")
    print_key_value("Cache Misses", f"{summary.get('cache_misses', 0):,}")
    print_key_value("Incremental Analyses", f"{summary.get('incremental_analyses', 0):,}")
    print_key_value("Cache Hit Rate", f"{summary.get('cache_hit_rate', 0.0):.1f}%")
    print_key_value("AI Requests Avoided", f"{summary.get('ai_requests_avoided', 0):,}")
    print_key_value("Estimated Tokens Saved", f"{summary.get('estimated_tokens_saved', 0):,}")

    if breakdown:
        console.print("\n[bold]Breakdown by Cache Layer:[/bold]\n")
        table = Table(box=box.SIMPLE_HEAVY, border_style="bright_cyan")
        table.add_column("Cache Layer", style="bold")
        table.add_column("Hits", justify="right", style="green")
        table.add_column("Misses", justify="right", style="yellow")
        table.add_column("Est. Tokens Avoided", justify="right", style="cyan")
        for ctype, cdata in breakdown.items():
            table.add_row(
                ctype,
                f"{cdata.get('hits', 0):,}",
                f"{cdata.get('misses', 0):,}",
                f"{cdata.get('tokens_avoided', 0):,}",
            )
        console.print(table)
    console.print()


def _render_savings_report(data: dict) -> None:
    """Format and display token savings report."""
    console.print("\n[bold bright_cyan]MUTAGEN Token Savings & Avoided Work[/bold bright_cyan]\n")
    print_key_value("AI Requests Avoided", f"{data.get('total_requests_avoided', 0):,}")
    print_key_value("Estimated Tokens Saved", f"{data.get('total_estimated_tokens_saved', 0):,}")
    print_key_value("Cache Hit Rate", f"{data.get('cache_hit_rate', 0.0):.1f}%")

    notice = data.get("accounting_notice")
    if notice:
        console.print(f"\n[dim italic]Notice: {notice}[/dim italic]\n")

    events = data.get("recent_savings_events", [])
    if events:
        console.print("[bold]Recent Avoided Work & Savings Events:[/bold]\n")
        table = Table(box=box.ROUNDED, border_style="bright_cyan")
        table.add_column("Timestamp", style="dim")
        table.add_column("Operation", style="bold bright_cyan")
        table.add_column("Cache Layer")
        table.add_column("Requests Avoided", justify="right")
        table.add_column("Tokens Avoided", justify="right", style="bold green")
        table.add_column("Baseline Method")
        for ev in events:
            table.add_row(
                ev.get("timestamp", "-"),
                ev.get("operation", "-"),
                ev.get("cache_type", "-"),
                str(ev.get("requests_avoided", 1)),
                f"{ev.get('tokens_avoided', 0):,}",
                ev.get("baseline", "Historical baseline"),
            )
        console.print(table)
    console.print()


@app.command("usage")
def usage(
    detailed: bool = typer.Option(False, "--detailed", "-d", help="Display individual usage records with pagination"),
    today: bool = typer.Option(False, "--today", help="Filter usage for today only"),
    since: Optional[str] = typer.Option(None, "--since", help="Filter records since date (YYYY-MM-DD)"),
    until: Optional[str] = typer.Option(None, "--until", help="Filter records until date (YYYY-MM-DD)"),
    operation: Optional[str] = typer.Option(None, "--operation", "-o", help="Filter by operation (analyze, mutate, evolution, explain-failure)"),
    cache: bool = typer.Option(False, "--cache", help="Display cache hit and event statistics"),
    savings: bool = typer.Option(False, "--savings", help="Display estimated token savings and avoided work"),
    export: Optional[str] = typer.Option(None, "--export", "-e", help="Export report format: 'csv' or 'json'"),
    json_output: bool = typer.Option(False, "--json", help="Output raw machine-readable JSON without styling"),
    project: Optional[str] = typer.Option(None, "--project", "-p", help="Filter by project ID"),
    provider: Optional[str] = typer.Option(None, "--provider", help="Filter by AI provider"),
    model: Optional[str] = typer.Option(None, "--model", "-m", help="Filter by AI model"),
    page: int = typer.Option(1, "--page", min=1, help="Page number for detailed records"),
    limit: int = typer.Option(20, "--limit", min=1, max=100, help="Records per page for detailed view"),
):
    """
    Inspect AI token consumption, cache performance, and optimization savings.

    Displays dashboard by default. Supports filtering, detailed pagination, and export.
    """
    # 1. Date range validation
    since_dt: Optional[datetime] = None
    until_dt: Optional[datetime] = None

    if today:
        now = datetime.now()
        since_dt = datetime(now.year, now.month, now.day, 0, 0, 0)
        until_dt = datetime(now.year, now.month, now.day, 23, 59, 59)
    else:
        if since:
            try:
                d = datetime.strptime(since.strip(), "%Y-%m-%d")
                since_dt = datetime(d.year, d.month, d.day, 0, 0, 0)
            except ValueError:
                print_error(f"Invalid date format for --since: '{since}'. Expected YYYY-MM-DD.")
                raise typer.Exit(code=2)
        if until:
            try:
                d = datetime.strptime(until.strip(), "%Y-%m-%d")
                until_dt = datetime(d.year, d.month, d.day, 23, 59, 59)
            except ValueError:
                print_error(f"Invalid date format for --until: '{until}'. Expected YYYY-MM-DD.")
                raise typer.Exit(code=2)

    if since_dt and until_dt and since_dt > until_dt:
        print_error(f"Invalid date range: --since ({since}) must be earlier than or equal to --until ({until}).")
        raise typer.Exit(code=2)

    # 2. Export format validation
    export_fmt = None
    if export:
        export_fmt = export.strip().lower()
        if export_fmt not in ("csv", "json"):
            print_error(f"Invalid export format: '{export}'. Supported formats are: csv, json.")
            raise typer.Exit(code=2)

    # 3. Authentication & Authorization
    user = require_auth()
    user_id = user["id"]

    usage_svc = UsageService()

    try:
        # 4. Handle export requests
        if export_fmt == "csv":
            csv_content = usage_svc.export_csv(
                user_id=user_id,
                project_id=project,
                since=since_dt,
                until=until_dt,
                operation=operation,
                provider=provider,
                model=model,
            )
            sys.stdout.write(csv_content)
            return

        if export_fmt == "json":
            json_data = usage_svc.export_json(
                user_id=user_id,
                project_id=project,
                since=since_dt,
                until=until_dt,
                operation=operation,
                provider=provider,
                model=model,
            )
            print_json_output(json_data)
            return

        # 5. Handle machine-readable JSON output
        if json_output:
            if detailed:
                data = usage_svc.get_detailed_records(
                    user_id=user_id,
                    project_id=project,
                    since=since_dt,
                    until=until_dt,
                    operation=operation,
                    provider=provider,
                    model=model,
                    page=page,
                    limit=limit,
                )
            elif cache:
                data = usage_svc.get_cache_statistics(
                    user_id=user_id,
                    project_id=project,
                    since=since_dt,
                    until=until_dt,
                    operation=operation,
                )
            elif savings:
                data = usage_svc.get_savings_report(
                    user_id=user_id,
                    project_id=project,
                    since=since_dt,
                    until=until_dt,
                    operation=operation,
                )
            else:
                data = usage_svc.get_usage_dashboard(
                    user_id=user_id,
                    project_id=project,
                    since=since_dt,
                    until=until_dt,
                    operation=operation,
                    provider=provider,
                    model=model,
                )
            print_json_output(data)
            return

        # 6. Display human-readable outputs
        if detailed:
            data = usage_svc.get_detailed_records(
                user_id=user_id,
                project_id=project,
                since=since_dt,
                until=until_dt,
                operation=operation,
                provider=provider,
                model=model,
                page=page,
                limit=limit,
            )
            _render_detailed_records(data, page)
        elif cache:
            data = usage_svc.get_cache_statistics(
                user_id=user_id,
                project_id=project,
                since=since_dt,
                until=until_dt,
                operation=operation,
            )
            _render_cache_stats(data)
        elif savings:
            data = usage_svc.get_savings_report(
                user_id=user_id,
                project_id=project,
                since=since_dt,
                until=until_dt,
                operation=operation,
            )
            _render_savings_report(data)
        else:
            data = usage_svc.get_usage_dashboard(
                user_id=user_id,
                project_id=project,
                since=since_dt,
                until=until_dt,
                operation=operation,
                provider=provider,
                model=model,
            )
            _render_usage_dashboard(data)

    except (MutagenAuthenticationError, MutagenAuthorizationError) as e:
        print_error(str(e))
        raise typer.Exit(code=1)
    except MutagenValidationError as e:
        print_error(str(e))
        raise typer.Exit(code=2)
    except Exception as e:
        err_msg = str(e)
        if "connect" in err_msg.lower() or "database" in err_msg.lower() or "operationalerror" in err_msg.lower():
            print_error(f"Database error: Unable to connect to MUTAGEN database.\nDetails: {err_msg}")
        else:
            print_error(f"Failed to query usage records: {err_msg}")
        raise typer.Exit(code=1)


# ── Helpers ──────────────────────────────────────────────────

def _redact_url(url: str) -> str:
    """Redact credentials from a database URL."""
    import re
    return re.sub(r"://([^:]+):([^@]+)@", r"://\1:***@", url)


def _default_env_content() -> str:
    """Default .env template content."""
    return """# MUTAGEN Configuration
MUTAGEN_AI_PROVIDER=gemma
MUTAGEN_AI_MODEL=gemma4:e4b
GEMMA_BASE_URL=http://localhost:11434
# GEMMA_API_KEY=
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

