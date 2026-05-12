''' Connecting the bot with claude '''
import subprocess

def message_claude(prompt):
    result = subprocess.run(

        ["claude", "--print"],
        input=prompt,
        capture_output=True,
        text=True,
        timeout=60,
    )

    if result.returncode != 0:
        result = f"Claude Error: {result.stderr}"
    return result