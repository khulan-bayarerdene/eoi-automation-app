"""
EOI PDF Extractor — Success Education & Visa
=============================================
Processes EOI Details + Points Breakdown PDFs.
Rules:
  - NO filename logic. All data from PDF content only.
  - Pair by EOI ID (content-extracted), never by filename or name.
  - Flag missing critical fields with review_flag = CHECK.
  - Output: staging CSV + raw debug CSV.

Usage:
  py eoi_pdf_extractor.py input --output output/eoi_staging_output.csv
  py eoi_pdf_extractor.py input_pdfs --output output/eoi_staging_output.csv
"""

import os
import re
import csv
import argparse
import logging
from datetime import datetime, timedelta
from pathlib import Path

import pdfplumber

# ──────────────────────────────────────────────
# CONFIG
# ──────────────────────────────────────────────

# Fields that trigger review_flag = CHECK if missing
CRITICAL_FIELDS = [
    "client_name",
    "eoi_id",
    "visa_subclass",
    "occupation_name",
    "anzsco_code",
    "total_points",
    "english_test_date",
    "skills_assessment_date",
]

# Staging CSV columns (order matters)
STAGING_COLUMNS = [
    "source_files",
    "client_name",
    "eoi_id",
    "visa_subclass",
    "state",
    "relationship_status",
    "eoi_initial_submitted_on",
    "eoi_last_submitted_on",
    "eoi_expiry_date",
    "eoi_days_remaining",
    "occupation_name",
    "anzsco_code",
    "english_test_type",
    "english_test_date",
    "english_expiry_date",
    "english_days_remaining",
    "english_level",
    "skills_assessment_authority",
    "skills_assessment_date",
    "skills_assessment_ref",
    "partner_dob",
    "partner_english_test_type",
    "partner_english_test_date",
    "partner_english_expiry_date",
    "partner_english_level",
    "partner_has_occupation",
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
    "review_flag",
    "review_notes",
]

# ──────────────────────────────────────────────
# LOGGING
# ──────────────────────────────────────────────

def setup_logging(log_dir: Path):
    log_dir.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    log_file = log_dir / f"eoi_run_{timestamp}.log"
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(message)s",
        handlers=[
            logging.FileHandler(log_file),
            logging.StreamHandler(),
        ],
    )
    return logging.getLogger(__name__)

# ──────────────────────────────────────────────
# PDF TEXT EXTRACTION
# ──────────────────────────────────────────────

def extract_text_from_pdf(pdf_path: str) -> tuple[str, str]:
    """
    Returns (raw_text, squashed_text).
    raw_text   = pages joined with newlines, layout preserved.
    squashed   = all whitespace collapsed to single space (for squashed table rows in Points PDFs).
    """
    raw_pages = []
    try:
        with pdfplumber.open(pdf_path) as pdf:
            for page in pdf.pages:
                text = page.extract_text() or ""
                raw_pages.append(text)
    except Exception as e:
        logging.warning(f"pdfplumber failed on {pdf_path}: {e}")
        return "", ""

    raw_text = "\n".join(raw_pages)
    squashed = re.sub(r"\s+", " ", raw_text).strip()
    return raw_text, squashed


# ──────────────────────────────────────────────
# PDF CLASSIFICATION  (content only, no filename)
# ──────────────────────────────────────────────

def classify_pdf(raw_text: str, squashed: str) -> str:
    """
    Returns 'details' | 'points' | 'unknown'.
    Logic based purely on content signals.
    """
    # Strong points-PDF signals
    points_signals = [
        r"SkillSelect EOI ID:",
        r"This points calculation is indicative only",
        r"TOTAL\s+\d+",
        r"TOTALs*\d+",          # squashed form
        r"DateofEffect",         # squashed header in table
    ]
    for sig in points_signals:
        if re.search(sig, raw_text, re.IGNORECASE) or re.search(sig, squashed, re.IGNORECASE):
            return "points"

    # Strong details-PDF signals
    details_signals = [
        r"Expression of Interest ID\s+E\d+",
        r"EOI Initially Submitted On",
        r"Nominated occupation",
        r"Name of assessing authority",
        r"Family name\s+\w+",
    ]
    for sig in details_signals:
        if re.search(sig, raw_text, re.IGNORECASE):
            return "details"

    return "unknown"


# ──────────────────────────────────────────────
# HELPERS
# ──────────────────────────────────────────────

def first_match(patterns: list, text: str, group: int = 1) -> str:
    """Try each regex pattern in order; return first match or ''."""
    for pat in patterns:
        m = re.search(pat, text, re.IGNORECASE)
        if m:
            try:
                return m.group(group).strip()
            except IndexError:
                pass
    return ""


def parse_date(date_str: str) -> datetime | None:
    """Parse dd/mm/yyyy dates."""
    if not date_str:
        return None
    for fmt in ("%d/%m/%Y", "%d/%m/%y"):
        try:
            return datetime.strptime(date_str.strip(), fmt)
        except ValueError:
            pass
    return None


def fmt_date(dt: datetime | None) -> str:
    return dt.strftime("%d/%m/%Y") if dt else ""


def days_remaining(target_date: datetime | None) -> str:
    if not target_date:
        return ""
    delta = (target_date - datetime.now()).days
    return str(delta)


# ──────────────────────────────────────────────
# EXTRACTION — DETAILS PDF
# ──────────────────────────────────────────────

def extract_details(raw_text: str, squashed: str, filename: str) -> dict:
    d = {}

    # EOI ID
    d["eoi_id"] = first_match([
        r"Expression of Interest ID\s+(E\d+)",
        r"EOI ID\s+(E\d+)",
        r"EOIID:\s*(E\d+)",
    ], raw_text) or first_match([
        r"ExpressionofInterestID\s*(E\d+)",
        r"EOIID:(E\d+)",
    ], squashed)

    # Client name — "Given names <X>\n" + "Family name <Y>"
    given = first_match([
        r"Given names\s+([A-Za-z][A-Za-z '-]+?)(?:\n|Sex|Date)",
        r"Given names\s+(.+)",
    ], raw_text)
    family = first_match([
        r"Family name\s+([A-Za-z][A-Za-z '-]+?)(?:\n|Given)",
        r"Family name\s+(.+)",
    ], raw_text)
    if given and family:
        d["client_name"] = f"{given.strip()} {family.strip()}"
    else:
        d["client_name"] = (given or family or "").strip()

    # Dates
    d["eoi_initial_submitted_on"] = first_match([
        r"EOI Initially Submitted On\s+(\d{2}/\d{2}/\d{4})",
    ], raw_text)
    d["eoi_last_submitted_on"] = first_match([
        r"EOI Last Submitted On\s+(\d{2}/\d{2}/\d{4})",
        r"EOI Last Submitted On:\s+\w+,\s+\d+\s+\w+\s+\d{4}",  # long form — skip, rely on short
    ], raw_text)

    # Visa subclass(es) — collect all mentioned
    visa_matches = re.findall(
        r"Subclass\s*(\d{3})", raw_text, re.IGNORECASE
    )
    # Deduplicate while preserving order
    seen = []
    for v in visa_matches:
        if v not in seen:
            seen.append(v)
    d["visa_subclass"] = " / ".join(seen) if seen else ""

    # State — match known state names only
    STATE_NAMES = [
        "Australian Capital Territory", "New South Wales", "Victoria",
        "Queensland", "South Australia", "Western Australia",
        "Tasmania", "Northern Territory",
    ]
    state_pattern = "|".join(re.escape(s) for s in STATE_NAMES)
    state_m = re.search(rf"^State\s+({state_pattern})", raw_text, re.IGNORECASE | re.MULTILINE)
    d["state"] = state_m.group(1) if state_m else ""
    # If not in resident section, try preferred nomination state
    if not d["state"]:
        nom_m = re.search(
            rf"interested in receiving a nomination\s+from\?\s+({state_pattern})",
            raw_text, re.IGNORECASE
        )
        d["state"] = nom_m.group(1) + " (nomination)" if nom_m else ""

    # Relationship status
    d["relationship_status"] = first_match([
        r"Relationship status\s+(MARRIED|NEVER MARRIED|DE FACTO|WIDOWED|SEPARATED|DIVORCED)",
    ], raw_text)

    # English test (client's own — skip partner section)
    # Find the "English language" section then look for test details
    eng_section_match = re.search(
        r"Provide details of the most recent English test\s*\n(.+?)(?=Education|Australian study|Credentialled|$)",
        raw_text, re.DOTALL | re.IGNORECASE
    )
    if eng_section_match:
        eng_block = eng_section_match.group(1)
        d["english_test_type"] = first_match([r"Name of test\s+(.+)"], eng_block)
        d["english_test_date"] = first_match([r"Date of test.*?(\d{2}/\d{2}/\d{4})"], eng_block)
        d["english_level"] = first_match([r"Language ability\s+(.+)"], eng_block)
    else:
        # Fallback: grab from raw text but skip lines mentioning "partner"
        lines = raw_text.split("\n")
        in_partner = False
        for i, line in enumerate(lines):
            if "partner" in line.lower() and "test" in line.lower():
                in_partner = True
            if in_partner and "language ability" in line.lower():
                in_partner = False  # partner section ended
                continue
            if not in_partner:
                if "name of test" in line.lower() and not d.get("english_test_type"):
                    d["english_test_type"] = line.split("test")[-1].strip()
                if "date of test" in line.lower() and not d.get("english_test_date"):
                    m = re.search(r"(\d{2}/\d{2}/\d{4})", line)
                    if m:
                        d["english_test_date"] = m.group(1)
                if "language ability" in line.lower() and not d.get("english_level"):
                    d["english_level"] = line.split("ability")[-1].strip()

    # Partner qualifications
    # The partner section appears BEFORE the client's own English section
    # Look for the partner block bounded by "Partner qualifications" heading
    partner_block_m = re.search(
        r"Partner qualifications\s*\n(.+?)(?=Preferred locations|English language\nHas the client undertaken)",
        raw_text, re.DOTALL | re.IGNORECASE
    )
    if partner_block_m:
        pb = partner_block_m.group(1)
        d["partner_dob"] = first_match([r"Partner's date of birth.*?(\d{2}/\d{2}/\d{4})"], pb)
        d["partner_english_test_type"] = first_match([r"Name of test\s+(.+)"], pb)
        d["partner_english_test_date"] = first_match([r"Date of test.*?(\d{2}/\d{2}/\d{4})"], pb)
        d["partner_english_level"] = first_match([r"Language ability\s+(.+)"], pb)
        d["partner_has_occupation"] = first_match([r"Does the client's partner have a nominated occupation\?\s+(Yes|No)"], pb)
    else:
        # Fallback — grab partner DOB from anywhere
        d["partner_dob"] = first_match([r"Partner's date of birth.*?(\d{2}/\d{2}/\d{4})"], raw_text)
        d["partner_english_test_type"] = ""
        d["partner_english_test_date"] = ""
        d["partner_english_level"] = ""
        d["partner_has_occupation"] = ""

    # Skills assessment
    d["skills_assessment_authority"] = first_match([
        r"Name of assessing authority\s+(.+)",
    ], raw_text)
    d["skills_assessment_date"] = first_match([
        r"Date of skills assessment.*?(\d{2}/\d{2}/\d{4})",
    ], raw_text)
    d["skills_assessment_ref"] = first_match([
        r"Reference number/receipt number\s+(.+)",
    ], raw_text)

    # Occupation
    occ_raw = first_match([
        r"Nominated occupation\s+(.+)",
    ], raw_text)
    if occ_raw:
        # "Systems Analyst - 261112"  or  "Finance Manager - 132211"
        occ_match = re.match(r"(.+?)\s*[-–]\s*(\d{6})", occ_raw)
        if occ_match:
            d["occupation_name"] = occ_match.group(1).strip()
            d["anzsco_code"] = occ_match.group(2).strip()
        else:
            d["occupation_name"] = occ_raw.strip()
            d["anzsco_code"] = ""
    else:
        d["occupation_name"] = ""
        d["anzsco_code"] = ""

    return d


# ──────────────────────────────────────────────
# EXTRACTION — POINTS PDF
# ──────────────────────────────────────────────

def extract_points(raw_text: str, squashed: str, filename: str) -> dict:
    d = {}

    # EOI ID — appears in clean form at top: "SkillSelect EOI ID: E0021584056"
    d["eoi_id"] = first_match([
        r"SkillSelect EOI ID:\s*(E\d+)",
        r"EOI ID:\s*(E\d+)",
        r"EOIID:\s*(E\d+)",
    ], raw_text) or first_match([
        r"SkillSelectEOIID:\s*(E\d+)",
        r"EOIID:(E\d+)",
    ], squashed)

    # Client name: "Client: Ajaya Sapkota" appears in squashed form
    d["client_name"] = first_match([
        r"Client:\s*([A-Za-z]+(?: [A-Za-z]+)+)",
        r"Client:\s*(.+?)(?:EOI|$)",
    ], squashed)
    # Also try raw
    if not d["client_name"]:
        d["client_name"] = first_match([r"Client:\s*(.+)"], raw_text)

    # TOTAL points — may appear as "TOTAL 75" or "TOTAL 75 85" (multi-subclass)
    # In squashed: "TOTAL75" or "TOTAL7585"
    total_raw = first_match([
        r"TOTAL\s+(\d+(?:\s+\d+)*)",
    ], raw_text) or first_match([
        r"TOTAL(\d+(?:\s*\d+)*)",
    ], squashed)
    if total_raw:
        # If multiple numbers (multi-subclass), take the LAST (highest, usually 491)
        nums = re.findall(r"\d+", total_raw)
        d["total_points"] = nums[-1] if nums else ""
    else:
        d["total_points"] = ""

    # Individual point items — from squashed text (table rows are squashed)
    # Pattern: "Age 25-32 30" or "Age25-3230" or "Age 25-32 30 30" (multi-col)
    def get_points(label_pattern: str) -> str:
        """Extract point value(s) for a criteria label from squashed.
        Strategy: find label, skip the bracket text, grab trailing number(s).
        For multi-subclass tables, take the LAST number (usually highest).
        """
        m = re.search(label_pattern + r"(.{0,120}?)(\d+)(?:\s+(\d+))?(?:\s+(\d+))?(?=\s*[A-Z]|\s*$|\s*PDF)", squashed, re.IGNORECASE)
        if m:
            # Collect all captured digit groups, return last non-None
            candidates = [g for g in [m.group(2), m.group(3), m.group(4)] if g is not None]
            return candidates[-1] if candidates else ""
        return ""

    # Age: "Age25-3230" or "Age33-392525" — number after the bracket (e.g. "25-32")
    age_m = re.search(r"Age\s*(\d+)\s*-\s*(\d+)\s*(\d+)(?:\s+(\d+))?", squashed, re.IGNORECASE)
    if age_m:
        # group(3) is first points col, group(4) is second (multi-subclass)
        d["age_points"] = age_m.group(4) or age_m.group(3)
    else:
        d["age_points"] = get_points(r"Age\s*\d")
    d["english_points"] = get_points(r"EnglishLanguageAbility")
    d["education_points"] = get_points(r"Levelofeducational")
    d["aus_work_exp_points"] = get_points(r"YearsofexperienceinNominatedOccupation-inAustralia")
    d["overseas_work_exp_points"] = get_points(r"Yearsofexperienceina?NominatedOccupation-overseas")
    d["partner_points"] = get_points(r"PartnerQualifications")
    d["professional_year_points"] = get_points(r"ProfessionalYear")
    d["aus_study_points"] = get_points(r"AustralianStudy")
    d["state_nomination_points"] = get_points(r"State/Territory")

    return d


# ──────────────────────────────────────────────
# EXPIRY CALCULATIONS
# ──────────────────────────────────────────────

def calculate_expiries(record: dict) -> dict:
    today = datetime.now()

    # EOI expiry = last submitted + 2 years
    eoi_last = parse_date(record.get("eoi_last_submitted_on", ""))
    if eoi_last:
        eoi_expiry = eoi_last + timedelta(days=730)
        record["eoi_expiry_date"] = fmt_date(eoi_expiry)
        record["eoi_days_remaining"] = days_remaining(eoi_expiry)
    else:
        record["eoi_expiry_date"] = ""
        record["eoi_days_remaining"] = ""

    # English expiry = test date + 3 years
    eng_date = parse_date(record.get("english_test_date", ""))
    if eng_date:
        eng_expiry = eng_date + timedelta(days=1095)
        record["english_expiry_date"] = fmt_date(eng_expiry)
        record["english_days_remaining"] = days_remaining(eng_expiry)
    else:
        record["english_expiry_date"] = ""
        record["english_days_remaining"] = ""

    # Partner English expiry = partner test date + 3 years
    partner_eng_date = parse_date(record.get("partner_english_test_date", ""))
    if partner_eng_date:
        partner_eng_expiry = partner_eng_date + timedelta(days=1095)
        record["partner_english_expiry_date"] = fmt_date(partner_eng_expiry)
    else:
        record["partner_english_expiry_date"] = ""

    # Skills assessment expiry — leave blank per spec
    return record


# ──────────────────────────────────────────────
# REVIEW FLAG
# ──────────────────────────────────────────────

def apply_review_flag(record: dict) -> dict:
    missing = [f for f in CRITICAL_FIELDS if not record.get(f)]
    if missing:
        record["review_flag"] = "CHECK"
        record["review_notes"] = "Missing: " + ", ".join(missing)
    else:
        record["review_flag"] = ""
        record["review_notes"] = ""
    return record


# ──────────────────────────────────────────────
# MAIN PIPELINE
# ──────────────────────────────────────────────

def process_batch(input_dir: str, output_file: str):
    input_path = Path(input_dir)
    output_path = Path(output_file)
    output_path.parent.mkdir(parents=True, exist_ok=True)

    logger = logging.getLogger(__name__)
    if not logger.handlers:
        logging.basicConfig(level=logging.INFO, format="%(message)s")
    logger.info(f"Processing PDFs in: {input_path.resolve()}")

    pdf_files = sorted(input_path.glob("**/*.pdf"))
    logger.info(f"Found {len(pdf_files)} PDF(s)")

    # Step 1: Extract and classify all PDFs
    raw_records = []   # for debug output
    details_map = {}   # eoi_id -> details dict
    points_map  = {}   # eoi_id -> points dict
    unmatched   = []   # PDFs with no EOI ID

    for pdf_path in pdf_files:
        logger.info(f"  Reading: {pdf_path.name}")
        raw_text, squashed = extract_text_from_pdf(str(pdf_path))
        pdf_type = classify_pdf(raw_text, squashed)

        # Quick EOI ID guess for debug output
        eoi_id_guess = (
            first_match([r"Expression of Interest ID\s+(E\d+)", r"SkillSelect EOI ID:\s*(E\d+)", r"EOIID:\s*(E\d+)"], raw_text)
            or first_match([r"(E\d{10})", r"EOIID:(E\d+)"], squashed)
        )
        client_name_guess = (
            first_match([r"Given names\s+(.+?)\n", r"Client:\s*([A-Za-z]+(?: [A-Za-z]+)+)"], raw_text)
            or first_match([r"Client:([A-Za-z]+(?:[A-Za-z]+)+)"], squashed)
        )

        raw_records.append({
            "file_name": pdf_path.name,
            "pdf_type": pdf_type,
            "eoi_id_guess": eoi_id_guess,
            "client_name_guess": client_name_guess,
            "raw_text": raw_text[:5000],
            "squashed_text": squashed[:3000],
        })

        if pdf_type == "details":
            data = extract_details(raw_text, squashed, pdf_path.name)
            data["_source_file"] = pdf_path.name
            eid = data.get("eoi_id", "")
            if eid:
                details_map[eid] = data
                logger.info(f"    -> details | EOI: {eid} | Client: {data.get('client_name')}")
            else:
                logger.warning(f"    -> details but NO EOI ID extracted — marked for review")
                unmatched.append(("details", data))

        elif pdf_type == "points":
            data = extract_points(raw_text, squashed, pdf_path.name)
            data["_source_file"] = pdf_path.name
            eid = data.get("eoi_id", "")
            if eid:
                points_map[eid] = data
                logger.info(f"    -> points  | EOI: {eid} | Total: {data.get('total_points')}")
            else:
                logger.warning(f"    -> points but NO EOI ID extracted — marked for review")
                unmatched.append(("points", data))

        else:
            logger.warning(f"    -> UNKNOWN type — cannot classify {pdf_path.name}")
            unmatched.append(("unknown", {"_source_file": pdf_path.name}))

    # Step 2: Pair by EOI ID (content only)
    all_eoi_ids = set(details_map.keys()) | set(points_map.keys())
    logger.info(f"\nPairing {len(all_eoi_ids)} unique EOI IDs...")

    staging_rows = []

    for eid in sorted(all_eoi_ids):
        det = details_map.get(eid, {})
        pts = points_map.get(eid, {})

        record = {}

        # Source files
        sources = []
        if det.get("_source_file"): sources.append(det["_source_file"])
        if pts.get("_source_file"): sources.append(pts["_source_file"])
        record["source_files"] = " | ".join(sources)

        # Merge: details fields
        for field in [
            "client_name", "eoi_id", "visa_subclass", "state", "relationship_status",
            "eoi_initial_submitted_on", "eoi_last_submitted_on",
            "occupation_name", "anzsco_code",
            "english_test_type", "english_test_date", "english_level",
            "skills_assessment_authority", "skills_assessment_date", "skills_assessment_ref",
            "partner_dob", "partner_english_test_type", "partner_english_test_date",
            "partner_english_level", "partner_has_occupation",
        ]:
            record[field] = det.get(field, "") or pts.get(field, "")

        # Merge: points fields
        for field in [
            "total_points", "age_points", "english_points", "education_points",
            "aus_work_exp_points", "overseas_work_exp_points", "partner_points",
            "professional_year_points", "aus_study_points", "state_nomination_points",
        ]:
            record[field] = pts.get(field, "")

        # Client name: prefer details, fallback to points
        if not record.get("client_name"):
            record["client_name"] = pts.get("client_name", "")

        # If only one side exists, note it
        if not det:
            record.setdefault("review_notes", "")
            record["review_notes"] += " No details PDF found."
        if not pts:
            record.setdefault("review_notes", "")
            record["review_notes"] += " No points PDF found."

        # Expiry calculations
        record = calculate_expiries(record)

        # Review flag
        record = apply_review_flag(record)

        staging_rows.append(record)
        logger.info(f"  Paired EOI {eid}: {record.get('client_name')} | {record.get('total_points')} pts | flag={record.get('review_flag')}")

    # Add unmatched (no EOI ID) as CHECK rows
    for utype, udata in unmatched:
        record = {col: "" for col in STAGING_COLUMNS}
        record["source_files"] = udata.get("_source_file", "")
        record["eoi_id"] = ""
        record["review_flag"] = "CHECK"
        record["review_notes"] = f"Could not extract EOI ID from {utype} PDF — manual review required"
        record = calculate_expiries(record)
        staging_rows.append(record)

    # Step 3: Write outputs
    # Staging CSV — exact path the user specified
    write_csv(output_path, STAGING_COLUMNS, staging_rows)
    logger.info(f"\nOK Staging output: {output_path}")



    # Summary
    check_count = sum(1 for r in staging_rows if r.get("review_flag") == "CHECK")
    logger.info(f"\n{'='*50}")
    logger.info(f"SUMMARY")
    logger.info(f"  PDFs processed:  {len(pdf_files)}")
    logger.info(f"  EOIs extracted:  {len(staging_rows)}")
    logger.info(f"  Need review:     {check_count}")
    logger.info(f"{'='*50}")

    return output_path


def write_csv(path: Path, columns: list, rows: list):
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=columns, extrasaction="ignore")
        writer.writeheader()
        for row in rows:
            writer.writerow({col: row.get(col, "") for col in columns})


# ──────────────────────────────────────────────
# ENTRY POINT
# ──────────────────────────────────────────────

if __name__ == "__main__":
    import sys

    # Always run relative to the script's own folder
    os.chdir(Path(__file__).parent)

    # If arguments are passed (terminal usage), use them
    # Otherwise fall back to hardcoded defaults (VS Code Run button)
    if len(sys.argv) > 1:
        parser = argparse.ArgumentParser(description="EOI PDF Extractor")
        parser.add_argument(
            "input_dir",
            help="Folder containing EOI PDFs (e.g. input_pdfs)"
        )
        parser.add_argument(
            "--output",
            default="output/eoi_staging_output.csv",
            help="Path for the staging CSV output"
        )
        args = parser.parse_args()
        process_batch(args.input_dir, args.output)
    else:
        # Default paths — edit these if your folder names are different
        INPUT_DIR  = "input_pdfs"
        OUTPUT_CSV = "output/eoi_staging_output.csv"
        process_batch(INPUT_DIR, OUTPUT_CSV)