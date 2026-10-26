"""Create a clean, exact-source disposable QVR image build context.

Uses git archive so no untracked host secrets, local .env, build output, or
dirty checkout modifications enter Docker. Overlays ONLY the three source
blobs of frozen Integration PR #82 after exact-byte SHA256 verification.
Must point at the Vera-owned PR89 working branch; will not fetch/write source.
"""
from __future__ import annotations

import argparse
import hashlib
import io
from pathlib import Path
import subprocess
import tarfile

OWNER_BRANCH="research/goal1-crossbranch-acceptance-20261023"
QVR82="26271c5d69dee4663e07d4dbcf63efcf033626e8"
SOURCES={
"qualified_runtime.py":"0466d85a19519f1e2c77fd51cf2f4d60964ecd9d57434c7a5b8a4e8472feb714",
"local_cognition.py":"b6820102bc569081f6bc298936970d3bb58406171298cc9d9b254a626646c14d",
"local_cognition_journal.py":"4bff14c593c58dd5e328a02ad00d4f583dac4a04f6b55aa1ccebbe8adbee5351",
}

def create_context(source: Path, destination: Path) -> dict:
    source=source.resolve()
    destination=destination.resolve()
    if destination.exists():
        raise ValueError("destination already exists; no overwrites")
    branch=subprocess.check_output(
        ["git","-C",str(source),"branch","--show-current"],text=True).strip()
    if branch!=OWNER_BRANCH:
        raise ValueError("expected isolated PR89 checkout, not main or peer branch")
    head=subprocess.check_output(["git","-C",str(source),"rev-parse","HEAD"],text=True).strip()
    archive=subprocess.check_output(["git","-C",str(source),"archive","--format=tar","HEAD"])
    data={}
    for name,want in SOURCES.items():
        path="packages/vera_core/src/vera_core/"+name
        blob=subprocess.check_output(["git","-C",str(source),"show",QVR82+":"+path])
        digest=hashlib.sha256(blob).hexdigest()
        if digest!=want:
            raise ValueError("Integration #82 source changed: "+name)
        data[path]=blob
    # No extraction prior to all source validations passing.
    destination.mkdir(parents=True)
    with tarfile.open(fileobj=io.BytesIO(archive),mode="r:") as tf:
        tf.extractall(destination,filter="data")
    for path,blob in data.items():
        target=destination/path
        # Two of the three #82 modules do not exist on canonical main.
        # They are new source files, not missing/corrupt archive members.
        if path.endswith("qualified_runtime.py") and not target.is_file():
            raise ValueError("QVR root module missing from tracked archive")
        target.parent.mkdir(parents=True,exist_ok=True)
        target.write_bytes(blob)
    return {"owner_head":head,"qvr82_commit":QVR82,
            "source_sha256":SOURCES,"context":str(destination),
            "contains_untracked_checkout_files":False,
            "production_route_selected":False}

def main():
    parser=argparse.ArgumentParser()
    parser.add_argument("--source",type=Path,required=True)
    parser.add_argument("--destination",type=Path,required=True)
    args=parser.parse_args()
    import json
    print(json.dumps(create_context(args.source,args.destination),sort_keys=True))

if __name__=="__main__":
    main()
