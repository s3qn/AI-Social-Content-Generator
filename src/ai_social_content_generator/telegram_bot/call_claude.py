''' Connecting the bot with claude '''
import asyncio
from dataclasses import dataclass


@dataclass
class ClaudeResult:
    stdout: str
    stderr: str
    returncode: int


async def message_claude(prompt, timeout=300):
    process = await asyncio.create_subprocess_exec(
        "claude",
        "--print",
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
