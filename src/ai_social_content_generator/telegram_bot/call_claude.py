''' Connecting the bot with claude '''
import subprocess


def message_claude(prompt, timeout=300):
    try:
        result = subprocess.run(
            ["claude", "--print"],
            input=prompt,
            capture_output=True,
            text=True,
            timeout=timeout,
        )
    except subprocess.TimeoutExpired:
        return f"Claude Error: timed out after {timeout}s"

    if result.returncode != 0:
        result = f"Claude Error: {result.stderr}"
    return result
