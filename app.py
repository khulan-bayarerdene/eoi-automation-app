import os
from pathlib import Path
from datetime import datetime

import pandas as pd
import streamlit as st
from supabase import create_client

from eoi_pdf_extractor import process_batch


st.set_page_config(
    page_title="EOI Client Dashboard",
    page_icon="📄",
    layout="wide"
)

INPUT_DIR = Path("input_pdfs")
OUTPUT_DIR = Path("output")
OUTPUT_FILE = OUTPUT_DIR / "eoi_results.csv"

INPUT_DIR.mkdir(exist_ok=True)
OUTPUT_DIR.mkdir(exist_ok=True)


# -----------------------------
# SUPABASE CONNECTION
# -----------------------------

@st.cache_resource
def get_supabase():
    url = st.secrets["SUPABASE_URL"]
    key = st.secrets["SUPABASE_KEY"]
    return create_client(url, key)


supabase = get_supabase()


# -----------------------------
# DATABASE FUNCTIONS
# -----------------------------

def save_records_to_supabase(df):
    saved = 0
    skipped = 0

    for _, row in df.iterrows():
        record = row.fillna("").to_dict()

        if not record.get("eoi_id"):
            skipped += 1
            continue

        record["updated_at"] = datetime.utcnow().isoformat()

        supabase.table("eoi_clients").upsert(
            record,
            on_conflict="eoi_id"
        ).execute()

        saved += 1

    return saved, skipped


def load_records_from_supabase():
    response = (
        supabase
        .table("eoi_clients")
        .select("*")
        .order("updated_at", desc=True)
        .execute()
    )

    data = response.data or []
    return pd.DataFrame(data)


# -----------------------------
# HEADER
# -----------------------------

st.title("EOI Client Dashboard")
st.caption("Persistent cloud database connected with Supabase")


# -----------------------------
# SIDEBAR UPLOAD
# -----------------------------

with st.sidebar:
    st.header("Upload PDFs")

    uploaded_files = st.file_uploader(
        "Upload EOI PDFs",
        type=["pdf"],
        accept_multiple_files=True
    )

    run_button = st.button("Run Extraction & Save", type="primary")

    st.divider()
    st.caption("Data will be saved permanently in Supabase.")


# -----------------------------
# PROCESS UPLOADS
# -----------------------------

if uploaded_files and run_button:
    # Clear temporary input folder
    for old_file in INPUT_DIR.glob("*.pdf"):
        old_file.unlink()

    # Save uploaded PDFs temporarily
    for file in uploaded_files:
        with open(INPUT_DIR / file.name, "wb") as f:
            f.write(file.getbuffer())

    with st.spinner("Extracting PDF data..."):
        process_batch(str(INPUT_DIR), str(OUTPUT_FILE))

    extracted_df = pd.read_csv(OUTPUT_FILE).fillna("")

    with st.spinner("Saving extracted records to Supabase..."):
        saved, skipped = save_records_to_supabase(extracted_df)

    st.success(f"Saved/updated {saved} record(s). Skipped {skipped} record(s) without EOI ID.")


# -----------------------------
# LOAD DASHBOARD DATA
# -----------------------------

df = load_records_from_supabase()

if df.empty:
    st.info("No records in database yet. Upload PDFs and run extraction.")
    st.stop()

df = df.fillna("")


# -----------------------------
# METRICS
# -----------------------------

total_clients = len(df)
need_review = len(df[df["review_flag"] == "CHECK"]) if "review_flag" in df.columns else 0
ready_clients = total_clients - need_review

expired_eoi = 0
urgent_eoi = 0

if "eoi_days_remaining" in df.columns:
    days = pd.to_numeric(df["eoi_days_remaining"], errors="coerce")
    expired_eoi = len(df[days <= 0])
    urgent_eoi = len(df[(days > 0) & (days <= 90)])

col1, col2, col3, col4 = st.columns(4)

col1.metric("Total Clients", total_clients)
col2.metric("Need Review", need_review)
col3.metric("Expired EOI", expired_eoi)
col4.metric("EOI < 90 Days", urgent_eoi)

st.divider()


# -----------------------------
# FILTERS
# -----------------------------

f1, f2, f3, f4 = st.columns(4)

with f1:
    search = st.text_input("Search")

with f2:
    visa_options = ["All"] + sorted(df["visa_subclass"].dropna().unique().tolist()) if "visa_subclass" in df.columns else ["All"]
    visa_filter = st.selectbox("Visa", visa_options)

with f3:
    flag_filter = st.selectbox("Flag", ["All", "CHECK", "OK"])

with f4:
    state_options = ["All"] + sorted(df["state"].dropna().unique().tolist()) if "state" in df.columns else ["All"]
    state_filter = st.selectbox("State", state_options)


filtered = df.copy()

if search:
    search_lower = search.lower()
    filtered = filtered[
        filtered.apply(lambda row: search_lower in " ".join(row.astype(str)).lower(), axis=1)
    ]

if visa_filter != "All" and "visa_subclass" in filtered.columns:
    filtered = filtered[filtered["visa_subclass"] == visa_filter]

if flag_filter == "CHECK" and "review_flag" in filtered.columns:
    filtered = filtered[filtered["review_flag"] == "CHECK"]

if flag_filter == "OK" and "review_flag" in filtered.columns:
    filtered = filtered[filtered["review_flag"] != "CHECK"]

if state_filter != "All" and "state" in filtered.columns:
    filtered = filtered[filtered["state"] == state_filter]


# -----------------------------
# TABLE
# -----------------------------

display_columns = [
    "client_name",
    "eoi_id",
    "visa_subclass",
    "state",
    "occupation_name",
    "total_points",
    "eoi_expiry_date",
    "eoi_days_remaining",
    "english_test_type",
    "english_test_date",
    "english_expiry_date",
    "skills_assessment_authority",
    "skills_assessment_date",
    "review_flag",
    "review_notes",
    "updated_at",
]

display_columns = [c for c in display_columns if c in filtered.columns]

st.subheader(f"Showing {len(filtered)} of {len(df)} records")

st.dataframe(
    filtered[display_columns],
    use_container_width=True,
    height=500
)


# -----------------------------
# DETAIL VIEW
# -----------------------------

st.divider()
st.subheader("Client Detail")

if "client_name" in filtered.columns and len(filtered) > 0:
    selected = st.selectbox(
        "Select client",
        filtered["client_name"].astype(str).tolist()
    )

    row = filtered[filtered["client_name"].astype(str) == selected].iloc[0]

    tab1, tab2, tab3, tab4 = st.tabs([
        "Personal",
        "EOI",
        "English & Skills",
        "Points"
    ])

    with tab1:
        st.write("**Client Name:**", row.get("client_name", ""))
        st.write("**EOI ID:**", row.get("eoi_id", ""))
        st.write("**Visa Subclass:**", row.get("visa_subclass", ""))
        st.write("**State:**", row.get("state", ""))
        st.write("**Relationship Status:**", row.get("relationship_status", ""))

    with tab2:
        st.write("**Initially Submitted:**", row.get("eoi_initial_submitted_on", ""))
        st.write("**Last Submitted:**", row.get("eoi_last_submitted_on", ""))
        st.write("**EOI Expiry:**", row.get("eoi_expiry_date", ""))
        st.write("**Days Remaining:**", row.get("eoi_days_remaining", ""))
        st.write("**Occupation:**", row.get("occupation_name", ""))
        st.write("**ANZSCO Code:**", row.get("anzsco_code", ""))

    with tab3:
        st.write("**English Test:**", row.get("english_test_type", ""))
        st.write("**English Test Date:**", row.get("english_test_date", ""))
        st.write("**English Expiry:**", row.get("english_expiry_date", ""))
        st.write("**English Level:**", row.get("english_level", ""))
        st.write("**Skills Authority:**", row.get("skills_assessment_authority", ""))
        st.write("**Skills Date:**", row.get("skills_assessment_date", ""))

    with tab4:
        points_fields = [
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

        for field in points_fields:
            st.write(f"**{field.replace('_', ' ').title()}:**", row.get(field, ""))


# -----------------------------
# DOWNLOAD DATABASE CSV
# -----------------------------

st.divider()

csv_data = df.to_csv(index=False).encode("utf-8")

st.download_button(
    "Download Full Database CSV",
    csv_data,
    file_name="eoi_database_export.csv",
    mime="text/csv"
)
