"""PipeProbe judges — pick any, swap freely."""
from pipeprobe.judges.base import BaseJudge
from pipeprobe.judges.claude_judge import ClaudeJudge

def get_judge(provider: str = "claude", **kwargs: object) -> BaseJudge:
    """
    Factory — returns the right judge for the given provider string.
    Used by the CLI so YAML suites can declare: judge: openai

    Supported providers: 'claude', 'openai'
    """
    if provider == "claude":
        return ClaudeJudge(**kwargs)  # type: ignore[arg-type]
    if provider == "openai":
        from pipeprobe.judges.openai_judge import OpenAIJudge
        return OpenAIJudge(**kwargs)  # type: ignore[arg-type]
    raise ValueError(f"Unknown judge provider: {provider!r}. Choose 'claude' or 'openai'.")

__all__ = ["BaseJudge", "ClaudeJudge", "get_judge"]
