"""Screen your sites: upload a site list, get setting, neighbours, noise and nearby generation."""

from __future__ import annotations

import copy
import hashlib
import math
import os
from pathlib import Path

import pandas as pd
import pydeck as pdk
import streamlit as st

from gbeg.screening import rules
from gbeg.screening.inputs import (
    EXTRA_SITE_FIELDS,
    ROLE_PATTERNS,
    ColumnMap,
    add_sites,
    detect_columns,
    read_table,
)
from gbeg.screening.layers import ReferenceData
from gbeg.screening.report import to_excel
from gbeg.screening.screen import screen

APP = Path(__file__).resolve().parents[1]
# Point GBEG_REFERENCE at another folder to use your own reference data (e.g. inside a
# company network) without changing the code.
REFERENCE = Path(os.environ.get("GBEG_REFERENCE", APP / "data" / "reference"))
EXAMPLE = APP / "examples" / "example_generator_sites.csv"
EXAMPLE_XLSX = APP / "examples" / "manweb_generator_deployments.xlsx"

SETTINGS = {
    "Urban": {"hex": "#3E5C76", "rgb": [62, 92, 118]},
    "Borderline": {"hex": "#C9940F", "rgb": [201, 148, 15]},
    "Rural": {"hex": "#2E7D6B", "rgb": [46, 125, 107]},
    "Not assessed": {"hex": "#7A8590", "rgb": [122, 133, 144]},
}
RAG_CSS = {"Red": "background-color:#F4C7C3", "Amber": "background-color:#FCE8B2",
           "Green": "background-color:#D9EAD3"}
ROLE_LABELS = {"name": "Site name", "location": "Location (any format)", "postcode": "Postcode",
               "gridref": "Grid reference", "easting": "Easting", "northing": "Northing",
               "lat": "Latitude", "lon": "Longitude", "kva": "Generator rating (kVA)",
               "noise_7m": "Noise at 7 m, dB(A)", "period": "Operating period"}


@st.cache_resource
def reference() -> ReferenceData:
    return ReferenceData.load(REFERENCE)


def num(value) -> str:
    if value is None or (isinstance(value, float) and math.isnan(value)):
        return "—"
    return f"{value:,.0f}" if float(value).is_integer() else f"{value:,.1f}"


ref = reference()
base_cfg = rules.load_config()

st.title("Screen generator sites")
st.markdown(
    "<p class='lede'>Upload a list of candidate sites for temporary or standby generators. "
    "For each one you get its rural or urban setting, how close the nearest addresses are, "
    "an indicative noise check and the generation already nearby, with the reason for every "
    "result. Download the results as a spreadsheet for your own assessment.</p>",
    unsafe_allow_html=True,
)
chips = "".join(
    f"<span class='{'' if ok else 'off'}'>{'✓' if ok else '✗'} {name}</span>"
    for name, ok in ref.available.items()
)
st.markdown(f"<div class='datachips'>Reference data: {chips}</div>", unsafe_allow_html=True)
if not all(ref.available.values()):
    missing = [k for k, v in ref.available.items() if not v]
    st.info("Some reference data is not loaded yet (" + ", ".join(missing) + "). Sites are "
            "still located and checked against what is available, and each result says what "
            "could not be assessed.")

# ---- Input ------------------------------------------------------------------------------
left, right = st.columns([3, 2])
with left:
    upload = st.file_uploader("Your site list (CSV or Excel)", type=["csv", "xlsx", "xls"])
with right:
    st.write("")
    use_example = upload is None and st.toggle("Try it with the example sites", value=True)
    st.download_button("Download a blank template", data=(
        "Site name,Location,Generator rating (kVA),Noise at 7m dB(A),Operating period\n"
        "Example site,SJ 838 980,500,,24h\n"), file_name="generator_sites_template.csv",
        mime="text/csv")
    st.download_button("Download an example team spreadsheet", data=EXAMPLE_XLSX.read_bytes(),
                       file_name=EXAMPLE_XLSX.name,
                       mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")

with st.expander("Add sites by hand", expanded=upload is None and not use_example):
    st.write("Type a site name and its location (postcode, grid reference such as "
             "SJ 838 980, easting and northing, or latitude and longitude). These sites are "
             "screened together with any file you upload. Add a row with the + below "
             "the table.")
    extra_sites = st.data_editor(
        pd.DataFrame({c: pd.Series(dtype="str") for c in EXTRA_SITE_FIELDS}),
        num_rows="dynamic", hide_index=True, width="stretch", key="extra_sites",
        column_config={"Generator rating (kVA)": st.column_config.TextColumn(),
                       "Noise at 7 m dB(A)": st.column_config.TextColumn()})
    if ref.spen_sites_loaded:
        st.caption("Leave Location empty for an SPEN substation: its name is looked up in "
                   "SP Energy Networks' substation list.")
        picked = st.multiselect(
            "Or pick SPEN substations", ref.spen_sites["label"].tolist(),
            placeholder="Start typing a substation name", key="spen_picked")
        if picked:
            spen = ref.spen_sites.set_index("label")
            # If the name alone would not find this exact substation, give its coordinates.
            extra_sites = pd.concat([extra_sites, pd.DataFrame({
                "Site name": picked,
                "Location": [None if (ref.find_site(p) or (0, 0, ""))[2] == p else
                             f"{spen.loc[p, 'e']:.0f}, {spen.loc[p, 'n']:.0f}"
                             for p in picked]})], ignore_index=True)

if upload is not None:
    raw, source_name = upload.getvalue(), upload.name
elif use_example:
    raw, source_name = EXAMPLE.read_bytes(), EXAMPLE.name
else:
    raw, source_name = None, None

if raw is not None:
    sites = read_table(raw, source_name)
    if use_example:
        source_name = "example sites (made up)"
    # Column choices belong to one file: a new file starts again from automatic detection.
    file_key = hashlib.md5(raw).hexdigest()[:10]
else:
    sites, file_key = pd.DataFrame(), "none"

n_file = len(sites)
if raw is not None:
    st.caption(f"{n_file} rows read from {source_name}. Location can be a postcode, OS grid "
               "reference, easting and northing, or latitude and longitude. If a Location "
               "column holds site names or addresses, the Postcode column (or a postcode in "
               "the address) is used instead.")

columns = ColumnMap()
if raw is not None:
    detected = detect_columns(sites)
    with st.expander("Check how your columns were read", expanded=False):
        st.write("Change a column if it was matched wrongly. Leave a role empty if your file "
                 "does not have it.")
        options = ["—"] + list(sites.columns)
        roles = {}
        grid = st.columns(3)
        for i, role in enumerate(ROLE_PATTERNS):
            current = detected.get(role)
            choice = grid[i % 3].selectbox(ROLE_LABELS[role], options,
                                           index=options.index(current) if current else 0,
                                           key=f"role_{role}_{file_key}")
            if choice != "—":
                roles[role] = choice
        columns = ColumnMap(roles)

# Sites typed in by hand go after the file's rows.
sites, columns = add_sites(sites, columns, extra_sites)
n_extra = len(sites) - n_file
if sites.empty:
    st.info("Upload a CSV or Excel file of sites, switch on the example sites, or add "
            "sites by hand above.")
    st.stop()
if n_extra:
    st.caption(f"{n_extra} {'site' if n_extra == 1 else 'sites'} added by hand"
               + (f", screened with the {n_file} from the file." if n_file else "."))

with st.expander("Adjust the screening rules for this run", expanded=False):
    cfg = copy.deepcopy(base_cfg)
    a, b, c = st.columns(3)
    s = cfg["setting"]
    s["radius_m"] = a.number_input("Count addresses within (m)", 50, 2000, s["radius_m"], 50)
    s["urban_if"]["addresses_at_least"] = a.number_input(
        "Urban if at least this many addresses", 1, 1000, s["urban_if"]["addresses_at_least"])
    s["rural_if"]["addresses_below"] = b.number_input(
        "Rural only if fewer addresses than", 1, 500, s["rural_if"]["addresses_below"])
    s["rural_if"]["nearest_address_at_least_m"] = b.number_input(
        "Rural only if nearest address at least (m)", 0, 2000,
        s["rural_if"]["nearest_address_at_least_m"], 10)
    bg = cfg["noise"]["assumed_night_background_db"]
    bg["rural"] = c.number_input("Night background, rural (dB)", 15, 60, bg["rural"])
    bg["borderline"] = c.number_input("Night background, borderline (dB)", 15, 60,
                                      bg["borderline"])
    bg["urban"] = c.number_input("Night background, urban (dB)", 15, 60, bg["urban"])
    st.caption("Defaults are assumptions, explained on the Method and assumptions page. "
               "The downloaded spreadsheet records the values used.")

result = screen(sites, ref, cfg, columns)
res = result.results.copy()
res["Setting shown"] = res["Setting"].fillna("Not assessed")

# ---- Summary ----------------------------------------------------------------------------
st.subheader(f"{len(res)} {'site' if len(res) == 1 else 'sites'} screened"
             + (f", {len(result.problems)} could not be" if len(result.problems) else ""))
if len(res):
    counts = res["Setting shown"].value_counts()
    total = len(res)
    bar = "".join(f"<span style='width:{counts.get(k, 0) / total * 100:.2f}%;"
                  f"background:{v['hex']}' title='{k}'></span>" for k, v in SETTINGS.items())
    rag = res["RAG"].value_counts()
    legend = "".join(
        f"<div><span class='dot' style='background:{v['hex']}'></span>{k} "
        f"<b>{counts.get(k, 0)}</b></div>" for k, v in SETTINGS.items() if counts.get(k, 0))
    if rag.sum():
        legend += (f"<div>Noise check: <b>{rag.get('Red', 0)}</b> red, "
                   f"<b>{rag.get('Amber', 0)}</b> amber, <b>{rag.get('Green', 0)}</b> green</div>")
    st.markdown(f"<div class='statusbar'>{bar}</div><div class='legend'>{legend}</div>",
                unsafe_allow_html=True)

if len(result.problems):
    n_bad = len(result.problems)
    with st.expander(f"{n_bad} {'row' if n_bad == 1 else 'rows'} could not be screened",
                     expanded=True):
        st.dataframe(result.problems, hide_index=True, width="stretch")

if not len(res):
    st.stop()

st.download_button(
    "Download results (Excel)", data=to_excel(result, cfg, ref.available),
    file_name="generator_site_screening.xlsx", type="primary",
    mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")

# ---- Map --------------------------------------------------------------------------------
site_names = res["Site"].tolist()
selected = st.session_state.get("selected_site", site_names[0])
if selected not in site_names:
    selected = site_names[0]

mapdf = res.assign(
    color=res["Setting shown"].map(lambda s: SETTINGS[s]["rgb"] + [230]),
    setting_text=res["Setting shown"],
    noise_text=res["Indicative noise impact"].fillna("not estimated"),
    nearest_text=res["Nearest address (m)"].map(lambda v: f"{num(v)} m"),
)
layers = []
near = pd.concat([g.assign(site=res.loc[i, "Site"]) for i, g in result.nearby.items()]) \
    if result.nearby else pd.DataFrame()
if len(near):
    from gbeg.transform.coords import from_en
    near = near.drop_duplicates(subset=["name", "e", "n"]).copy()
    ll = [from_en(e, n) for e, n in zip(near["e"], near["n"], strict=True)]
    near["lat"] = [p.latitude for p in ll]
    near["lon"] = [p.longitude for p in ll]
    near["mw_text"] = near["mw"].map(lambda v: f"{num(v)} MW")
    layers.append(pdk.Layer(
        "ScatterplotLayer", data=near, id="nearby", pickable=True,
        get_position="[lon, lat]", get_fill_color=[31, 42, 51, 90], get_radius=60,
        radius_min_pixels=2, radius_max_pixels=6))
sel = mapdf[mapdf["Site"] == selected]
layers.append(pdk.Layer(
    "ScatterplotLayer", data=sel, id="radius", stroked=True, filled=False,
    get_position="[Longitude, Latitude]", get_radius=cfg["setting"]["radius_m"],
    get_line_color=[31, 42, 51, 200], line_width_min_pixels=1.5))
layers.append(pdk.Layer(
    "ScatterplotLayer", data=mapdf, id="sites", pickable=True, auto_highlight=True,
    get_position="[Longitude, Latitude]", get_fill_color="color", get_radius=180,
    radius_min_pixels=6, radius_max_pixels=14, stroked=True,
    get_line_color=[255, 255, 255], line_width_min_pixels=1.5))

points = mapdf[["Longitude", "Latitude"]].values.tolist()
if len({tuple(p) for p in points}) < 2:
    # compute_view needs a spread of points (with one, its 95% subset is empty).
    view = pdk.ViewState(longitude=points[0][0], latitude=points[0][1], zoom=14)
else:
    # Keep 95% of points in view (ignoring outliers), but never fewer than all of a few.
    view = pdk.data_utils.compute_view(points, 0.95 if len(points) >= 20 else 1)
    view.zoom = min(view.zoom, 13)
event = st.pydeck_chart(
    pdk.Deck(layers=layers, map_provider="carto", map_style="light", initial_view_state=view,
             tooltip={"html": "<b>{Site}</b><br/>{setting_text}<br/>Nearest address: "
                              "{nearest_text}<br/>Noise: {noise_text}",
                      "style": {"fontFamily": "IBM Plex Sans, sans-serif", "fontSize": "13px"}}),
    height=480, on_select="rerun", selection_mode="single-object", key="screen_map")
try:
    hit = event.selection.objects.get("sites", [])
    if hit:
        selected = hit[0]["Site"]
except AttributeError:
    pass
st.caption("Large dots are your sites, coloured by setting. Small grey dots are existing or "
           f"planned generation. The ring shows the {cfg['setting']['radius_m']} m radius "
           "used to count addresses around the selected site.")

# ---- Table ------------------------------------------------------------------------------
show = ["Site", "Setting", "ONS rural/urban class", "Addresses within 250 m",
        "Nearest address (m)", "Predicted at nearest address dB(A)",
        "Excess over background dB", "RAG", "Generation within 2 km"]
table = res[show].rename(columns={"Addresses within 250 m":
                                  f"Addresses within {cfg['setting']['radius_m']} m"})
st.dataframe(table.style.map(lambda v: RAG_CSS.get(v, ""), subset=["RAG"]),
             hide_index=True, width="stretch")

# ---- Site detail ------------------------------------------------------------------------
st.subheader("Why each site got its result")
selected = st.selectbox("Site", site_names, index=site_names.index(selected),
                        key="selected_site")
row = res[res["Site"] == selected].iloc[0]
colour = SETTINGS[row["Setting shown"]]["hex"]
st.markdown(f"<span class='dot' style='background:{colour}'></span><b>{row['Setting shown']}"
            f"</b>. {row['Why this setting']}.", unsafe_allow_html=True)

d1, d2 = st.columns(2)
with d1:
    st.markdown("**Location and neighbours**")
    st.markdown(
        "<table class='compare'>"
        f"<tr><th>Location given</th><td>{row['Location given']}</td></tr>"
        f"<tr><th>Read as</th><td>{row['Located by']}: {row['Easting']:,}, "
        f"{row['Northing']:,}</td></tr>"
        f"<tr><th>ONS class</th><td>{row['ONS rural/urban class'] or 'not loaded'}</td></tr>"
        f"<tr><th>Addresses within 250 m</th><td>{num(row['Addresses within 250 m'])}</td></tr>"
        f"<tr><th>Addresses within 500 m</th><td>{num(row['Addresses within 500 m'])}</td></tr>"
        f"<tr><th>Nearest address</th><td>{num(row['Nearest address (m)'])} m</td></tr>"
        "</table>", unsafe_allow_html=True)
with d2:
    st.markdown("**Indicative noise check**")
    if row["Predicted at nearest address dB(A)"] is None or pd.isna(
            row["Predicted at nearest address dB(A)"]):
        st.write(row["Notes"] or "Not estimated.")
    else:
        st.markdown(
            "<div class='calc'>"
            f"Generator: <b>{num(row['Noise at 7 m dB(A)'])} dB(A) at 7 m</b> "
            f"({row['Noise figure']})<br/>"
            f"At the nearest address, {num(row['Nearest address (m)'])} m away: "
            f"<b>{row['Predicted at nearest address dB(A)']:.1f} dB(A)</b><br/>"
            f"Assumed {row['Assessed period']}-time background: "
            f"{row['Assumed background dB']:.0f} dB<br/>"
            f"Excess: <b>{row['Excess over background dB']:+.1f} dB</b>, "
            f"{row['Indicative noise impact'].lower()}</div>", unsafe_allow_html=True)
        st.caption("Point-source estimate with no screening, so it errs on the cautious "
                   "side. Not a BS 4142 assessment.")

g = result.nearby.get(res.index[res["Site"] == selected][0])
if g is not None:
    st.markdown(f"**Generation within {cfg['nearby_generation']['radius_m'] / 1000:g} km**")
    if len(g):
        st.dataframe(g[["name", "technology", "mw", "status", "source", "distance_m"]].rename(
            columns={"name": "Scheme", "technology": "Technology", "mw": "MW",
                     "status": "Status", "source": "Source", "distance_m": "Distance (m)"}),
            hide_index=True, width="stretch")
    else:
        st.write("None found in the ENWL register or REPD.")
