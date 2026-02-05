"""Streamlit UI entry-point — 4 tabs sharing session state with the CLI
pipeline functions.

    streamlit run src/app.py
"""

import json
import os
import sys
import tempfile

import streamlit as st
from dotenv import load_dotenv

# Ensure the project root is on sys.path so ``src.*`` imports resolve when
# Streamlit runs this file directly (unlike ``python -m src.cli``).
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

# Bootstrap .env before any OpenAI / pydantic-ai import, then initialise.
load_dotenv()

from src.bootstrapper import bootstrap  # noqa: E402
from src.app_config import DATA_DIR, DEFAULT_PDF  # noqa: E402
from src.extract import run_extraction  # noqa: E402
from src.pipeline import run_pipeline  # noqa: E402

bootstrap()


# ══════════════════════════════════════════════════════════════════════════════
# Tree-selection helper functions — must be defined before the tab body that
# calls them, because Streamlit executes the script top-to-bottom.
# ══════════════════════════════════════════════════════════════════════════════


def _build_section_tree(sections: list[dict]) -> list[dict]:
    """Convert a flat section list into a nested tree.

    Each node is ``{"section": <dict>, "children": [<node>, …]}``.
    A section at level N+1 becomes a child of the nearest preceding level-N
    node.
    """
    root: list[dict] = []
    stack: list[dict] = [{"children": root}]  # virtual root

    for sec in sections:
        level = sec.get("level", 1)
        node: dict = {"section": sec, "children": []}

        while len(stack) > level:
            stack.pop()

        stack[-1]["children"].append(node)
        stack.append(node)

    return root


def _checkbox_key(title: str) -> str:
    return f"sel_{title}"


def _ensure_checkbox_keys(node: dict) -> None:
    """Initialise session_state checkbox keys to False if not present."""
    key = _checkbox_key(node["section"]["title"])
    if key not in st.session_state:
        st.session_state[key] = False
    for child in node.get("children", []):
        _ensure_checkbox_keys(child)


def _get_all_descendant_keys(node: dict) -> list[str]:
    keys: list[str] = []
    for child in node.get("children", []):
        keys.append(_checkbox_key(child["section"]["title"]))
        keys.extend(_get_all_descendant_keys(child))
    return keys


def _on_parent_toggle(parent_key: str, descendant_keys: list[str]) -> None:
    """Callback: set all descendants to match the parent checkbox."""
    new_value = st.session_state[parent_key]
    for k in descendant_keys:
        st.session_state[k] = new_value


def _render_tree_node(node: dict, indent: int = 0) -> None:
    """Recursively render an expander (level 1) or indented checkbox."""
    sec = node["section"]
    title = sec["title"]
    pages_str = f"pp {sec['start_page']}–{sec.get('end_page', '?')}"
    key = _checkbox_key(title)
    children = node.get("children", [])
    desc_keys = _get_all_descendant_keys(node)

    if indent == 0:
        with st.expander(f"{title} ({pages_str})"):
            st.checkbox(
                title,
                key=key,
                on_change=_on_parent_toggle,
                args=(key, desc_keys),
            )
            for child in children:
                _render_tree_node(child, indent=indent + 1)
    else:
        prefix = "\u00a0\u00a0" * indent  # non-breaking spaces for indent
        st.checkbox(
            f"{prefix}{title} ({pages_str})",
            key=key,
            on_change=_on_parent_toggle,
            args=(key, _get_all_descendant_keys(node)),
        )
        for child in children:
            _render_tree_node(child, indent=indent + 1)


def _get_checked_sections(tree: list[dict]) -> list[dict]:
    """Collect all section dicts whose checkbox is currently checked."""
    result: list[dict] = []

    def _walk(node: dict) -> None:
        key = _checkbox_key(node["section"]["title"])
        if st.session_state.get(key, False):
            result.append(node["section"])
        for child in node.get("children", []):
            _walk(child)

    for node in tree:
        _walk(node)
    return result


# Emoji mapping shared by Tab 4.
_STATUS_EMOJI = {
    "TRACED": "✅",
    "PARTIALLY_TRACED": "⚠️",
    "NOT_TRACED": "🚩",
    "COVERED": "✅",
    "PARTIAL": "⚠️",
    "OMITTED": "🚩",
}


# ══════════════════════════════════════════════════════════════════════════════
# PAGE LAYOUT
# ══════════════════════════════════════════════════════════════════════════════

st.set_page_config(
    page_title="AI Podcast Generator",
    layout="wide",
    initial_sidebar_state="expanded",
)


logo_path = DATA_DIR / "logo.png"

import streamlit as st
import base64

# --- Remove top padding + Streamlit chrome ---
st.markdown(
    """
    <style>
        .block-container {
            padding-top: 0rem;
        }
        #MainMenu, footer, header {
            visibility: hidden;
        }
    </style>
    """,
    unsafe_allow_html=True
)

# --- Load logo as base64 (required for HTML centering) ---
with open(logo_path, "rb") as f:
    logo_base64 = base64.b64encode(f.read()).decode()

# --- Centered logo ---
st.markdown(
    f"""
    <div style="display: flex; justify-content: center;">
        <img src="data:image/png;base64,{logo_base64}" width="200"/>
    </div>
    """,
    unsafe_allow_html=True
)

# --- Centered title ---
st.markdown(
    """
    <h1 style="text-align: center; margin-top: 0.25rem;">
        AI Podcast Generator
    </h1>
    """,
    unsafe_allow_html=True
)


# ── tabs ───────────────────────────────────────────────────────────────────
tab_extract, tab_generate, tab_script, tab_verify = st.tabs(
    ["1.Extract", "2.Generate", "3.Podcast Script", "4.Verification Report"]
)


# ══════════════════════════════════════════════════════════════════════════════
# TAB 1 — Extract
# ══════════════════════════════════════════════════════════════════════════════
with tab_extract:
    st.header("Upload & Extract")
    uploaded_file = st.file_uploader("Upload a PDF", type=["pdf"])

    using_default = uploaded_file is None
    extract_possible = not using_default or DEFAULT_PDF.exists()

    if using_default and DEFAULT_PDF.exists():
        st.info(f"No file uploaded — the default **{DEFAULT_PDF.name}** will be used.")
    elif using_default:
        st.warning("No file uploaded and the default PDF was not found. Please upload a file.")

    extract_btn = st.button("Extract", disabled=not extract_possible)

    if extract_btn:
        if using_default:
            pdf_path = str(DEFAULT_PDF)
        else:
            tmp = tempfile.NamedTemporaryFile(suffix=".pdf", delete=False)
            tmp.write(uploaded_file.getvalue())
            tmp.close()
            pdf_path = tmp.name

        try:
            with st.status("Extracting …", expanded=True) as status:
                st.write("Opening PDF …")
                result = run_extraction(file_path=pdf_path)
                st.session_state["extracted_data"] = result
                st.session_state["sections"] = result.get("sections", [])
                # Clear downstream state so stale results don't linger.
                for key in ("selected_sections", "page_overrides", "script", "verification", "word_count"):
                    st.session_state.pop(key, None)
                status.update(label="Extraction complete!", state="complete")
        finally:
            if not using_default:
                os.unlink(pdf_path)

    # Show detected sections table when available.
    if "sections" in st.session_state and st.session_state["sections"]:
        import pandas as pd

        rows = [
            {
                "Title": s["title"],
                "Pages": f"{s['start_page']}–{s.get('end_page', '?')}",
                "Level": s["level"],
            }
            for s in st.session_state["sections"]
        ]
        st.dataframe(pd.DataFrame(rows), use_container_width=True)


# ══════════════════════════════════════════════════════════════════════════════
# TAB 2 — Generate
# ══════════════════════════════════════════════════════════════════════════════
with tab_generate:
    if "extracted_data" not in st.session_state or st.session_state["extracted_data"] is None:
        st.info("Run extraction first (Tab 1) before generating a podcast.")
    else:
        st.header("Select sections")

        sections = st.session_state.get("sections", [])
        tree = _build_section_tree(sections) if sections else []

        for node in tree:
            _ensure_checkbox_keys(node)

        for node in tree:
            _render_tree_node(node)

        # Page overrides for selected sections only.
        checked = _get_checked_sections(tree)
        if checked:
            st.subheader("Page overrides (only for selected sections)")
            if "page_overrides" not in st.session_state:
                st.session_state["page_overrides"] = {}
            for sec in checked:
                title = sec["title"]
                val = st.session_state["page_overrides"].get(title, "")
                new_val = st.text_input(
                    f"{title}:", value=val, placeholder='e.g. "12-15"', key=f"override_{title}"
                )
                st.session_state["page_overrides"][title] = new_val

        if not checked:
            st.warning("Select at least one section before generating.")

        gen_btn = st.button("Generate", disabled=not checked)
        if gen_btn:
            overrides = st.session_state.get("page_overrides", {})
            selected = [
                {
                    "name": s["title"],
                    "page_override": overrides.get(s["title"]) or None,
                }
                for s in checked
            ]

            with st.status("Generating …", expanded=True) as status:

                def _progress(msg: str, frac: float) -> None:
                    status.update(label=f"{msg} ({frac * 100:.0f} %)")

                pipeline_result = run_pipeline(
                    st.session_state["extracted_data"],
                    selected,
                    progress_callback=_progress,
                )
                st.session_state["script"] = pipeline_result.script
                st.session_state["verification"] = pipeline_result.verification
                st.session_state["word_count"] = pipeline_result.word_count
                status.update(label="Generation complete!", state="complete")


# ══════════════════════════════════════════════════════════════════════════════
# TAB 3 — Podcast Script
# ══════════════════════════════════════════════════════════════════════════════
with tab_script:
    if "script" not in st.session_state or st.session_state["script"] is None:
        st.info("Run the pipeline first (Tab 2) to see the podcast script.")
    else:
        script_text: str = st.session_state["script"]
        word_count: int = st.session_state.get("word_count", len(script_text.split()))

        st.metric("Word Count", word_count)

        # Render speaker names in bold via markdown.
        display_lines: list[str] = []
        for line in script_text.split("\n"):
            if ":" in line:
                speaker, _, rest = line.partition(":")
                if speaker.strip() in ("Alex", "Jordan"):
                    display_lines.append(f"**{speaker.strip()}:** {rest.strip()}")
                    continue
            display_lines.append(line)
        st.markdown("\n\n".join(display_lines))

        st.download_button(
            label="⬇ Download Script",
            data=script_text,
            file_name="podcast_script.txt",
            mime="text/plain",
        )


# ══════════════════════════════════════════════════════════════════════════════
# TAB 4 — Verification Report
# ══════════════════════════════════════════════════════════════════════════════
with tab_verify:
    if "verification" not in st.session_state or st.session_state["verification"] is None:
        st.info("Run the pipeline first (Tab 2) to see the verification report.")
    else:
        import pandas as pd

        verification = st.session_state["verification"]

        # Claims table
        st.subheader("Claims")
        claims_rows = [
            {
                "Status": f"{_STATUS_EMOJI.get(c['status'], '')} {c['status']}",
                "Claim": c["claim_text"],
                "Page": c.get("source_page"),
                "Section": c.get("source_section"),
            }
            for c in verification.get("claims", [])
        ]
        if claims_rows:
            st.dataframe(pd.DataFrame(claims_rows), use_container_width=True)

        # Coverage table
        st.subheader("Section Coverage")
        cov_rows = [
            {
                "Status": f"{_STATUS_EMOJI.get(c['status'], '')} {c['status']}",
                "Section": c["section"],
                "Key Points Covered": f"{c['key_points_covered']}/{c['key_points_total']}",
                "Omitted": ", ".join(c.get("omitted_points", [])) or "—",
            }
            for c in verification.get("coverage", [])
        ]
        if cov_rows:
            st.dataframe(pd.DataFrame(cov_rows), use_container_width=True)

        st.download_button(
            label="⬇ Download Report (JSON)",
            data=json.dumps(verification, indent=2, ensure_ascii=False),
            file_name="verification_report.json",
            mime="application/json",
        )
