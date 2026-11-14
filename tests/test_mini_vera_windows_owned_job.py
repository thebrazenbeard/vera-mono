"""Real Windows parent-kill subprocess regression: test-owned child only."""
from __future__ import annotations

import ctypes
import os
from pathlib import Path
import signal
import subprocess
import sys
import tempfile
import time
import unittest


def _running(pid: int) -> bool:
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel32.OpenProcess.argtypes = [ctypes.c_uint32, ctypes.c_int, ctypes.c_uint32]
    kernel32.OpenProcess.restype = ctypes.c_void_p
    kernel32.WaitForSingleObject.argtypes = [ctypes.c_void_p, ctypes.c_uint32]
    kernel32.WaitForSingleObject.restype = ctypes.c_uint32
    kernel32.CloseHandle.argtypes = [ctypes.c_void_p]
    kernel32.CloseHandle.restype = ctypes.c_int
    handle = kernel32.OpenProcess(0x00100000, 0, pid)
    if not handle:
        return False
    try:
        return kernel32.WaitForSingleObject(handle, 0) == 0x102
    finally:
        kernel32.CloseHandle(handle)


@unittest.skipUnless(sys.platform == "win32", "Windows Job Object semantics only")
class KillOnCloseWindowsJobTests(unittest.TestCase):
    def test_abrupt_python_parent_termination_kills_only_its_job_child(self):
        with tempfile.TemporaryDirectory() as tmp:
            sentinel = Path(tmp) / "owned-child.pid"
            code = (
                "import pathlib,subprocess,sys,time\n"
                "from tools.mini_vera.windows_owned_job import KillOnCloseJob\n"
                "job=KillOnCloseJob()\n"
                "child=subprocess.Popen([sys.executable,'-B','-c',"
                "'import time;time.sleep(70)'],stdin=subprocess.DEVNULL,"
                "stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL,"
                "creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))\n"
                "job.bind(child.pid)\n"
                "pathlib.Path(sys.argv[1]).write_text(str(child.pid))\n"
                "while True: time.sleep(0.2)\n"
            )
            parent = subprocess.Popen(
                [sys.executable, "-B", "-c", code, str(sentinel)],
                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                stdin=subprocess.DEVNULL, cwd=Path(__file__).resolve().parents[1],
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
            child_pid = None
            try:
                deadline = time.monotonic() + 6
                while time.monotonic() < deadline and not sentinel.exists():
                    self.assertIsNone(parent.poll(), "owned parent exited before binding")
                    time.sleep(0.1)
                self.assertTrue(sentinel.exists(), "owned child not created")
                child_pid = int(sentinel.read_text())
                self.assertTrue(_running(child_pid), "synthetic child did not start")
                parent.kill()
                parent.wait(timeout=4)
                deadline = time.monotonic() + 5
                while time.monotonic() < deadline and _running(child_pid):
                    time.sleep(0.1)
                self.assertFalse(_running(child_pid),
                                 "job must terminate only owned child when parent killed")
            finally:
                if parent.poll() is None:
                    parent.kill()
                    parent.wait(timeout=4)
                if child_pid is not None and _running(child_pid):
                    # Scope: synthetic child PID from our private sentinel only.
                    os.kill(child_pid, signal.SIGTERM)


if __name__ == "__main__":
    unittest.main()
