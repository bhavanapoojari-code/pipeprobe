"""
PipeProbe CLI

pipeprobe run  tests.yaml          — run a YAML suite
pipeprobe run  tests.yaml --html   — run + generate HTML report
pipeprobe diff dbt-rag             — show regression diff for last 2 runs
pipeprobe history dbt-rag          — show run history
pipeprobe init my-suite            — scaffold a YAML suite file
"""
from __future__ import annotations
import json, os, sys
from pathlib import Path
import typer
from rich.console import Console
from rich.table import Table
from rich.panel import Panel
from rich import box

app     = typer.Typer(name="pipeprobe", help="PipeProbe — LLM regression testing for data infrastructure AI.", no_args_is_help=True)
console = Console()


# ══════════════════════════════════════════════════════════════════════════════
# pipeprobe run tests.yaml
# ══════════════════════════════════════════════════════════════════════════════

@app.command()
def run(
    suite_file: Path  = typer.Argument(..., help="Path to YAML suite file, e.g. tests.yaml"),
    provider: str     = typer.Option("claude",  "--provider", "-p", help="Judge provider: claude | openai"),
    model: str        = typer.Option("",        "--model",    "-m", help="Override model from YAML"),
    reasoning: bool   = typer.Option(False,     "--reasoning","-r", help="Show per-metric judge reasoning"),
    no_save: bool     = typer.Option(False,     "--no-save",        help="Don't persist results (no regression tracking)"),
    html: bool        = typer.Option(False,     "--html",           help="Generate HTML report"),
    html_out: Path    = typer.Option(Path("pipeprobe-report.html"), "--html-out"),
    slack: bool       = typer.Option(False,     "--slack",          help="Post results to Slack (needs SLACK_WEBHOOK_URL)"),
    compare: bool     = typer.Option(True,      "--compare/--no-compare", help="Show regression diff vs previous run"),
) -> None:
    """Run a probe suite from a YAML file and report results."""
    if not suite_file.exists():
        console.print(f"[red]File not found:[/red] {suite_file}")
        raise typer.Exit(1)

    api_key_var = "ANTHROPIC_API_KEY" if provider == "claude" else "OPENAI_API_KEY"
    if not os.environ.get(api_key_var):
        console.print(f"[red]{api_key_var} not set.[/red]")
        raise typer.Exit(1)

    from pipeprobe.suite import Suite
    from pipeprobe.judges import get_judge

    judge_kwargs: dict = {"provider": provider}
    if model:
        judge_kwargs["model"] = model

    judge = get_judge(**judge_kwargs)
    suite = Suite.from_yaml(suite_file, judge=judge)
    console.print(f"\n[blue]Suite:[/blue] {suite_file}  ([dim]{len(suite._cases)} cases[/dim])")

    # We need an ai_fn — for YAML-driven runs it's supplied via a Python shim.
    # The YAML can specify: ai_module and ai_function keys.
    import yaml
    with open(suite_file) as f:
        raw: dict = yaml.safe_load(f)

    ai_module_path = raw.get("ai_module")
    ai_fn_name     = raw.get("ai_function", "run")

    if ai_module_path:
        import importlib.util
        spec   = importlib.util.spec_from_file_location("_ai_module", ai_module_path)
        module = importlib.util.module_from_spec(spec)      # type: ignore[arg-type]
        spec.loader.exec_module(module)                     # type: ignore[union-attr]
        ai_fn  = getattr(module, ai_fn_name)
    else:
        # No ai_module — use a stub that prints a clear error
        def ai_fn(question: str, context: dict) -> str:  # type: ignore[misc]
            return (
                f"[STUB] Add ai_module: path/to/your_ai.py and "
                f"ai_function: your_function_name to {suite_file} "
                f"to connect your real AI system."
            )
        console.print(
            "[yellow]⚠  No ai_module in YAML — running with stub responses.[/yellow]\n"
            "   Add [cyan]ai_module:[/cyan] path/to/your_ai.py to connect your AI system.\n"
        )

    result = suite.run(ai_fn, show_reasoning=reasoning, save=not no_save)

    if html:
        from pipeprobe.reporters.html_reporter import generate_html_report
        compare_data = suite.tracker.compare_summary(result)
        generate_html_report(result, compare_data, output_path=html_out)
        console.print(f"[green]HTML report →[/green] {html_out}")

    if slack:
        _post_slack(result)

    # CI exit code
    if result.regressions or result.failed > 0:
        raise typer.Exit(1)


# ══════════════════════════════════════════════════════════════════════════════
# pipeprobe diff <suite-name>
# ══════════════════════════════════════════════════════════════════════════════

@app.command()
def diff(
    suite_name: str = typer.Argument(..., help="Suite name to compare"),
    store: Path     = typer.Option(Path(".pipeprobe"), "--store"),
) -> None:
    """Show regression diff between the last two runs of a suite."""
    from pipeprobe.reporters.regression_tracker import RegressionTracker
    tracker = RegressionTracker(store_path=store)
    history = tracker.get_history(suite_name, limit=2)

    if len(history) < 2:
        console.print(f"[yellow]Need at least 2 runs to diff. Only {len(history)} found.[/yellow]")
        raise typer.Exit()

    curr, prev = history[0], history[1]

    t = Table(box=box.SIMPLE_HEAD, show_header=True, header_style="bold dim")
    t.add_column("Metric");  t.add_column("Previous", justify="right"); t.add_column("Current", justify="right"); t.add_column("Δ", justify="right")

    avg_delta = (curr["avg_score"] or 0) - (prev["avg_score"] or 0)
    delta_col = "green" if avg_delta >= 0 else "red"
    sign      = "+" if avg_delta >= 0 else ""

    t.add_row("Pass rate",
              f"{(prev['pass_rate'] or 0):.1%}", f"{(curr['pass_rate'] or 0):.1%}",
              f"[{delta_col}]{sign}{(curr['pass_rate'] or 0)-(prev['pass_rate'] or 0):+.1%}[/{delta_col}]")
    t.add_row("Avg score",
              f"{(prev['avg_score'] or 0):.3f}", f"{(curr['avg_score'] or 0):.3f}",
              f"[{delta_col}]{sign}{avg_delta:.3f}[/{delta_col}]")
    t.add_row("Regressions",
              str(prev.get("regressions", 0)), str(curr.get("regressions", 0)), "")
    t.add_row("Run ID",
              prev.get("run_id","?"), curr.get("run_id","?"), "")

    console.print(f"\n[bold]Diff:[/bold] {suite_name}")
    console.print(t)


# ══════════════════════════════════════════════════════════════════════════════
# pipeprobe history <suite-name>
# ══════════════════════════════════════════════════════════════════════════════

@app.command()
def history(
    suite_name: str = typer.Argument(..., help="Suite name"),
    limit: int      = typer.Option(10, "--limit", "-n"),
    store: Path     = typer.Option(Path(".pipeprobe"), "--store"),
) -> None:
    """Show run history for a suite."""
    from pipeprobe.reporters.regression_tracker import RegressionTracker
    tracker = RegressionTracker(store_path=store)
    runs    = tracker.get_history(suite_name, limit=limit)

    if not runs:
        console.print(f"[yellow]No history for '{suite_name}'[/yellow]")
        raise typer.Exit()

    t = Table(box=box.SIMPLE_HEAD, header_style="bold dim")
    t.add_column("Run ID", style="cyan"); t.add_column("Timestamp", style="dim")
    t.add_column("Pass rate", justify="center"); t.add_column("Avg score", justify="center")
    t.add_column("Passed", justify="center");   t.add_column("Failed", justify="center")
    t.add_column("Regressions", justify="center"); t.add_column("Branch", style="dim")

    for r in runs:
        pr  = r.get("pass_rate") or 0
        col = "green" if pr >= 0.8 else "yellow" if pr >= 0.6 else "red"
        reg = r.get("regressions", 0)
        t.add_row(
            r.get("run_id","?"),
            (r.get("timestamp") or "?")[:19],
            f"[{col}]{pr:.1%}[/{col}]",
            f"{r.get('avg_score') or 0:.3f}",
            str(r.get("passed",0)), str(r.get("failed",0)),
            f"[{'red' if reg else 'green'}]{reg}[/{'red' if reg else 'green'}]",
            r.get("git_branch","—"),
        )
    console.print(f"\n[bold]History:[/bold] {suite_name}")
    console.print(t)


# ══════════════════════════════════════════════════════════════════════════════
# pipeprobe init <name>
# ══════════════════════════════════════════════════════════════════════════════

@app.command()
def init(
    name: str       = typer.Argument("my-suite", help="Suite name"),
    directory: Path = typer.Option(Path("."), "--dir", "-d"),
    provider: str   = typer.Option("claude", "--provider", "-p", help="claude | openai"),
) -> None:
    """Scaffold a YAML suite + Python AI stub in the current directory."""
    probe_dir  = directory / "probes"
    probe_dir.mkdir(parents=True, exist_ok=True)

    yaml_file  = probe_dir / f"{name.replace('-','_')}.yaml"
    ai_file    = probe_dir / f"{name.replace('-','_')}_ai.py"
    model_name = "claude-sonnet-4-6" if provider == "claude" else "gpt-4o"

    yaml_file.write_text(f"""# PipeProbe suite — generated by: pipeprobe init {name}
# Run with: pipeprobe run {yaml_file}
# Docs:     https://github.com/yourusername/pipeprobe

name: {name}

judge:
  provider: {provider}
  model: {model_name}
  thresholds:
    faithfulness:     0.80
    correctness:      0.75
    domain_relevance: 0.70
    actionability:    0.65

regression_threshold: 0.05   # flag if score drops by >= 5%
fail_on_regression: true      # exit 1 in CI on regression

# Point to your AI system (optional — stub used if omitted)
# ai_module:   {ai_file}
# ai_function: run

cases:
  - id: example-dbt-001
    domain: dbt
    question: "Which models write to the orders table, in dependency order?"
    expected: "stg_orders → int_orders → fct_orders"
    tags: [lineage, critical]
    context:
      dbt_manifest_excerpt:
        fct_orders:   {{depends_on: [int_orders]}}
        int_orders:   {{depends_on: [stg_orders]}}
        stg_orders:   {{depends_on: [raw_orders]}}

  - id: example-airflow-001
    domain: airflow
    question: "What time does the orders_daily DAG run?"
    expected: "6:00 AM UTC daily (cron: '0 6 * * *')"
    tags: [airflow, schedule]
    context:
      dag_id: orders_daily
      schedule_interval: "0 6 * * *"
      timezone: UTC

  - id: example-sql-001
    domain: sql
    question: "How should I optimize this slow query?"
    expected: "Replace the correlated subquery with a JOIN. Add composite index on (customer_id, created_at)."
    tags: [sql, optimization]
    context:
      slow_query: "SELECT * FROM orders WHERE customer_id IN (SELECT id FROM customers WHERE region='US')"
      explain_plan: {{full_table_scan: true, estimated_rows: 4500000}}
""")

    ai_file.write_text(f'''"""
PipeProbe AI stub for suite: {name}
Replace the `run` function body with your actual AI system call.
"""
from typing import Any


def run(question: str, context: dict[str, Any]) -> str:
    """
    Your AI system goes here.
    PipeProbe calls this function for every test case in the suite.

    Parameters
    ----------
    question : The natural language question to answer.
    context  : Structured context from the YAML (dbt manifest, DAG config, etc.)

    Returns
    -------
    str — the AI system's answer (will be evaluated by the judge).
    """
    # ── Replace below with your actual system ──────────────────────────────
    # Example RAG call:
    # from my_rag import answer
    # return answer(question, context)

    # Example LangChain agent:
    # from my_agent import agent
    # return agent.run(question)

    return "Replace this stub with your real AI system."
''')

    # .gitignore
    gi = directory / ".gitignore"
    entry = ".pipeprobe/\n"
    if gi.exists():
        if ".pipeprobe" not in gi.read_text(): gi.write_text(gi.read_text() + entry)
    else:
        gi.write_text(entry)

    console.print(f"\n[green]✓ PipeProbe initialised[/green]")
    console.print(f"  Suite YAML : [cyan]{yaml_file}[/cyan]")
    console.print(f"  AI stub    : [cyan]{ai_file}[/cyan]")
    console.print(f"\nNext steps:")
    console.print(f"  1. Edit [cyan]{yaml_file}[/cyan] — adjust cases + thresholds")
    console.print(f"  2. Fill [cyan]{ai_file}[/cyan] — point to your real AI system")
    console.print(f"  3. Set  [yellow]{'ANTHROPIC_API_KEY' if provider=='claude' else 'OPENAI_API_KEY'}[/yellow]")
    console.print(f"  4. Run  [bold]pipeprobe run {yaml_file}[/bold]\n")


# ── Helpers ────────────────────────────────────────────────────────────────────

def _post_slack(result: object) -> None:
    try:
        from pipeprobe.reporters.slack_notifier import SlackNotifier
        n = SlackNotifier(notify_on="always")
        n.post_result(result)      # type: ignore[arg-type]
        console.print("[green]Slack notification sent.[/green]")
    except Exception as e:
        console.print(f"[yellow]Slack skipped: {e}[/yellow]")


if __name__ == "__main__":
    app()
