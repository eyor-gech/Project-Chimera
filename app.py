import streamlit as st
import time

try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass

from runtime.orchestrator import run_chimera

st.set_page_config(page_title="Chimera Agent", page_icon="🤖", layout="wide")

st.title("🤖 Project Chimera - Autonomous AI Influencer")
st.markdown("Spec-Driven Development · Skill Orchestration · Human-in-the-Loop Governance")

with st.sidebar:
    st.header("Settings")
    platform = st.selectbox("Platform", ["Twitter", "YouTube", "Instagram"])
    limit = st.slider("Number of Trends", 1, 5, 1)
    use_real = st.checkbox("Fetch Live Trends (HackerNews)", value=True)
    generate = st.button("Run Pipeline", type="primary", use_container_width=True)
    
    st.markdown("---")
    st.caption(
        "Generation uses your local Ollama model when reachable, otherwise "
        "the deterministic offline stub. Each draft shows which was used."
    )

if generate:
    with st.spinner("Executing pipeline..."):
        logs = []
        log_placeholder = st.empty()
        
        def ui_logger(entry):
            event = entry.get("event")
            stage = entry.get("stage")
            logs.append(f"`[{stage}] {event}`")
            log_placeholder.markdown("\n".join(logs))

        try:
            start_time = time.time()
            result = run_chimera(
                platform=platform,
                limit=limit,
                logger=ui_logger,
                use_real_api=use_real
            )
            elapsed = time.time() - start_time
            
            log_placeholder.empty()
            st.success(f"Pipeline completed in {elapsed:.2f}s")

            summary = result.get("summary", {})
            live_count = summary.get("live_llm_drafts", 0)
            draft_count = summary.get("drafts", 0)
            if live_count:
                st.info(f"Live model served {live_count}/{draft_count} draft(s).")
            else:
                st.warning(
                    f"All {draft_count} draft(s) came from the offline stub - "
                    "no live model was reachable. Check the Ollama URL and "
                    "CHIMERA_LLM_TIMEOUT in .env."
                )

            grounded_count = sum(
                1 for d in result["drafts"] if d.get("grounded_on_source")
            )
            if grounded_count:
                st.info(
                    f"Grounded in source content/comments: {grounded_count}/{draft_count} draft(s)."
                )
            else:
                st.caption(
                    "No source material was available, so drafts were written "
                    "from the trend headline alone."
                )

            st.subheader("1. Discovered Trends")
            for t in result["trends"]:
                st.write(f"📈 **{t['title']}** (Score: {t['score']})")

            st.subheader("2. Generated Content & 3. Governance Approval")
            for i, draft in enumerate(result["drafts"]):
                approval = result["approvals"][i]
                trend = result["trends"][i] if i < len(result["trends"]) else {}

                with st.expander(f"Draft: {draft.get('topic', 'Untitled')} - {approval['workflow_status']}", expanded=True):
                    mode = draft.get("generation_mode", "unknown")
                    if mode == "live-llm":
                        st.success(f"Live model: {draft.get('generated_by', 'unknown')}")
                    else:
                        st.warning(f"Offline stub (no live model used): {draft.get('generated_by', 'unknown')}")

                    st.markdown(f"**Headline:** {draft.get('headline', '')}")
                    st.markdown(f"**Caption:** {draft.get('caption', '')}")

                    hashtags = draft.get('suggested_hashtags', [])
                    if hashtags:
                        st.markdown(f"**Hashtags:** {' '.join(hashtags)}")

                    source = trend.get("context") or ""
                    if source:
                        if trend.get("source_url"):
                            st.markdown(f"**Source:** {trend['source_url']}")
                        with st.expander("Source material analysed"):
                            st.write(source)
                    
                    st.divider()
                    
                    col1, col2 = st.columns(2)
                    with col1:
                        st.metric("Brand Safety Score", f"{approval['brand_safety_score']}")
                    with col2:
                        if approval['approved']:
                            st.success(approval['reason'])
                        else:
                            st.error(approval['reason'])
                            
        except Exception as e:
            st.error(f"Pipeline Halted: {e}")
