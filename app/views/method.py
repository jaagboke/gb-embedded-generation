"""Method and assumptions page: renders docs/screening-method.md."""

from pathlib import Path

import streamlit as st

DOC = Path(__file__).resolve().parents[2] / "docs" / "screening-method.md"

st.markdown(DOC.read_text())
st.markdown(
    "<p class='note'>The default thresholds live in <code>config/screening.yaml</code> and can "
    "be changed for a single run on the Screen your sites page.</p>",
    unsafe_allow_html=True,
)
