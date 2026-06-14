''' Connecting the bot with claude '''
import asyncio
from dataclasses import dataclass


@dataclass
class ClaudeResult:
    stdout: str
    stderr: str
    returncode: int


# Claude Code 2.1.154 switched to a "lean" default system prompt and started
# reserving multi-choice clarification responses for ambiguous input. The
# bot's SKILL templates piped over stdin look ambiguous under that default,
# so the CLI replies with "I see you've pasted the prompt — what would you
# like me to do?" instead of executing. This suffix re-primes the model to
# treat the piped message as a task to run, restoring pre-2.1.154 behavior.
_EXECUTION_PRIMING = (
    "You are being invoked by an automated script via stdin. "
    "The user message is a complete prompt template to execute as-is, "
    "not a paste asking for help. Do not ask clarifying questions, do "
    "not summarize, do not offer alternatives. Produce only the "
    "structured output described in the prompt."
)


async def message_claude(prompt, timeout=300, image_dir: str | None = None):
    """Run the Claude CLI on a prompt over stdin. When image_dir is set,
    grant the CLI read access to that directory so the prompt can
    reference local frame files (vision). The text path (image_dir None)
    is byte-identical to before."""
    args = [
        "claude",
        "--print",
        "--append-system-prompt",
        _EXECUTION_PRIMING,
    ]
    if image_dir:
        # Verified on the VPS: this exact flag combo lets --print read
        # local images without stalling on the file-permission gate and
        # without an API key.
        args += [
            "--add-dir", image_dir,
            "--permission-mode", "dontAsk",
            "--allowedTools", "Read",
        ]

    process = await asyncio.create_subprocess_exec(
        *args,
        stdin=asyncio.subprocess.PIPE,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )

    try:
        stdout_bytes, stderr_bytes = await asyncio.wait_for(
            process.communicate(input=prompt.encode("utf-8")),
            timeout=timeout,
        )
    except asyncio.TimeoutError:
        process.kill()
        await process.wait()
        return ClaudeResult(
            stdout="",
            stderr=f"Timed out after {timeout}s",
            returncode=-1,
        )

    return ClaudeResult(
        stdout=stdout_bytes.decode("utf-8", errors="replace"),
        stderr=stderr_bytes.decode("utf-8", errors="replace"),
        returncode=process.returncode if process.returncode is not None else -1,
    )
