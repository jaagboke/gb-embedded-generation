"""Generator site screening tool.

Run locally with:  streamlit run app/streamlit_app.py
"""

from __future__ import annotations

import sys
from pathlib import Path

import streamlit as st

# Make the gbeg package importable without installing it (e.g. on Streamlit Community Cloud).
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

st.set_page_config(page_title="Generator site screening", page_icon="⚡", layout="wide")

st.markdown(
    """
    <style>
    @import url('https://fonts.googleapis.com/css2?family=IBM+Plex+Sans:wght@400;500;600&display=swap');
    html, body, [class*="css"], .stMarkdown, .stText, button, input, select, textarea {
        font-family: 'IBM Plex Sans', system-ui, sans-serif;
    }
    h1 { font-weight: 600; letter-spacing: -0.01em; font-size: 2.1rem; line-height: 1.2; }
    h2, h3 { font-weight: 600; }
    .block-container { padding-top: 2.2rem; max-width: 1280px; }
    .lede { font-size: 1.08rem; max-width: 70ch; line-height: 1.55; margin-bottom: 1.2rem; }
    .statusbar { display: flex; width: 100%; height: 14px; border-radius: 7px;
                 overflow: hidden; margin: 0.4rem 0 0.6rem; }
    .statusbar span { display: block; height: 100%; }
    .legend { display: flex; flex-wrap: wrap; gap: 0.4rem 1.6rem; margin-bottom: 1.2rem;
              font-size: 0.93rem; }
    .legend .dot, .dot { display: inline-block; width: 10px; height: 10px; border-radius: 50%;
                         margin-right: 0.45rem; vertical-align: 0; }
    .legend b { font-weight: 600; font-variant-numeric: tabular-nums; }
    .compare td, .compare th { padding: 0.35rem 0.8rem 0.35rem 0; vertical-align: top;
                               text-align: left; border: none; }
    .compare th { font-weight: 500; opacity: 0.7; width: 11rem; }
    .compare { border-collapse: collapse; margin-bottom: 0.6rem; }
    .note { font-size: 0.9rem; opacity: 0.8; max-width: 75ch; }
    .datachips { display: flex; flex-wrap: wrap; gap: 0.4rem 1.2rem; font-size: 0.9rem;
                 margin: -0.4rem 0 1.2rem; }
    .datachips .off { opacity: 0.55; text-decoration: line-through; }
    .calc { font-variant-numeric: tabular-nums; line-height: 1.8; }
    </style>
    """,
    unsafe_allow_html=True,
)

# Page paths are relative to this file.
page = st.navigation([
    st.Page("views/screen.py", title="Screen your sites", icon="📍", default=True),
    st.Page("views/register.py", title="Generation register", icon="🗺️"),
    st.Page("views/method.py", title="Method and assumptions", icon="📐"),
])
page.run()
