import subprocess

result = subprocess.run(

    ["claude", "--print", "What is the number of the meaning of the universe? reply with only the number."],
    capture_output=True,
    text=True,
    timeout=30,
)

print("stdout: ", repr(result.stdout))
print("stderr:", repr(result.stderr))
print("exit code:", result.returncode)