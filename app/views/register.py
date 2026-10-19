"""Generation register page: ENWL's Embedded Capacity Register checked against REPD.

Reads app/data/enwl_sites.csv, produced by `python -m gbeg.export`.
"""

from __future__ import annotations

import math
from pathlib import Path

import pandas as pd
import pydeck as pdk
import streamlit as st

DATA = Path(__file__).resolve().parents[1] / "data" / "enwl_sites.csv"
REPO_URL = "https://github.com/jaagboke/gb-embedded-generation"

STATUSES = {
    "In both registers": {"hex": "#2E7D6B", "rgb": [46, 125, 107],
                          "help": "ENWL's register and REPD describe the same site."},
    "Possible match": {"hex": "#C9940F", "rgb": [201, 148, 15],
                       "help": "A same-technology REPD site 1-2 km away with a different name."},
    "Not found in REPD": {"hex": "#B8336A", "rgb": [184, 51, 106],
                          "help": "No REPD site that plausibly matches."},
    "Fossil (not covered by REPD)": {"hex": "#7A8590", "rgb": [122, 133, 144],
                                     "help": "Gas and diesel plant. REPD lists renewables "
                                             "and storage only."},
}

@st.cache_data
def load() -> pd.DataFrame:
    df = pd.read_csv(DATA)
    df["label"] = df["site_name"].fillna("Unnamed site").str.title()
    return df


def fmt_mw(value: float | None) -> str:
    if value is None or (isinstance(value, float) and math.isnan(value)):
        return "not stated"
    return f"{value:,.1f} MW" if value < 100 else f"{value:,.0f} MW"


def text(value) -> str:
    if value is None or (isinstance(value, float) and math.isnan(value)):
        return "—"
    return str(value)


df = load()

# ---- Header -----------------------------------------------------------------------------
st.title("Is it in both registers?")
st.markdown(
    "<p class='lede'>Electricity North West publishes every generator of 1 MW or more on its "
    "network. The government's Renewable Energy Planning Database (REPD) tracks renewable "
    "and storage projects through planning. This map checks one against the other, site "
    "by site.</p>",
    unsafe_allow_html=True,
)

# ---- Filters ----------------------------------------------------------------------------
with st.sidebar:
    st.subheader("Filter sites")
    technologies = sorted(df["technology_label"].dropna().unique())
    chosen_tech = st.multiselect("Technology", technologies, placeholder="All technologies")
    chosen_status = st.multiselect("Match status", list(STATUSES), placeholder="All statuses")
    connection = st.radio("Connection", ["All", "Connected", "Accepted to connect"],
                          horizontal=False)
    max_mw = float(df["capacity_mw"].max())
    min_mw = st.slider("Minimum capacity (MW)", 0.0, 50.0, 0.0, 0.5)
    show_links = st.toggle("Draw a line to the matched REPD site", value=True)
    search = st.text_input("Find a site by name")
    st.caption("Size of each dot shows capacity.")

view = df.copy()
if chosen_tech:
    view = view[view["technology_label"].isin(chosen_tech)]
if chosen_status:
    view = view[view["match_status"].isin(chosen_status)]
if connection != "All":
    view = view[view["ecr_status"] == connection]
view = view[view["capacity_mw"].fillna(0) >= min_mw]
if search:
    view = view[view["site_name"].str.contains(search, case=False, na=False)]

# ---- Status bar and legend (doubles as the headline summary) ---------------------------
counts = view["match_status"].value_counts()
mw = view.groupby("match_status")["capacity_mw"].sum()
total = int(counts.sum())
if total:
    segments = "".join(
        f"<span style='width:{counts.get(s, 0) / total * 100:.2f}%;background:{v['hex']}'"
        f" title='{s}'></span>"
        for s, v in STATUSES.items()
    )
    legend = "".join(
        f"<div title=\"{v['help']}\"><span class='dot' style='background:{v['hex']}'></span>"
        f"{s} <b>{counts.get(s, 0)}</b> sites, {mw.get(s, 0):,.0f} MW</div>"
        for s, v in STATUSES.items()
    )
    st.markdown(f"<div class='statusbar'>{segments}</div><div class='legend'>{legend}</div>",
                unsafe_allow_html=True)
else:
    st.info("No sites match these filters. Clear a filter in the sidebar to see more.")

# ---- Map --------------------------------------------------------------------------------
view = view.assign(
    color=view["match_status"].map(lambda s: STATUSES[s]["rgb"] + [210]),
    radius=(view["capacity_mw"].fillna(1).clip(lower=1) ** 0.5) * 260,
    mw_text=view["capacity_mw"].map(fmt_mw),
    repd_text=view["repd_site_name"].fillna("no match"),
)
layers = [
    pdk.Layer(
        "ScatterplotLayer", data=view, id="sites", pickable=True, auto_highlight=True,
        get_position="[longitude, latitude]", get_fill_color="color", get_radius="radius",
        radius_min_pixels=3, radius_max_pixels=28, stroked=True,
        get_line_color=[255, 255, 255], line_width_min_pixels=1,
    )
]
links = view.dropna(subset=["repd_latitude"])
if show_links and len(links):
    layers.insert(0, pdk.Layer(
        "LineLayer", data=links, id="links",
        get_source_position="[longitude, latitude]",
        get_target_position="[repd_longitude, repd_latitude]",
        get_color=[31, 42, 51, 150], get_width=2,
    ))
    layers.insert(1, pdk.Layer(
        "ScatterplotLayer", data=links, id="repd",
        get_position="[repd_longitude, repd_latitude]", get_fill_color=[255, 255, 255, 230],
        get_line_color=[31, 42, 51, 200], stroked=True, line_width_min_pixels=1.5,
        get_radius=120, radius_min_pixels=2, radius_max_pixels=6,
    ))

deck = pdk.Deck(
    layers=layers,
    map_provider="carto",
    map_style="light",
    initial_view_state=pdk.ViewState(latitude=54.05, longitude=-2.75, zoom=7.3),
    tooltip={
        "html": "<b>{label}</b><br/>{technology_label}, {mw_text}<br/>{ecr_status}"
                "<br/><i>{match_status}</i><br/>REPD: {repd_text}",
        "style": {"fontFamily": "IBM Plex Sans, sans-serif", "fontSize": "13px"},
    },
)
event = st.pydeck_chart(deck, height=600, on_select="rerun", selection_mode="single-object",
                        key="map")
st.caption("Coloured dots are ENWL's records. Hollow dots joined by a line are the REPD "
           "record each one was matched to. Click a dot to see the comparison below.")

# ---- Site detail ------------------------------------------------------------------------
picked = None
try:
    objects = event.selection.objects.get("sites", [])
    if objects:
        picked = objects[0]["site_id"]
except AttributeError:
    pass

tab_site, tab_quality, tab_method = st.tabs(["Site comparison", "What the data got wrong",
                                             "How this works"])

with tab_site:
    options = view.sort_values("capacity_mw", ascending=False)
    if options.empty:
        st.write("Adjust the filters to choose a site.")
    else:
        ids = options["site_id"].tolist()
        labels = dict(zip(options["site_id"],
                          options["label"] + " (" + options["mw_text"] + ")", strict=True))
        index = ids.index(picked) if picked in ids else 0
        site_id = st.selectbox("Site", ids, index=index, format_func=labels.get)
        row = options.set_index("site_id").loc[site_id]
        colour = STATUSES[row["match_status"]]["hex"]
        st.markdown(f"#### {row['label']}")
        st.markdown(
            f"<span class='dot' style='display:inline-block;width:10px;height:10px;"
            f"border-radius:50%;background:{colour};margin-right:6px'></span>"
            f"<b>{row['match_status']}</b>. {row['match_basis']}.",
            unsafe_allow_html=True,
        )
        if row.get("status_conflict"):
            st.warning("Worth checking: ENWL lists this site as accepted to connect, but the "
                       f"matched REPD record says “{row['repd_status_raw']}”. The connection "
                       "offer may be out of date, or the match may be wrong.")
        if not pd.isna(row.get("capacity_flag")):
            st.info("ENWL records 99.9 MW for this site. That figure appears on several "
                    "battery schemes and may be a placeholder rather than the design capacity.")

        left, right = st.columns(2)
        with left:
            st.markdown("**ENWL Embedded Capacity Register**")
            st.markdown(
                "<table class='compare'>"
                f"<tr><th>Name</th><td>{text(row['site_name'])}</td></tr>"
                f"<tr><th>Operator</th><td>{text(row['operator'])}</td></tr>"
                f"<tr><th>Technology</th><td>{text(row['technology_label'])}</td></tr>"
                f"<tr><th>Capacity</th><td>{fmt_mw(row['capacity_mw'])}</td></tr>"
                f"<tr><th>Status</th><td>{text(row['ecr_status'])}</td></tr>"
                f"<tr><th>Voltage</th><td>{text(row['connection_voltage_kv'])} kV</td></tr>"
                f"<tr><th>Primary</th><td>{text(row['primary_substation']).title()}</td></tr>"
                f"<tr><th>Grid supply point</th><td>{text(row['grid_supply_point']).title()}"
                "</td></tr>"
                f"<tr><th>Postcode</th><td>{text(row['postcode'])}</td></tr>"
                "</table>",
                unsafe_allow_html=True,
            )
        with right:
            st.markdown("**Renewable Energy Planning Database**")
            if pd.isna(row["repd_site_name"]):
                st.write("No matching record." if "Fossil" not in row["match_status"]
                         else "Not applicable: REPD does not cover fossil generation.")
            else:
                dist = row["distance_m"]
                st.markdown(
                    "<table class='compare'>"
                    f"<tr><th>Name</th><td>{text(row['repd_site_name'])}</td></tr>"
                    f"<tr><th>Operator</th><td>{text(row['repd_operator'])}</td></tr>"
                    f"<tr><th>Capacity</th><td>{fmt_mw(row['repd_capacity_mw'])}</td></tr>"
                    f"<tr><th>Status</th><td>{text(row['repd_status_raw'])}</td></tr>"
                    f"<tr><th>Postcode</th><td>{text(row['repd_postcode'])}</td></tr>"
                    f"<tr><th>Distance</th><td>{dist:,.0f} m from the ENWL location</td></tr>"
                    f"<tr><th>REPD ref</th><td>{int(row['repd_ref'])}</td></tr>"
                    "</table>",
                    unsafe_allow_html=True,
                )

with tab_quality:
    st.markdown(
        """
Getting two public registers to line up meant fixing or flagging these problems first.

**REPD (14,657 records)**
- Nine Scottish battery sites had easting and northing swapped, placing them off the edge
  of Great Britain. Fixed and flagged.
- Some records carry the wrong country (Highland sites labelled England) while their
  coordinates are right, so location always comes from the coordinates.
- Re-applications create repeat records: 890 rows share a name and location with another.
- Newlines inside fields, including the coordinate columns, mean 15,967 lines hold
  14,657 records.

**ENWL Embedded Capacity Register (568 records)**
- No usable record ID: the reference is blank on 566 rows, so a stable key is built from
  the site's details.
- Technology is free text with typos ("IRRESPECTVE", "STOAGE") and 25 spellings of the
  energy source. Ordered rules classify them, and the load stops if a new spelling appears.
- Unknown values are written three ways: "DATA NOT AVAILABLE", "TO BE CONFIRMED" and "-".
- 99.9 MW appears on nine battery schemes. Three match REPD records that also say 99.9 MW,
  so at least some are real.
- About a quarter of ENWL's large generation (179 sites, 1,941 MW) is gas or diesel,
  which REPD does not cover at all.
        """
    )

with tab_method:
    st.markdown(
        f"""
**Matching.** Each ENWL site is compared with every REPD site within 2 km. A pair counts as
the same site when the technologies agree, the capacities are within a factor of two, and
either the names agree or the sites are within 1 km. Names are compared after removing
words that never identify a site, such as "solar", "farm" or "BESS".

Distance alone is not enough. Many wind and solar farms with identical names sit 1 to 2 km
apart in the two registers, probably because ENWL records the connection point and REPD the
site centre.

**Accuracy.** The matching has not yet been validated. A stratified sample of 60 pairs is
being labelled by hand to measure how often an accepted match is right and how many real
matches are missed. Treat the counts here as a first pass.

**Data.** ENWL Embedded Capacity Register (1 MW and above). DESNZ Renewable Energy Planning
Database, Q2 2026, Open Government Licence v3.0. Basemap © CARTO, © OpenStreetMap
contributors.

**Code.** The pipeline, tests and decision log are on [GitHub]({REPO_URL}).
        """
    )

st.markdown(
    f"<p class='note'>Built by Jax as an open data engineering project. "
    f"<a href='{REPO_URL}'>Source and method</a>.</p>",
    unsafe_allow_html=True,
)
