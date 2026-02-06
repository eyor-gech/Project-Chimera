from runtime.orchestrator import run_chimera

def test_orchestration_flow():
    result = run_chimera(platform="YouTube", limit=1)

    assert "trends" in result
    assert "drafts" in result
    assert "approvals" in result
