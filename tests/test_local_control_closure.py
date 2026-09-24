from vera_control.local_profile import (
    R10_SOURCE_CLOSURE,
    git_blob_sha,
    local_r10_source_paths,
    portable_text_git_blob_sha,
    validate_local_r10_source_closure,
)


def test_r10_control_source_cut_is_closed_inside_monorepo():
    assert validate_local_r10_source_closure() == ()
    paths = local_r10_source_paths()
    assert len(paths) == len(R10_SOURCE_CLOSURE)
    assert "FULL_OWNER" in paths
    assert "BUS_TOPOLOGY_OWNER" in paths
    assert all(path.is_file() for path in paths.values())


def test_control_source_blob_identity_is_stable_across_crlf_checkout():
    lf = b"line one\nline two\n"
    crlf = b"line one\r\nline two\r\n"
    assert portable_text_git_blob_sha(crlf) == git_blob_sha(lf)
