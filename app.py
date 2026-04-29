import os
from pathlib import Path
from datetime import datetime

import pandas as pd
import streamlit as st

from eoi_pdf_extractor import process_batch


# -----------------------------
# CONFIG
# -----------------------------

st.set_page_config(
    page_title="EOI Dashboard",
    page_icon="📄",
    layout="wide"
)

INPUT_DIR = Path("input_pdfs")
OUTPUT_DIR = Path("output")
OUTPUT_FILE = OUTPUT_DIR / "eoi_results.csv"

INPUT_DIR.mkdir(exist_ok=True)
OUTPUT_DIR.mkdir(exist_ok=True)


# -----------------------------
# HELPERS
# -----------------------------

STATE_ABBR = {
    "Australian Capital Territory": "ACT",
    "New South Wales": "NSW",
    "Victoria": "VIC",
    "Queensland": "QLD",
    "South Australia": "SA",
    "Western Australia": "WA",
    "Tasmania": "TAS",
    "Northern Territory": "NT",
    "Australian Capital Territory (nomination)": "ACT*",
    "New South Wales (nomination)": "NSW*",
    "Victoria (nomination)": "VIC*",
    "Queensland (nomination)": "QLD*",
    "South Australia (nomination)": "SA*",
    "Western Australia (nomination)": "WA*",
    "Tasmania (nomination)": "TAS*",
    "Northern Territory (nomination)": "NT*",
}

def abbr_state(value):
    return STATE_ABBR.get(value, value)

def expiry_status(days):
    try:
        days = int(days)
        if days <= 0:
            return "EXPIRED"
        if days <= 90:
            return f"{days} days"
        if days <= 180:
            return f"{days} days"
        return ""
    except:
        return ""

def expiry_group(days):
    try:
        days = int(days)
        if days <= 0:
            return "Expired"
        if days <= 90:
            return "< 90 days"
        if days <= 180:
            return "< 180 days"
        return "OK"
    except:
        return "Unknown"

def enrich_df(df):
    df = df.copy()

    if "state" in df.columns:
        df["state_short"] = df["state"].apply(abbr_state)

    if "eoi_days_remaining" in df.columns:
        df["eoi_status"] = df["eoi_days_remaining"].apply(expiry_status)
        df["eoi_expiry_group"] = df["eoi_days_remaining"].apply(expiry_group)

    if "english_days_remaining" in df.columns:
        df["english_status"] = df["english_days_remaining"].apply(expiry_status)
        df["english_expiry_group"] = df["english_days_remaining"].apply(expiry_group)

    return df


# -----------------------------
# HEADER
# -----------------------------

st.markdown(
    """
    <div style="background-color:#ffffff; padding:18px 24px; border-bottom:1px solid #DDE1ED;">
        <h2 style="margin:0; color:#1C2033;">EOI Client Dashboard</h2>
        <p style="margin:4px 0 0 0; color:#6B7280;">
            Success Education & Visa — PDF extraction, review and expiry tracking
        </p>
    </div>
    """,
    unsafe_allow_html=True
)

st.write("")


# -----------------------------
# SIDEBAR UPLOAD
# -----------------------------

with st.sidebar:
    st.title("EOI Automation")

    uploaded_files = st.file_uploader(
        "Upload EOI PDFs",
        type=["pdf"],
        accept_multiple_files=True
    )

    run_button = st.button("Run Extraction", type="primary")

    st.divider()
    st.caption("Upload EOI Details and Points Breakdown PDFs together.")


# -----------------------------
# PROCESS FILES
# -----------------------------

if uploaded_files and run_button:
    for old_file in INPUT_DIR.glob("*.pdf"):
        old_file.unlink()

    for file in uploaded_files:
        with open(INPUT_DIR / file.name, "wb") as f:
            f.write(file.getbuffer())

    with st.spinner("Extracting EOI data..."):
        process_batch(str(INPUT_DIR), str(OUTPUT_FILE))

    st.success("Extraction completed.")


# -----------------------------
# LOAD DATA
# -----------------------------

if not OUTPUT_FILE.exists():
    st.info("Upload PDFs from the sidebar and click **Run Extraction**.")
    st.stop()

df = pd.read_csv(OUTPUT_FILE).fillna("")
df = enrich_df(df)


# -----------------------------
# METRICS
# -----------------------------

total_clients = len(df)
need_review = len(df[df.get("review_flag", "") == "CHECK"]) if "review_flag" in df.columns else 0
ready_clients = total_clients - need_review

expired_eoi = 0
urgent_eoi = 0

if "eoi_days_remaining" in df.columns:
    expired_eoi = len(df[pd.to_numeric(df["eoi_days_remaining"], errors="coerce") <= 0])
    urgent_eoi = len(df[
        (pd.to_numeric(df["eoi_days_remaining"], errors="coerce") > 0) &
        (pd.to_numeric(df["eoi_days_remaining"], errors="coerce") <= 90)
    ])

col1, col2, col3, col4 = st.columns(4)

col1.metric("Total Clients", total_clients)
col2.metric("Need Review", need_review)
col3.metric("Expired EOI", expired_eoi)
col4.metric("EOI < 90 Days", urgent_eoi)

st.divider()


# -----------------------------
# FILTERS
# -----------------------------

filter_col1, filter_col2, filter_col3, filter_col4, filter_col5 = st.columns(5)

with filter_col1:
    search = st.text_input("Search client / EOI / occupation")

with filter_col2:
    visa_options = ["All"] + sorted([x for x in df["visa_subclass"].unique() if x]) if "visa_subclass" in df.columns else ["All"]
    visa_filter = st.selectbox("Visa", visa_options)

with filter_col3:
    state_col = "state_short" if "state_short" in df.columns else "state"
    state_options = ["All"] + sorted([x for x in df[state_col].unique() if x]) if state_col in df.columns else ["All"]
    state_filter = st.selectbox("State", state_options)

with filter_col4:
    flag_filter = st.selectbox("Flag", ["All", "CHECK", "OK"])

with filter_col5:
    expiry_filter = st.selectbox("EOI Expiry", ["All", "Expired", "< 90 days", "< 180 days"])


filtered = df.copy()

if search:
    search_lower = search.lower()
    filtered = filtered[
        filtered.apply(lambda row: search_lower in " ".join(row.astype(str)).lower(), axis=1)
    ]

if visa_filter != "All" and "visa_subclass" in filtered.columns:
    filtered = filtered[filtered["visa_subclass"] == visa_filter]

if state_filter != "All" and state_col in filtered.columns:
    filtered = filtered[filtered[state_col] == state_filter]

if flag_filter == "CHECK" and "review_flag" in filtered.columns:
    filtered = filtered[filtered["review_flag"] == "CHECK"]

if flag_filter == "OK" and "review_flag" in filtered.columns:
    filtered = filtered[filtered["review_flag"] != "CHECK"]

if expiry_filter != "All" and "eoi_expiry_group" in filtered.columns:
    filtered = filtered[filtered["eoi_expiry_group"] == expiry_filter]


# -----------------------------
# TABLE DISPLAY
# -----------------------------

display_columns = [
    "client_name",
    "eoi_id",
    "visa_subclass",
    "state_short",
    "occupation_name",
    "total_points",
    "eoi_expiry_date",
    "eoi_status",
    "english_test_type",
    "english_test_date",
    "english_expiry_date",
    "english_status",
    "english_level",
    "skills_assessment_authority",
    "skills_assessment_date",
    "partner_english_test_type",
    "partner_english_test_date",
    "partner_english_expiry_date",
    "partner_english_level",
    "review_flag",
]

display_columns = [c for c in display_columns if c in filtered.columns]

st.subheader(f"Showing {len(filtered)} of {len(df)} clients")

def highlight_rows(row):
    if row.get("review_flag", "") == "CHECK":
        return ["background-color: #F5F3FF"] * len(row)

    try:
        days = int(row.get("eoi_days_remaining", ""))
        if days <= 0:
            return ["background-color: #FFF0F0"] * len(row)
        if days <= 90:
            return ["background-color: #FFF7ED"] * len(row)
        if days <= 180:
            return ["background-color: #FFFBEB"] * len(row)
    except:
        pass

    return [""] * len(row)

st.dataframe(
    filtered[display_columns].style.apply(highlight_rows, axis=1),
    use_container_width=True,
    height=500
)


# -----------------------------
# DETAIL VIEW
# -----------------------------

st.divider()
st.subheader("Client Detail View")

if len(filtered) > 0 and "client_name" in filtered.columns:
    selected_client = st.selectbox(
        "Select a client",
        filtered["client_name"].astype(str).tolist()
    )

    selected_row = filtered[filtered["client_name"].astype(str) == selected_client].iloc[0]

    detail_tab1, detail_tab2, detail_tab3, detail_tab4 = st.tabs([
        "Personal",
        "EOI & Occupation",
        "English & Skills",
        "Points"
    ])

    with detail_tab1:
        st.write("**Client Name:**", selected_row.get("client_name", ""))
        st.write("**EOI ID:**", selected_row.get("eoi_id", ""))
        st.write("**Visa Subclass:**", selected_row.get("visa_subclass", ""))
        st.write("**State:**", selected_row.get("state", ""))
        st.write("**Relationship Status:**", selected_row.get("relationship_status", ""))

    with detail_tab2:
        st.write("**Initially Submitted:**", selected_row.get("eoi_initial_submitted_on", ""))
        st.write("**Last Submitted:**", selected_row.get("eoi_last_submitted_on", ""))
        st.write("**EOI Expiry:**", selected_row.get("eoi_expiry_date", ""))
        st.write("**EOI Status:**", selected_row.get("eoi_status", ""))
        st.write("**Occupation:**", selected_row.get("occupation_name", ""))
        st.write("**ANZSCO Code:**", selected_row.get("anzsco_code", ""))

    with detail_tab3:
        st.write("**English Test:**", selected_row.get("english_test_type", ""))
        st.write("**English Test Date:**", selected_row.get("english_test_date", ""))
        st.write("**English Expiry:**", selected_row.get("english_expiry_date", ""))
        st.write("**English Level:**", selected_row.get("english_level", ""))
        st.write("**Assessing Authority:**", selected_row.get("skills_assessment_authority", ""))
        st.write("**Skills Assessment Date:**", selected_row.get("skills_assessment_date", ""))

    with detail_tab4:
        points_cols = [
            "total_points",
            "age_points",
            "english_points",
            "education_points",
            "aus_work_exp_points",
            "overseas_work_exp_points",
            "partner_points",
            "professional_year_points",
            "aus_study_points",
            "state_nomination_points",
        ]

        for col in points_cols:
            if col in selected_row:
                st.write(f"**{col.replace('_', ' ').title()}:**", selected_row.get(col, ""))


# -----------------------------
# DOWNLOAD
# -----------------------------

st.divider()

with open(OUTPUT_FILE, "rb") as f:
    st.download_button(
        "Download CSV",
        f,
        file_name="eoi_results.csv",
        mime="text/csv"
    )
