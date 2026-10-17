"""Exact Win32 no-GC ownership test across an entire QualifiedVeraRuntime.

All changes are confined to disposable test state. Does not create an owner
lease, memory promotion, effect permission, or model provider.
"""
from pathlib import Path
import os
import subprocess
import sys

import pytest

from vera_core import QualifiedVeraRuntime, VeraStateDirectory


@pytest.mark.skipif(os.name != "nt", reason="Win32 live-handle replace denial")
def test_all_qualified_mono_sqlite_files_are_released_while_runtime_is_live(tmp_path):
    state=VeraStateDirectory(tmp_path/"vera-state",
                             project_id="veraos",identity_id="VERA")
    runtime=QualifiedVeraRuntime.from_state_directory(state)
    files=sorted(state.paths.root.rglob("*.sqlite"))+sorted(
        state.paths.root.rglob("*.sqlite3"))
    assert len(files)>=20
    # The runtime and all store references remain live, and gc.collect is
    # deliberately forbidden here. Closed transactions must close handles.
    for p in files:
        alt=p.with_name(p.name+".close-check")
        os.replace(p,alt)
        os.replace(alt,p)
    assert runtime.tasks.path.is_file()
    # Cold instantiation must not depend on stale process-only open handles.
    reopened=QualifiedVeraRuntime.from_state_directory(state)
    assert reopened.tasks.path==runtime.tasks.path
    for p in files:
        alt=p.with_name(p.name+".reopen-check")
        os.replace(p,alt)
        os.replace(alt,p)
    child=subprocess.run(
        [sys.executable,"-c",
         "import sqlite3,sys; c=sqlite3.connect(sys.argv[1]);"
         "print(c.execute('select count(*) from sqlite_master').fetchone()[0]);c.close()",
         str(state.paths.tasks)],
        text=True,capture_output=True,timeout=15)
    assert child.returncode==0,child.stderr
    assert int(child.stdout.strip())>0
