from pathlib import Path
from datetime import datetime

import pandas as pd
import streamlit as st
from supabase import create_client

from eoi_pdf_extractor import process_batch


# -----------------------------
# PAGE SETUP
# -----------------------------

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
# SUPABASE FUNCTIONS
# -----------------------------
def clean_name(value):
    value = str(value or "UNKNOWN").upper().strip()
    value = value.replace("&", "AND")
    value = value.replace("/", "_")
    value = value.replace("-", "_")
    value = value.replace(" ", "_")
    value = "".join(c for c in value if c.isalnum() or c == "_")
    while "__" in value:
        value = value.replace("__", "_")
    return value.strip("_") or "UNKNOWN"


def clean_date(value):
    try:
        return datetime.strptime(str(value), "%d/%m/%Y").strftime("%Y%m%d")
    except:
        return "UNKNOWNDATE"


def build_standard_pdf_name(record, pdf_type):
    region = clean_name(record.get("state"))
    subclass = clean_name(record.get("visa_subclass"))
    client = clean_name(record.get("client_name"))
    occupation = clean_name(record.get("occupation_name"))
    eoi_id = clean_name(record.get("eoi_id"))

    first_date = clean_date(record.get("eoi_initial_submitted_on"))
    last_date = clean_date(record.get("eoi_last_submitted_on"))

    time_part = datetime.utcnow().strftime("%H%M%S")

    return f"{region}_{subclass}_{client}_{occupation}_{eoi_id}_{pdf_type}_{first_date}_{last_date}_{time_part}.pdf"
    
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

    return pd.DataFrame(response.data or [])



def save_pdf_record(file_name, storage_path, eoi_id=""):
    supabase.table("uploaded_pdfs").upsert(
        {
            "file_name": file_name,
            "storage_path": storage_path,
            "eoi_id": eoi_id,
            "uploaded_at": datetime.utcnow().isoformat()
        },
        on_conflict="storage_path"
    ).execute()


def load_uploaded_pdfs():
    response = (
        supabase
        .table("uploaded_pdfs")
        .select("*")
        .order("uploaded_at", desc=True)
        .execute()
    )

    return pd.DataFrame(response.data or [])


def clear_database():
    supabase.table("eoi_clients").delete().gte("id", 0).execute()
    supabase.table("uploaded_pdfs").delete().gte("id", 0).execute()


def clear_storage():
    files = supabase.storage.from_("eoi-pdfs").list()

    if files:
        paths = [file["name"] for file in files]
        supabase.storage.from_("eoi-pdfs").remove(paths)


def reset_system():
    clear_storage()
    clear_database()

    for old_file in INPUT_DIR.glob("*.pdf"):
        old_file.unlink()

    for old_file in OUTPUT_DIR.glob("*"):
        if old_file.is_file():
            old_file.unlink()

    st.cache_data.clear()
    st.cache_resource.clear()


# -----------------------------
# HEADER
# -----------------------------

st.title("EOI Client Dashboard")
st.caption("Cloud database + PDF storage connected with Supabase")


# -----------------------------
# SIDEBAR
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
    st.caption("PDFs are saved in Supabase Storage. Extracted data is saved in Supabase Database.")

    st.divider()
    st.subheader("Danger Zone")

    confirm_reset = st.checkbox("I understand this will delete ALL records and PDFs")

    if st.button("Reset System", type="secondary"):
        if confirm_reset:
            with st.spinner("Clearing all database records and PDFs..."):
                reset_system()
            st.success("System reset completed.")
            st.rerun()
        else:
            st.warning("Please tick the confirmation box first.")


# -----------------------------
# PROCESS UPLOAD
# -----------------------------

if uploaded_files and run_button:
    # Clear temp folder
    for old_file in INPUT_DIR.glob("*.pdf"):
        old_file.unlink()

    # Step 1: Save uploaded PDFs locally
    for file in uploaded_files:
        local_path = INPUT_DIR / file.name
        with open(local_path, "wb") as f:
            f.write(file.getbuffer())

    # Step 2: Extract data
    with st.spinner("Extracting PDF data..."):
        process_batch(str(INPUT_DIR), str(OUTPUT_FILE))

    extracted_df = pd.read_csv(OUTPUT_FILE).fillna("")

    # Step 3: Save extracted records
    with st.spinner("Saving extracted records to Supabase database..."):
        saved, skipped = save_records_to_supabase(extracted_df)

    uploaded_storage_paths = []

    # Step 4: Upload PDFs with STANDARD NAMES
    for i, row in extracted_df.iterrows():
        if i >= len(uploaded_files):
            break

        file = uploaded_files[i]
        file_bytes = file.getbuffer()

        # Detect PDF type
        file_name_lower = file.name.lower()
        if "point" in file_name_lower:
            pdf_type = "POINTS"
        else:
            pdf_type = "DETAILS"

        # Build clean filename
        new_name = build_standard_pdf_name(row, pdf_type)

        # Upload to Supabase Storage
        supabase.storage.from_("eoi-pdfs").upload(
            new_name,
            bytes(file_bytes),
            {
                "content-type": "application/pdf",
                "upsert": "true"
            }
        )

        uploaded_storage_paths.append((file.name, new_name))

        # Save PDF record
        save_pdf_record(file.name, new_name, row.get("eoi_id", ""))

    st.success(f"Saved/updated {saved} record(s). Skipped {skipped} record(s).")
    st.info(f"Uploaded {len(uploaded_storage_paths)} PDF(s) with clean naming.")

# -----------------------------
# LOAD DATA
# -----------------------------

df = load_records_from_supabase()
pdf_df = load_uploaded_pdfs()


# -----------------------------
# EMPTY STATE
# -----------------------------

if df.empty:
    st.info("No EOI records saved yet. Upload PDFs and click **Run Extraction & Save**.")

    if not pdf_df.empty:
        st.subheader("Uploaded PDFs")
        st.dataframe(pdf_df, use_container_width=True)

    st.stop()


df = df.fillna("")


# -----------------------------
# METRICS
# -----------------------------

total_clients = len(df)
need_review = len(df[df["review_flag"] == "CHECK"]) if "review_flag" in df.columns else 0

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
    state_options = ["All"] + sorted(df["state"].dropna().unique().tolist()) if "state" in df.columns else ["All"]
    state_filter = st.selectbox("State", state_options)

with f4:
    flag_filter = st.selectbox("Flag", ["All", "CHECK", "OK"])


filtered = df.copy()

if search:
    search_lower = search.lower()
    filtered = filtered[
        filtered.apply(lambda row: search_lower in " ".join(row.astype(str)).lower(), axis=1)
    ]

if visa_filter != "All" and "visa_subclass" in filtered.columns:
    filtered = filtered[filtered["visa_subclass"] == visa_filter]

if state_filter != "All" and "state" in filtered.columns:
    filtered = filtered[filtered["state"] == state_filter]

if flag_filter == "CHECK" and "review_flag" in filtered.columns:
    filtered = filtered[filtered["review_flag"] == "CHECK"]

if flag_filter == "OK" and "review_flag" in filtered.columns:
    filtered = filtered[filtered["review_flag"] != "CHECK"]


# -----------------------------
# MAIN TABS
# -----------------------------

tab1, tab2, tab3 = st.tabs([
    "Client Dashboard",
    "Uploaded PDFs",
    "Download"
])


# -----------------------------
# TAB 1: CLIENT DASHBOARD
# -----------------------------

with tab1:
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

    st.divider()
    st.subheader("Client Detail")

    if "client_name" in filtered.columns and len(filtered) > 0:
        selected = st.selectbox(
            "Select client",
            filtered["client_name"].astype(str).tolist()
        )

        row = filtered[filtered["client_name"].astype(str) == selected].iloc[0]

        d1, d2, d3, d4 = st.tabs([
            "Personal",
            "EOI",
            "English & Skills",
            "Points"
        ])

        with d1:
            st.write("**Client Name:**", row.get("client_name", ""))
            st.write("**EOI ID:**", row.get("eoi_id", ""))
            st.write("**Visa Subclass:**", row.get("visa_subclass", ""))
            st.write("**State:**", row.get("state", ""))
            st.write("**Relationship Status:**", row.get("relationship_status", ""))

        with d2:
            st.write("**Initially Submitted:**", row.get("eoi_initial_submitted_on", ""))
            st.write("**Last Submitted:**", row.get("eoi_last_submitted_on", ""))
            st.write("**EOI Expiry:**", row.get("eoi_expiry_date", ""))
            st.write("**Days Remaining:**", row.get("eoi_days_remaining", ""))
            st.write("**Occupation:**", row.get("occupation_name", ""))
            st.write("**ANZSCO Code:**", row.get("anzsco_code", ""))

        with d3:
            st.write("**English Test:**", row.get("english_test_type", ""))
            st.write("**English Test Date:**", row.get("english_test_date", ""))
            st.write("**English Expiry:**", row.get("english_expiry_date", ""))
            st.write("**English Level:**", row.get("english_level", ""))
            st.write("**Skills Authority:**", row.get("skills_assessment_authority", ""))
            st.write("**Skills Date:**", row.get("skills_assessment_date", ""))

        with d4:
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
                st.write(
                    f"**{field.replace('_', ' ').title()}:**",
                    row.get(field, "")
                )


# -----------------------------
# TAB 2: UPLOADED PDFS
# -----------------------------

with tab2:
    st.subheader("Uploaded PDFs")

    if pdf_df.empty:
        st.info("No PDFs uploaded yet.")
    else:
        st.dataframe(
            pdf_df,
            use_container_width=True,
            height=450
        )


# -----------------------------
# TAB 3: DOWNLOAD
# -----------------------------

with tab3:
    st.subheader("Download Database")

    csv_data = df.to_csv(index=False).encode("utf-8")

    st.download_button(
        "Download Full Database CSV",
        csv_data,
        file_name="eoi_database_export.csv",
        mime="text/csv"
    )

    if not pdf_df.empty:
        pdf_csv = pdf_df.to_csv(index=False).encode("utf-8")

        st.download_button(
            "Download Uploaded PDF List CSV",
            pdf_csv,
            file_name="uploaded_pdfs_export.csv",
            mime="text/csv"
        )
