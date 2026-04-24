"""PipeProbe — Rich terminal reporter with regression diff output."""
from __future__ import annotations
from rich.console import Console
from rich.panel import Panel
from rich.table import Table
from rich.text import Text
from rich import box
from pipeprobe.models import SuiteResult, Verdict

console = Console()


def print_suite_result(
    suite: SuiteResult,
    compare: dict | None = None,
    show_reasoning: bool = False,
) -> None:
    _print_header(suite)
    if compare and compare.get("has_baseline"):
        _print_comparison(compare)
    _print_table(suite, show_reasoning)
    if suite.regressions:
        _print_regressions(suite)
    _print_summary(suite)


# ── Sections ───────────────────────────────────────────────────────────────────

def _print_header(suite: SuiteResult) -> None:
    console.print()
    console.print(Panel(
        f"[bold]PipeProbe[/bold]  [cyan]{suite.suite_name}[/cyan]\n"
        f"run [dim]{suite.run_id}[/dim]  ·  "
        f"branch [dim]{suite.git_branch or 'local'}[/dim]  ·  "
        f"sha [dim]{suite.git_sha[:8] if suite.git_sha else 'n/a'}[/dim]  ·  "
        f"[dim]{suite.duration_seconds:.1f}s[/dim]",
        border_style="blue",
    ))


def _print_comparison(compare: dict) -> None:
    """Print a before/after diff table — the key CI feature."""
    avg_delta  = compare.get("avg_delta", 0)
    delta_sign = "+" if avg_delta >= 0 else ""
    delta_col  = "green" if avg_delta >= 0 else "red"
    regressed  = compare.get("regressed", [])
    improved   = compare.get("improved", [])

    lines = [
        f"[bold]vs run {compare.get('prev_run_id')}[/bold]  "
        f"avg score: [dim]{compare.get('prev_avg'):.3f}[/dim] → "
        f"[bold]{compare.get('curr_avg'):.3f}[/bold]  "
        f"([{delta_col}]{delta_sign}{avg_delta:.3f}[/{delta_col}])"
    ]
    if regressed:
        lines.append(f"[red]▼ Regressions ({len(regressed)}):[/red]  " +
                     "  ".join(f"[red]{r['case_id']} {r['delta']:+.2f}[/red]" for r in regressed))
    if improved:
        lines.append(f"[green]▲ Improved ({len(improved)}):[/green]  " +
                     "  ".join(f"[green]{i['case_id']} {i['delta']:+.2f}[/green]" for i in improved))

    console.print(Panel("\n".join(lines), title="[bold]Regression comparison[/bold]",
                        border_style="red" if regressed else "green"))


def _print_table(suite: SuiteResult, show_reasoning: bool) -> None:
    t = Table(box=box.SIMPLE_HEAD, show_header=True, header_style="bold dim", expand=True)
    t.add_column("Case ID",       style="cyan", no_wrap=True, width=20)
    t.add_column("Domain",        width=10)
    t.add_column("Score",         justify="center", width=7)
    t.add_column("Δ",             justify="center", width=8)
    t.add_column("Verdict",       justify="center", width=9)
    t.add_column("Judge",         width=8)
    t.add_column("Failed metrics",width=28)

    for r in suite.results:
        failed = ", ".join(m.name for m in r.failed_metrics) or "—"
        t.add_row(
            r.case_id, r.domain.value,
            _score_text(r.overall_score),
            _delta_text(r.delta, r.regression),
            _verdict_text(r.verdict),
            r.judge_provider,
            failed,
        )
        if show_reasoning:
            for m in r.metrics:
                icon   = "✓" if m.passed else "✗"
                colour = "green" if m.passed else "red"
                console.print(
                    f"    [{colour}]{icon}[/{colour}] [dim]{m.name}[/dim] "
                    f"({m.score:.2f}): {m.reasoning[:110]}"
                )
    console.print(t)


def _print_regressions(suite: SuiteResult) -> None:
    lines = "\n".join(
        f"[red]▼ REGRESSION[/red]  [cyan]{r.case_id}[/cyan]  "
        f"[dim]{r.prev_score:.2f}[/dim] → [bold red]{r.overall_score:.2f}[/bold red]  "
        f"([bold red]{r.delta:.1%}[/bold red])"
        for r in suite.regressions
    )
    console.print(Panel(lines, title="[bold red]Regressions detected[/bold red]",
                        border_style="red"))


def _print_summary(suite: SuiteResult) -> None:
    ok = suite.failed == 0
    status_col = "green" if ok else "red"
    pr_col     = "green" if suite.pass_rate >= 0.8 else "yellow" if suite.pass_rate >= 0.6 else "red"
    console.print()
    console.print(Panel(
        f"[{status_col}][bold]{'✓ PASSED' if ok else '✗ FAILED'}[/bold][/{status_col}]  "
        f"[{pr_col}]{suite.passed}/{suite.total} passed ({suite.pass_rate:.1%})[/{pr_col}]  ·  "
        f"avg score [bold]{suite.avg_score:.3f}[/bold]  ·  "
        f"regressions [{'red' if suite.regressions else 'green'}]"
        f"{len(suite.regressions)}[/{'red' if suite.regressions else 'green'}]",
        border_style=status_col,
    ))
    console.print()


# ── Helpers ────────────────────────────────────────────────────────────────────

def _score_text(s: float) -> Text:
    col = "green" if s >= 0.8 else "yellow" if s >= 0.6 else "red"
    return Text(f"{s:.3f}", style=col)

def _delta_text(d: float, regression: bool) -> Text:
    if d == 0.0: return Text("—", style="dim")
    sign  = "+" if d > 0 else ""
    style = "bold red" if regression else "green" if d > 0 else "dim"
    return Text(f"{sign}{d:.1%}", style=style)

def _verdict_text(v: Verdict) -> Text:
    m = {Verdict.PASS: ("✓ pass","green"), Verdict.FAIL: ("✗ fail","red"),
         Verdict.WARN: ("⚠ warn","yellow"), Verdict.SKIP: ("– skip","dim")}
    label, col = m.get(v, ("?","white"))
    return Text(label, style=col)
