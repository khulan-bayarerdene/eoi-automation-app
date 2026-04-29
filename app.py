import streamlit as st
import pandas as pd
import os
from eoi_pdf_extractor import process_batch

st.set_page_config(page_title="EOI Automation", layout="wide")

st.title("EOI Automation System")
st.write("Upload EOI PDFs and extract data automatically.")

os.makedirs("input_pdfs", exist_ok=True)
os.makedirs("output", exist_ok=True)

uploaded_files = st.file_uploader(
    "Upload PDF files",
    type=["pdf"],
    accept_multiple_files=True
)

if uploaded_files:
    for file in uploaded_files:
        with open(os.path.join("input_pdfs", file.name), "wb") as f:
            f.write(file.getbuffer())

    st.success("PDF files uploaded successfully.")

    if st.button("Extract Data"):
        output_file = "output/eoi_results.csv"
        process_batch("input_pdfs", output_file)

        df = pd.read_csv(output_file)
        st.dataframe(df, use_container_width=True)

        with open(output_file, "rb") as f:
            st.download_button(
                "Download Results CSV",
                f,
                file_name="eoi_results.csv",
                mime="text/csv"
            )