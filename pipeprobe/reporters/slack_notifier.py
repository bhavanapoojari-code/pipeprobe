"""
EvalForge — Slack Notifier

Posts eval results and regression alerts to a Slack channel.
Designed for teams that want visibility into AI quality without
checking CI logs manually.

Setup
-----
1. Create a Slack app at https://api.slack.com/apps
2. Add the `chat:write` OAuth scope
3. Install to workspace and copy the Bot Token
4. Set SLACK_BOT_TOKEN and SLACK_CHANNEL env variables

Usage
-----
    from pipeprobe.reporters.slack_notifier import SlackNotifier

    notifier = SlackNotifier(channel="#data-ai-alerts")
    notifier.post_result(suite_result)
"""
from __future__ import annotations

import json
import os
from typing import Any
from urllib import request, error

from pipeprobe.models import EvalSuiteResult


class SlackNotifier:
    """
    Posts EvalForge results to a Slack channel via Webhook or Bot API.

    Parameters
    ----------
    channel:
        Slack channel name (e.g. "#data-ai-alerts"). Required for Bot API.
    webhook_url:
        Slack Incoming Webhook URL. Takes priority over Bot API if set.
        Set via SLACK_WEBHOOK_URL env var.
    bot_token:
        Slack Bot OAuth token (xoxb-...). Used if no webhook_url.
        Set via SLACK_BOT_TOKEN env var.
    notify_on:
        When to post. Options: "always", "failure_only", "regression_only".
    """

    API_URL = "https://slack.com/api/chat.postMessage"

    def __init__(
        self,
        channel: str = "#pipeprobe-alerts",
        webhook_url: str | None = None,
        bot_token: str | None = None,
        notify_on: str = "failure_only",
    ) -> None:
        self.channel = channel
        self.webhook_url = webhook_url or os.environ.get("SLACK_WEBHOOK_URL")
        self.bot_token = bot_token or os.environ.get("SLACK_BOT_TOKEN")
        self.notify_on = notify_on

        if not self.webhook_url and not self.bot_token:
            raise ValueError(
                "Set SLACK_WEBHOOK_URL or SLACK_BOT_TOKEN environment variable."
            )

    def post_result(self, suite: EvalSuiteResult) -> bool:
        """
        Post suite result to Slack if notify_on conditions are met.
        Returns True if message was sent.
        """
        should_notify = (
            self.notify_on == "always"
            or (self.notify_on == "failure_only" and suite.failed > 0)
            or (self.notify_on == "regression_only" and suite.regressions)
        )
        if not should_notify:
            return False

        blocks = self._build_blocks(suite)
        return self._send(blocks)

    def post_regression_alert(self, suite: EvalSuiteResult) -> bool:
        """Post a focused regression-only alert (shorter message)."""
        if not suite.regressions:
            return False
        blocks = self._build_regression_blocks(suite)
        return self._send(blocks)

    # ── Block builders ─────────────────────────────────────────────────────

    def _build_blocks(self, suite: EvalSuiteResult) -> list[dict[str, Any]]:
        icon = "✅" if suite.failed == 0 else "❌"
        status = "PASSED" if suite.failed == 0 else "FAILED"
        reg_text = (
            f"  |  *Regressions:* :rotating_light: {len(suite.regressions)}"
            if suite.regressions else ""
        )

        blocks: list[dict[str, Any]] = [
            {
                "type": "header",
                "text": {
                    "type": "plain_text",
                    "text": f"{icon} EvalForge — {suite.suite_name} — {status}",
                }
            },
            {
                "type": "section",
                "fields": [
                    {"type": "mrkdwn", "text": f"*Pass rate:*\n{suite.pass_rate:.1%}"},
                    {"type": "mrkdwn", "text": f"*Avg score:*\n{suite.avg_score:.2f}"},
                    {"type": "mrkdwn", "text": f"*Passed:*\n{suite.passed}/{suite.total}"},
                    {"type": "mrkdwn", "text": f"*Duration:*\n{suite.duration_seconds:.1f}s"},
                ]
            },
            {
                "type": "context",
                "elements": [
                    {
                        "type": "mrkdwn",
                        "text": (
                            f"Branch: `{suite.git_branch or 'unknown'}`  |  "
                            f"SHA: `{suite.git_sha[:8] if suite.git_sha else 'unknown'}`  |  "
                            f"Run: `{suite.run_id}`"
                            f"{reg_text}"
                        )
                    }
                ]
            },
        ]

        # Failed cases
        failed_results = [r for r in suite.results if r.verdict.value == "fail"]
        if failed_results:
            failed_lines = "\n".join(
                f"• `{r.case_id}` ({r.domain.value})  score: {r.overall_score:.2f}"
                + (f"  *▼ regression {r.delta:.1%}*" if r.regression else "")
                for r in failed_results[:8]  # cap at 8
            )
            blocks.append({
                "type": "section",
                "text": {
                    "type": "mrkdwn",
                    "text": f"*Failed cases:*\n{failed_lines}"
                }
            })

        blocks.append({"type": "divider"})
        return blocks

    def _build_regression_blocks(self, suite: EvalSuiteResult) -> list[dict[str, Any]]:
        reg_lines = "\n".join(
            f"• `{r.case_id}` — score {r.overall_score:.2f} (dropped {r.delta:.1%})"
            for r in suite.regressions[:6]
        )
        return [
            {
                "type": "header",
                "text": {
                    "type": "plain_text",
                    "text": f"⚠️ EvalForge — {len(suite.regressions)} regression(s) in {suite.suite_name}",
                }
            },
            {
                "type": "section",
                "text": {"type": "mrkdwn", "text": reg_lines}
            },
            {
                "type": "context",
                "elements": [{
                    "type": "mrkdwn",
                    "text": f"Branch: `{suite.git_branch}` | SHA: `{suite.git_sha[:8] if suite.git_sha else '?'}`"
                }]
            },
        ]

    # ── HTTP ───────────────────────────────────────────────────────────────

    def _send(self, blocks: list[dict[str, Any]]) -> bool:
        payload = json.dumps({
            "channel": self.channel,
            "blocks": blocks,
        }).encode()

        if self.webhook_url:
            req = request.Request(
                self.webhook_url,
                data=payload,
                headers={"Content-Type": "application/json"},
                method="POST",
            )
        else:
            req = request.Request(
                self.API_URL,
                data=payload,
                headers={
                    "Content-Type": "application/json",
                    "Authorization": f"Bearer {self.bot_token}",
                },
                method="POST",
            )

        try:
            with request.urlopen(req, timeout=10) as resp:
                body = json.loads(resp.read())
                return body.get("ok", True) if isinstance(body, dict) else True
        except error.URLError as e:
            print(f"[EvalForge] Slack notification failed: {e}")
            return False
