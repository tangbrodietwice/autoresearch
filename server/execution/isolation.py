"""Restricted subprocesses for model-generated project code on macOS."""
import json
import os
from pathlib import Path
import signal
import subprocess
import sys


SYSTEM_READ = (
    "/System", "/usr", "/bin", "/sbin", "/Library/Apple", "/Library/Developer/CommandLineTools",
    "/Applications/Xcode.app", "/Library/Frameworks/Python.framework",
    "/opt/homebrew", "/usr/local", "/private/var/db/timezone",
)
PATH = "/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin"


def isolation_available():
    return sys.platform == "darwin" and Path("/usr/bin/sandbox-exec").is_file()


def rule(operation, paths, filter_name="subpath"):
    return f"(allow {operation} " + " ".join(
        f"({filter_name} {json.dumps(str(path), ensure_ascii=False)})" for path in paths
    ) + ")"


def run_isolated(argv, *, cwd, home, read, write, env, log, lock_fd):
    if not isolation_available():
        raise ValueError("当前系统没有可用的本机隔离执行器，已停止运行候选代码。")
    # Use the canonical macOS /private paths for the stage directories.
    writable = tuple(Path(path).resolve() for path in (*write, home))
    readable = tuple(Path(path).resolve() for path in (cwd, *read)) + writable
    system = (*SYSTEM_READ, *(Path(path).resolve() for path in SYSTEM_READ))
    traverse = {parent for path in (*readable, *map(Path, system)) for parent in path.parents} | {Path("/private/etc")}
    profile = "\n".join((
        "(version 1)", "(deny default)", "(allow process-fork process-exec sysctl-read)",
        rule("file-read*", (*system, *readable)),
        rule("file-read-metadata", sorted(traverse), "literal"),
        rule("file-read*", ("/", "/dev/null", "/dev/urandom", "/private/etc/localtime"), "literal"),
        rule("file-write*", writable),
    ))
    environment = {"PATH": PATH, "HOME": str(home), "TMPDIR": str(home), "LANG": "en_US.UTF-8",
                   "PYTHONDONTWRITEBYTECODE": "1", **env}
    # A trusted monitor owns the lease while the command runs. The candidate
    # never gets the lease descriptor, even if the training worker is killed.
    request = {"command": ["/usr/bin/sandbox-exec", "-p", profile, *argv],
               "cwd": str(cwd), "env": environment}
    subprocess.run([sys.executable, "-I", str(Path(__file__).resolve())],
                   input=json.dumps(request), text=True, stdout=log, stderr=log,
                   pass_fds=(lock_fd,), start_new_session=True, check=True)


def monitor(request):
    with subprocess.Popen(request["command"], cwd=request["cwd"], env=request["env"],
                          stdin=subprocess.DEVNULL, start_new_session=True) as process:
        try:
            return process.wait(timeout=600)
        finally:
            # Remove descendants before the next stage starts with different permissions.
            try:
                os.killpg(process.pid, signal.SIGKILL)
            except ProcessLookupError:
                pass


if __name__ == "__main__":
    try:
        status = monitor(json.load(sys.stdin))
    except subprocess.TimeoutExpired:
        print("Isolated command timed out.", file=sys.stderr)
        status = 124
    sys.exit(status if status >= 0 else 128 - status)
