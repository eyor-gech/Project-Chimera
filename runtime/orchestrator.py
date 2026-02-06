from skills.skill_fetch_trends import fetch_trends
from skills.skill_generate_content import generate_content
from skills.skill_approve_content import approve_content

def run_chimera(platform: str, limit: int = 5):
    trends = fetch_trends(platform=platform, limit=limit)

    drafts = []
    for trend in trends:
        draft = generate_content(
            trend_id=trend["trend_id"],
            platform=platform
        )
        drafts.append(draft)

    approvals = []
    for draft in drafts:
        approval = approve_content(draft_id=draft["draft_id"])
        approvals.append(approval)

    return {
        "trends": trends,
        "drafts": drafts,
        "approvals": approvals
    }
