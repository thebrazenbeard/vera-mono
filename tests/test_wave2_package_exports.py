def test_wave2_primitives_are_exposed_on_package_surfaces():
    import vera_core
    import vera_memory

    for name in (
        "SemanticTransferCatalog",
        "plan_catalog_semantic_transfer",
        "TaskWakeScheduler",
        "PortfolioSystemModel",
        "PrequentialCase",
        "evaluate_prequential",
        "RepairCase",
        "SimulationState",
    ):
        assert hasattr(vera_core, name), name

    for name in (
        "LearnedInfluenceGate",
        "LearnedRevision",
        "ReviewDisposition",
    ):
        assert hasattr(vera_memory, name), name
