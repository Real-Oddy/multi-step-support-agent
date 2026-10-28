"""
app.py
------
Streamlit interface layer for the Multi-Step Order Support Agent.

Startup:
  - DB and RAG are initialised once via st.cache_resource (survives reruns).
  - asyncio.run() bridges Streamlit's sync context into our async agent layer.

Layout:
  - Sidebar  : app info, sample queries, session stats.
  - Main area: chat interface with structured response cards.
"""

from __future__ import annotations

import asyncio
from datetime import datetime
from pathlib import Path

import streamlit as st
from dotenv import load_dotenv

from agent import ask
from config import validate_api_keys
from database import init_db
from models import AgentResponse
from rag import init_rag

load_dotenv()

# ---------------------------------------------------------------------------
# Page config — must be the very first Streamlit call
# ---------------------------------------------------------------------------

st.set_page_config(
    page_title="Order Support Agent",
    page_icon="📦",
    layout="centered",
    initial_sidebar_state="expanded",
)

# ---------------------------------------------------------------------------
# One-time system initialisation (cached across reruns and users)
# ---------------------------------------------------------------------------


@st.cache_resource(show_spinner="Initialising systems...")
def _init_systems() -> bool:
    """Validate configuration and initialize systems once per server lifetime."""
    validate_api_keys()
    asyncio.run(init_db())
    asyncio.run(init_rag())
    return True


# ---------------------------------------------------------------------------
# Session state defaults
# ---------------------------------------------------------------------------


def _init_session() -> None:
    """Initialise session state keys on first run for this browser session."""
    if "messages" not in st.session_state:
        st.session_state.messages = []  # list of {"role", "content", "response"}
    if "query_count" not in st.session_state:
        st.session_state.query_count = 0
    if "escalation_count" not in st.session_state:
        st.session_state.escalation_count = 0


# ---------------------------------------------------------------------------
# Response card renderer
# ---------------------------------------------------------------------------


def _render_response_card(response: AgentResponse) -> None:
    """Render a structured AgentResponse as a formatted Streamlit card."""

    # Status badge colour
    status_colours = {
        "processing": "🟡",
        "shipped": "🔵",
        "delivered": "🟢",
        "cancelled": "⚫",
        "delayed": "🔴",
        "pending payment": "🟠",
    }
    status_icon = status_colours.get(response.current_status.lower(), "⚪")

    # Header row — order number + status
    col1, col2 = st.columns([1, 2])
    with col1:
        st.metric(label="Order", value=response.order_number)
    with col2:
        st.metric(
            label="Status",
            value=f"{status_icon} {response.current_status}",
        )

    st.divider()

    # Explanation
    st.markdown("**📋 What we found**")
    st.markdown(response.explanation)

    # Recommended action
    st.markdown("**✅ Recommended Action**")
    st.info(response.recommended_action, icon="👉")

    # Escalation flag
    if response.escalation_required:
        st.warning(
            "A support ticket has been raised. Our team will be in touch shortly.",
            icon="⚠️",
        )
    else:
        st.success("This query was resolved without escalation.", icon="✅")


# ---------------------------------------------------------------------------
# Sidebar
# ---------------------------------------------------------------------------


def _render_sidebar() -> None:
    """Render the sidebar with app info, sample queries, and session stats."""
    with st.sidebar:
        st.title("📦 Support Agent")
        st.caption("Multi-Step Order Support — Powered by Claude Haiku + PydanticAI")
        st.divider()

        st.markdown("### 💡 Try these queries")
        sample_queries = [
            "Where is my order ORD-1003?",
            "Can I cancel order ORD-1001?",
            "Can I cancel order ORD-1002?",
            "Why is ORD-1004 delayed?",
            "What is the return policy for ORD-1005?",
            "Where is ORD-9999?",
        ]
        for query in sample_queries:
            if st.button(query, use_container_width=True, key=f"sample_{query}"):
                st.session_state["prefill"] = query

        st.divider()

        # Session stats
        st.markdown("### 📊 Session Stats")
        col1, col2 = st.columns(2)
        col1.metric("Queries", st.session_state.query_count)
        col2.metric("Escalations", st.session_state.escalation_count)

        st.divider()

        # Reset button
        if st.button("🗑 Clear Chat", use_container_width=True):
            st.session_state.messages = []
            st.session_state.query_count = 0
            st.session_state.escalation_count = 0
            st.rerun()

        st.caption(f"Session started: {datetime.now().strftime('%H:%M:%S')}")


# ---------------------------------------------------------------------------
# Main chat area
# ---------------------------------------------------------------------------


def _render_chat() -> None:
    """Render the chat history and handle new user input."""

    st.title("Order Support Chat")
    st.caption(
        "Ask about any order — status, tracking, cancellations, or return policies."
    )

    # Render existing message history
    for msg in st.session_state.messages:
        with st.chat_message(msg["role"]):
            if msg["role"] == "user":
                st.markdown(msg["content"])
            else:
                # Re-render the structured card for assistant messages
                _render_response_card(msg["response"])

    # Check if a sidebar sample query was clicked
    prefill = st.session_state.pop("prefill", None)

    # Chat input
    user_input = st.chat_input(
        "Ask about your order...",
        key="chat_input",
    ) or prefill

    if not user_input:
        return

    # Display user message immediately
    with st.chat_message("user"):
        st.markdown(user_input)
    st.session_state.messages.append({"role": "user", "content": user_input})

    # Run the agent and stream the response card
    with st.chat_message("assistant"):
        with st.spinner("Looking into your order..."):
            try:
                response: AgentResponse = asyncio.run(ask(user_input))
            except Exception as exc:
                st.error(f"Something went wrong: {exc}", icon="🚨")
                return

        _render_response_card(response)

    # Persist assistant response to session history
    st.session_state.messages.append(
        {"role": "assistant", "content": response.explanation, "response": response}
    )

    # Update session stats
    st.session_state.query_count += 1
    if response.escalation_required:
        st.session_state.escalation_count += 1


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------


def main() -> None:
    _init_session()

    # Initialise systems (runs once, cached)
    try:
        _init_systems()
    except EnvironmentError as exc:
        st.error(
            f"**Startup failed:** {exc}\n\n"
            "Check that `OPENAI_API_KEY` and `ANTHROPIC_API_KEY` are set in your `.env` file.",
            icon="🚨",
        )
        st.stop()

    _render_sidebar()
    _render_chat()


if __name__ == "__main__":
    main()
