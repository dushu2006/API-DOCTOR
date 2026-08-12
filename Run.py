import os
import sys
import subprocess
import time

def main():
    """Launch the backend and the run/trigger script in two consoles.

    On Windows this uses CREATE_NEW_CONSOLE so each process appears in its own
    terminal window. On other platforms both processes are launched and their
    output streams are prefixed and printed to the current terminal.
    """
    repo_root = os.path.dirname(__file__)
    backend_script = os.path.join(repo_root, "api-doctor-backend", "run.py")
    trigger_script = os.path.join(repo_root, "auto_trigger.py")

    if os.name == "nt":
        # Windows: open two new consoles
        creation_flags = subprocess.CREATE_NEW_CONSOLE
        print("Starting backend in a new console...")
        subprocess.Popen([sys.executable, backend_script], creationflags=creation_flags)
        # give backend a moment to start
        time.sleep(1)
        print("Starting trigger runner in a new console...")
        subprocess.Popen([sys.executable, trigger_script], creationflags=creation_flags)
        print("Launched two consoles. Check the new windows for output.")
    else:
        # POSIX: stream both outputs here
        print("Starting backend (streaming output)...")
        backend = subprocess.Popen([sys.executable, backend_script], stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
        print("Starting trigger runner (streaming output)...")
        trigger = subprocess.Popen([sys.executable, trigger_script], stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)

        def stream(prefix, stream_obj):
            for line in stream_obj:
                print(f"[{prefix}] {line}", end="")

        # Simple streaming loop: interleave lines from both processes.
        try:
            while True:
                if backend.stdout is not None:
                    line = backend.stdout.readline()
                    if line:
                        print(f"[BACKEND] {line}", end="")
                if trigger.stdout is not None:
                    line = trigger.stdout.readline()
                    if line:
                        print(f"[RUNNER] {line}", end="")
                # break when both have exited and no more output
                if backend.poll() is not None and trigger.poll() is not None:
                    break
                time.sleep(0.05)
        except KeyboardInterrupt:
            print("Stopping child processes...")
            for p in (backend, trigger):
                try:
                    p.terminate()
                except Exception:
                    pass


if __name__ == "__main__":
    main()
