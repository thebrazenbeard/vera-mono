from __future__ import annotations

import pytest

from research.goal1_acceptance_bridge.full_qvr_stdio_broker import (
    build_command,invoke_with_host_callback,VOLUME
)

IMAGE="sha256:"+"a"*64
VOLUME_NAME="goal1-qvr-contract-test"

def test_full_qvr_process_is_networkless_with_only_named_state_volume():
    args=build_command(IMAGE,VOLUME_NAME)
    for flag in ("--pull=never","--network=none","--read-only","--cap-drop=ALL",
                 "--security-opt=no-new-privileges","--user=65534:65534",
                 "--ipc=private","-i"):
        assert flag in args
    assert "--mount=type=volume,src="+VOLUME_NAME+",dst=/state" in args
    assert args[args.index("-i")+1]==IMAGE
    assert not any(flag in args for flag in (
        "--privileged","--network=host","-v","-p","--publish","--device",
        "--env","-e","--pid=host"))
    assert not any("docker.sock" in item for item in args)

@pytest.mark.parametrize("volume",[
    "",None,"state","goal1-qvr-../escape","goal1-qvr-test/other",
    "goal1-qvr-test,readonly","goal1-qvr-TEST",
    "goal1-qvr-"+("x"*60)
])
def test_unsafe_volume_names_fail_before_container(volume):
    with pytest.raises(ValueError):
        build_command(IMAGE,volume)

@pytest.mark.parametrize("image",["python:3.12-slim","sha256:bad",None])
def test_image_tag_or_bad_id_disallowed(image):
    with pytest.raises(ValueError):
        build_command(image,VOLUME_NAME)

@pytest.mark.parametrize("prompt,invocation,tokens",[
    ("","good",3),("x","",3),("x","good",0),
    ("x","good",129),("x","good",True),
    ("x"*4097,"good",3)
])
def test_bad_invocation_rejected_before_dispatch(prompt,invocation,tokens):
    with pytest.raises(ValueError):
        invoke_with_host_callback(image_id=IMAGE,volume=VOLUME_NAME,
            prompt=prompt,model="test",digest="a"*64,
            invocation_id=invocation,max_tokens=tokens,callback=lambda **k:{})
