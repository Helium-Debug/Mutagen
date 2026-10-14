"""
Rich console and formatting utilities for MUTAGEN CLI.

Provides the shared console instance, banner display, status formatting,
and standardized output helpers.
"""

from __future__ import annotations

import json
import sys
from enum import Enum
from typing import Any, Optional

from rich.console import Console
from rich.panel import Panel
from rich.table import Table
from rich.text import Text
from rich.theme import Theme
from rich import box

# ── Theme ──────────────────────────────────────────────────────
MUTAGEN_THEME = Theme({
    "mutagen.title": "bold bright_cyan",
    "mutagen.subtitle": "dim cyan",
    "mutagen.tagline": "italic bright_white",
    "mutagen.success": "bold green",
    "mutagen.error": "bold red",
    "mutagen.warning": "bold yellow",
    "mutagen.info": "bold blue",
    "mutagen.dim": "dim white",
    "mutagen.key": "bold bright_magenta",
    "mutagen.value": "white",
    "mutagen.status.valid": "bold green",
    "mutagen.status.rejected": "bold red",
    "mutagen.status.failed": "bold red",
    "mutagen.status.running": "bold yellow",
    "mutagen.status.cancelled": "dim yellow",
    "mutagen.status.best": "bold bright_green",
    "mutagen.status.queued": "bold blue",
    "mutagen.metric.positive": "bold green",
    "mutagen.metric.negative": "bold red",
    "mutagen.metric.neutral": "white",
})

# ── Windows Console Encoding Safety ──────────────────────────
if sys.platform == "win32":
    try:
        if hasattr(sys.stdout, "reconfigure"):
            sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        if hasattr(sys.stderr, "reconfigure"):
            sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

# ── Console instances ────────────────────────────────────────
console = Console(theme=MUTAGEN_THEME, stderr=False)
err_console = Console(theme=MUTAGEN_THEME, stderr=True)


class CandidateStatus(str, Enum):
    """Status labels for mutation candidates."""
    VALID = "VALID"
    REJECTED = "REJECTED"
    FAILED = "FAILED"
    RUNNING = "RUNNING"
    CANCELLED = "CANCELLED"
    BEST_ELIGIBLE = "BEST ELIGIBLE"
    QUEUED = "QUEUED"


def print_banner() -> None:
    """Display the MUTAGEN banner."""
    banner_text = Text()
    banner_text.append("MUTAGEN\n", style="mutagen.title")
    banner_text.append("The Experimental Evolution Engine for Code\n\n", style="mutagen.subtitle")
    banner_text.append("AI proposes.\n", style="mutagen.tagline")
    banner_text.append("MUTAGEN experiments.\n", style="mutagen.tagline")
    banner_text.append("Memory makes it evolve.", style="mutagen.tagline")

    panel = Panel(
        banner_text,
        border_style="bright_cyan",
        box=box.DOUBLE_EDGE,
        padding=(1, 2),
    )
    err_console.print(panel)


def print_success(message: str) -> None:
    """Print a success message."""
    err_console.print(f"[mutagen.success]✓[/] {message}")


def print_error(message: str) -> None:
    """Print an error message."""
    err_console.print(f"[mutagen.error]✗[/] {message}")


def print_warning(message: str) -> None:
    """Print a warning message."""
    err_console.print(f"[mutagen.warning]⚠[/] {message}")


def print_info(message: str) -> None:
    """Print an info message."""
    err_console.print(f"[mutagen.info]ℹ[/] {message}")


def print_key_value(key: str, value: Any) -> None:
    """Print a key-value pair."""
    err_console.print(f"  [mutagen.key]{key}:[/] [mutagen.value]{value}[/]")


def print_json_output(data: Any) -> None:
    """
    Print JSON output to stdout.

    All decorative output goes to stderr, so stdout is clean JSON.
    """
    print(json.dumps(data, indent=2, default=str))


def print_status(status: str) -> None:
    """Print a formatted status label."""
    style_map = {
        "VALID": "mutagen.status.valid",
        "REJECTED": "mutagen.status.rejected",
        "FAILED": "mutagen.status.failed",
        "RUNNING": "mutagen.status.running",
        "CANCELLED": "mutagen.status.cancelled",
        "BEST ELIGIBLE": "mutagen.status.best",
        "QUEUED": "mutagen.status.queued",
        "SUCCEEDED": "mutagen.status.valid",
        "TIMED_OUT": "mutagen.status.failed",
    }
    style = style_map.get(status.upper(), "white")
    err_console.print(f"  Status: [{style}]{status}[/]")


def format_improvement(percent: float) -> str:
    """Format an improvement percentage with sign and color hint."""
    if percent > 0:
        return f"+{percent:.1f}%"
    elif percent < 0:
        return f"{percent:.1f}%"
    else:
        return "0.0%"


def create_results_table(title: str) -> Table:
    """Create a standardized results table."""
    table = Table(
        title=title,
        box=box.ROUNDED,
        border_style="bright_cyan",
        header_style="bold bright_white",
        title_style="bold bright_cyan",
    )
    return table


def confirm_action(message: str, default: bool = False) -> bool:
    """Ask for user confirmation. Returns default in non-interactive mode."""
    if not sys.stdin.isatty():
        return default
    try:
        response = console.input(f"[mutagen.warning]{message} [y/N]: [/]")
        return response.strip().lower() in ("y", "yes")
    except (EOFError, KeyboardInterrupt):
        return default


def print_diff(diff_text: str) -> None:
    """Print syntax-highlighted unified diff."""
    if not diff_text or not diff_text.strip():
        console.print("[dim]No changes detected.[/dim]")
        return

    # Normalize special unicode hyphens and quotes for terminal compatibility
    diff_text = (
        diff_text.replace("\u2011", "-")
        .replace("\u2013", "-")
        .replace("\u2014", "--")
        .replace("\u2018", "'")
        .replace("\u2019", "'")
        .replace("\u201c", '"')
        .replace("\u201d", '"')
    )

    for line in diff_text.splitlines():
        if line.startswith("+++") or line.startswith("---"):
            console.print(f"[bold cyan]{line}[/bold cyan]")
        elif line.startswith("@@"):
            console.print(f"[bold magenta]{line}[/bold magenta]")
        elif line.startswith("+"):
            console.print(f"[green]{line}[/green]")
        elif line.startswith("-"):
            console.print(f"[red]{line}[/red]")
        else:
            console.print(f"[dim]{line}[/dim]")


def print_evolution_report(report_data: dict) -> None:
    """
    Display complete code evolution report with programmatic unified diff,
    change summary, validation status, and benchmark comparisons.
    """
    if hasattr(report_data, "model_dump"):
        data = report_data.model_dump()
    elif hasattr(report_data, "dict"):
        data = report_data.dict()
    elif isinstance(report_data, dict):
        data = report_data
    else:
        data = dict(report_data)

    console.print()
    header_panel = Panel(
        Text("MUTAGEN -- CODE EVOLUTION REPORT", style="bold bright_cyan", justify="center"),
        border_style="bright_cyan",
        box=box.DOUBLE,
    )
    console.print(header_panel)

    project_name = data.get("project_name", data.get("file_path", "default"))
    exp_id = data.get("experiment_id", "-")
    gen_num = data.get("generation", 1)
    cand_id = data.get("candidate_id", "-")
    file_path = data.get("file_path", "source")

    console.print(f"[bold bright_magenta]Project:[/] [white]{project_name}[/]")
    console.print(f"[bold bright_magenta]Experiment:[/] [white]{exp_id}[/]")
    console.print(f"[bold bright_magenta]Generation:[/] [white]{gen_num}[/]")
    console.print(f"[bold bright_magenta]Candidate:[/] [white]{cand_id}[/]")
    console.print(f"\n[bold bright_magenta]Modified file:[/]\n    [white]{file_path}[/]\n")

    diff_text = data.get("diff_text", "")
    if diff_text:
        print_diff(diff_text)
    else:
        console.print("[dim]No source diff available.[/dim]")

    raw_summary = data.get("summary", {})
    if hasattr(raw_summary, "model_dump"):
        summary = raw_summary.model_dump()
    elif hasattr(raw_summary, "dict"):
        summary = raw_summary.dict()
    elif isinstance(raw_summary, dict):
        summary = raw_summary
    else:
        summary = {}

    console.print("\n[bold bright_cyan]CHANGE SUMMARY[/]")
    console.print("[dim]--------------[/]")
    console.print(f"Files changed: [bold]{summary.get('files_changed', 1)}[/]")
    console.print(f"Lines added: [bold green]+{summary.get('lines_added', 0)}[/]")
    console.print(f"Lines removed: [bold red]-{summary.get('lines_removed', 0)}[/]")
    console.print(f"Functions modified: [bold]{summary.get('functions_modified', 0)}[/]")
    if summary.get("modified_functions"):
        funcs = ", ".join(summary["modified_functions"])
        console.print(f"Modified functions: [dim]{funcs}[/dim]")

    console.print("\n[bold bright_cyan]VALIDATION[/]")
    console.print("[dim]----------[/]")
    val_passed = data.get("validation_passed", False)
    tests_passed = data.get("tests_passed", False)
    console.print(f"Syntax: [{'bold green' if val_passed else 'bold red'}]{'PASSED' if val_passed else 'FAILED'}[/]")
    console.print(f"Static analysis: [{'bold green' if val_passed else 'bold red'}]{'PASSED' if val_passed else 'FAILED'}[/]")
    console.print(f"Mandatory tests: [{'bold green' if tests_passed else 'bold red'}]{'PASSED' if tests_passed else 'FAILED'}[/]")

    console.print("\n[bold bright_cyan]BENCHMARK[/]")
    console.print("[dim]---------[/]")
    orig_time = data.get("baseline_median_time")
    cand_time = data.get("candidate_median_time")
    speed_imp = data.get("speed_improvement_percent")

    console.print(f"Original median runtime: [white]{f'{orig_time:.6f}s' if orig_time is not None else 'N/A'}[/]")
    console.print(f"Optimized median runtime: [white]{f'{cand_time:.6f}s' if cand_time is not None else 'N/A'}[/]")
    imp_str = f"{speed_imp:+.1f}%" if speed_imp is not None else "N/A"
    style = "bold green" if (speed_imp or 0) > 0 else ("bold red" if (speed_imp or 0) < 0 else "white")
    console.print(f"Runtime improvement: [{style}]{imp_str}[/]")

    console.print("\n[bold bright_cyan]STATUS[/]")
    console.print("[dim]------[/]")
    status_val = str(data.get("status", "VALID"))
    if data.get("is_eligible", False) or status_val.lower() in ("valid", "best_eligible", "succeeded"):
        console.print("[bold green]Candidate evaluated successfully.[/bold green]\n")
    else:
        reason = data.get("rejection_reason", "Candidate rejected during validation or testing.")
        console.print(f"[bold red]Candidate failed evaluation: {reason}[/bold red]\n")

    verif_json = data.get("verification_json")
    if verif_json:
        try:
            from mutagen.verification.report import format_verification_report
            console.print(format_verification_report(verif_json))
            console.print()
        except Exception:
            pass
    elif data.get("verification_verdict"):
        verdict = data.get("verification_verdict")
        style = "bold green" if verdict == "ACCEPT" else ("bold yellow" if verdict == "REVIEW" else "bold red")
        console.print(f"[bold bright_cyan]VERIFICATION VERDICT:[/] [{style}]{verdict}[/{style}]\n")

