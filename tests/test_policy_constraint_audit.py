import vera_assurance


def test_policy_constraint_audit_detects_delegation_laundering():
    assert hasattr(vera_assurance, "audit_policy_constraints"), (
        "vera_assurance must expose the policy-constraint audit seam"
    )

    report = vera_assurance.audit_policy_constraints(
        "Operators must not delete customer records.\n"
        "Operators may ask support to delete customer records."
    )

    findings = [f for f in report.findings if f.category == "delegation_laundering"]
    assert len(findings) == 1
    finding = findings[0]
    assert finding.target_effect == "delete:customer records"
    assert finding.rule_ids == ("R0001", "R0002")
    assert finding.source_lines == (1, 2)
