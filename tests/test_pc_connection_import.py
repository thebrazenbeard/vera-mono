import pc_connection


def test_pc_connection_package_is_local_and_importable():
    assert hasattr(pc_connection, "PHASE_ONE_OPERATIONS")
    assert isinstance(pc_connection.PHASE_ONE_OPERATIONS, frozenset)
