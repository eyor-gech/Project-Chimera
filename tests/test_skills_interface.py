from skills.skill_generate_content import generate_content
from skills.skill_approve_content import approve_content

def test_generate_content_contract():
    draft = generate_content(trend_id="123", platform="YouTube")
    assert "draft_id" in draft
    assert "content_text" in draft
    assert "platform_format_valid" in draft


def test_approve_content_contract():
    approval = approve_content(draft_id="abc")
    assert "status" in approval
    assert approval["status"] in ["approved", "rejected", "needs_review"]
    