import streamlit as st
import pandas as pd
import os
from eoi_pdf_extractor import process_batch

# Page setup
st.set_page_config(
    page_title="EOI Automation Dashboard",
    page_icon="📄",
    layout="wide"
)

# Create folders
os.makedirs("input_pdfs", exist_ok=True)
os.makedirs("output", exist_ok=True)

# Sidebar
st.sidebar.title("EOI Automation")
st.sidebar.write("Upload EOI PDFs, extract data, review issues, and download results.")

uploaded_files = st.sidebar.file_uploader(
    "Upload EOI PDF files",
    type=["pdf"],
    accept_multiple_files=True
)

process_button = st.sidebar.button("Run Extraction")

# Main title
st.title("EOI Automation Dashboard")
st.write("A dashboard for extracting, reviewing, and exporting EOI client data.")

# Top info cards
col1, col2, col3, col4 = st.columns(4)

with col1:
    st.metric("Uploaded PDFs", len(uploaded_files) if uploaded_files else 0)

with col2:
    st.metric("Processed EOIs", 0)

with col3:
    st.metric("Need Review", 0)

with col4:
    st.metric("Ready Records", 0)

st.divider()

# Processing section
if uploaded_files and process_button:
    # Clear old input files first
    for old_file in os.listdir("input_pdfs"):
        if old_file.lower().endswith(".pdf"):
            os.remove(os.path.join("input_pdfs", old_file))

    # Save uploaded files
    for file in uploaded_files:
        file_path = os.path.join("input_pdfs", file.name)
        with open(file_path, "wb") as f:
            f.write(file.getbuffer())

    with st.spinner("Processing uploaded PDFs..."):
        output_file = "output/eoi_results.csv"
        process_batch("input_pdfs", output_file)

    df = pd.read_csv(output_file)

    total_records = len(df)
    review_records = len(df[df["review_flag"] == "CHECK"]) if "review_flag" in df.columns else 0
    ready_records = total_records - review_records

    st.success("Extraction completed successfully.")

    # Dashboard metrics after processing
    col1, col2, col3, col4 = st.columns(4)

    with col1:
        st.metric("Uploaded PDFs", len(uploaded_files))

    with col2:
        st.metric("Processed EOIs", total_records)

    with col3:
        st.metric("Need Review", review_records)

    with col4:
        st.metric("Ready Records", ready_records)

    st.divider()

    # Tabs
    tab1, tab2, tab3, tab4 = st.tabs([
        "Extracted Data",
        "Review Required",
        "Summary",
        "Download"
    ])

    with tab1:
        st.subheader("All Extracted Data")
        st.dataframe(df, use_container_width=True)

    with tab2:
        st.subheader("Records That Need Review")

        if "review_flag" in df.columns:
            review_df = df[df["review_flag"] == "CHECK"]
            if len(review_df) > 0:
                st.warning(f"{len(review_df)} record(s) need manual review.")
                st.dataframe(review_df, use_container_width=True)
            else:
                st.success("No records need review.")
        else:
            st.info("No review flag column found.")

    with tab3:
        st.subheader("Extraction Summary")

        st.write("Total records extracted:", total_records)
        st.write("Records needing review:", review_records)
        st.write("Ready records:", ready_records)

        if "visa_subclass" in df.columns:
            st.subheader("Visa Subclass Breakdown")
            st.bar_chart(df["visa_subclass"].value_counts())

        if "state" in df.columns:
            st.subheader("State Breakdown")
            st.bar_chart(df["state"].value_counts())

    with tab4:
        st.subheader("Download Results")

        with open(output_file, "rb") as f:
            st.download_button(
                label="Download CSV",
                data=f,
                file_name="eoi_results.csv",
                mime="text/csv"
            )

else:
    st.info("Upload EOI PDFs from the sidebar, then click Run Extraction.")
