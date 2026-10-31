"""Static tables for the synthetic data generator: fictional insurers, providers, people, service catalogues,
diagnosis templates and the policy clause ids. Everything here is invented; no real person, hospital or
insurer is named.
"""
from __future__ import annotations

from typing import Dict, List, Optional, Tuple

# ---------------------------------------------------------------------------
# Products
# ---------------------------------------------------------------------------
PRODUCT_IN = "IN-HEALTH-RETAIL"
PRODUCT_AE = "AE-HEALTH-GROUP"

INSURER_IN = "Sahara Health Assurance"
INSURER_AE = "Gulf Shield Takaful"

REQUIRED_DOCUMENTS_IN: Dict[str, List[str]] = {
    "inpatient": ["claim_form", "itemized_final_hospital_bill", "discharge_summary", "diagnostic_reports",
                  "prescriptions", "kyc_document", "pre_auth_form"],
    "daycare": ["claim_form", "itemized_final_hospital_bill", "discharge_summary", "prescriptions", "kyc_document"],
    "outpatient": ["itemized_final_hospital_bill", "prescriptions"],
    "pharmacy": ["medicine_pharmacy_bills", "prescriptions"],
}
REQUIRED_DOCUMENTS_AE: Dict[str, List[str]] = {
    "inpatient": ["claim_form", "itemized_final_hospital_bill", "discharge_summary", "diagnostic_reports",
                  "prescriptions", "kyc_document", "pre_auth_form"],
    "daycare": ["claim_form", "itemized_final_hospital_bill", "discharge_summary", "prescriptions", "kyc_document"],
    "outpatient": ["itemized_final_hospital_bill", "prescriptions"],
    "pharmacy": ["medicine_pharmacy_bills", "prescriptions"],
}

# The non-payable lists. The generator's non-payable line descriptions start with these strings so a plain
# keyword match finds them; payable lines never contain them.
NON_PAYABLE_IN: List[str] = [
    "Surgical gloves", "Disposable syringe", "Cotton roll", "Thermometer", "Admission kit", "Toiletries",
    "Mineral water", "Diet charges for attendant", "Telephone charges", "Television charges",
    "Documentation charges", "Registration charges", "Visitor pass", "Nebuliser kit", "Hot water bag",
    "Slippers", "Mask (non-surgical)", "Tissue paper", "Sanitiser", "Bed pan", "Urine pot",
    "Belt / brace (non-implant)", "Crepe bandage", "Spirit / disinfectant", "Attendant charges",
]
NON_PAYABLE_AE: List[str] = [
    "Non-prescription items", "Cosmetics", "Vitamins without prescription", "Medical report fee",
    "Telephone charges", "Extra meals", "Companion bed", "Parking", "Toiletries", "Sick leave certificate fee",
    "Administrative fee", "Newspaper / magazines",
]

# Clause ids used by both the Policy records and data/policies/*.md (keep the two in step).
CLAUSES_IN = {
    "ROOM_RENT": "3.1", "PROPORTIONATE": "3.3", "ICU": "4.1", "COPAY": "5.1", "DEDUCTIBLE": "6.1",
    "CATARACT": "7.1", "MATERNITY": "7.2", "PHYSIO_SESSIONS": "7.3", "WAITING": "8.1", "PED": "9.1",
    "COSMETIC": "10.3", "DENTAL": "10.4", "OPD_CONSULT": "10.5", "NON_PAYABLE": "11.1", "NETWORK": "12.1",
    "EPISODE_DATES": "13.4", "BENEFIT_LIMIT": "2.2", "DUPLICATE": "13.6", "DOCUMENTS": "14.1",
}
CLAUSES_AE = {
    "BENEFIT_LIMIT": "2.2", "ROOM": "3.1", "ICU": "4.1", "COPAY_OP": "5.1", "COPAY_PH": "5.2", "COPAY_IP": "5.3",
    "DEDUCTIBLE": "6.1", "ORDER": "6.2", "MATERNITY": "7.1", "PHYSIO": "7.2", "WAITING": "8.1", "PED": "9.1",
    "DENTAL": "10.2", "OPTICAL": "10.3", "COSMETIC": "10.4", "NON_PAYABLE": "11.1", "NETWORK": "12.1",
    "EPISODE_DATES": "13.4", "DUPLICATE": "13.6", "DOCUMENTS": "14.1",
}

# ---------------------------------------------------------------------------
# Providers (8): P-001..P-006 normal, P-007 inflated pricing, P-008 related-party claimants.
# ---------------------------------------------------------------------------
PROVIDERS: List[Dict[str, object]] = [
    {"provider_id": "P-001", "provider_name": "Meridian Care Hospital", "market": "IN", "city": "Pune",
     "provider_type": "hospital", "in_network": True, "profile": "normal", "invoice_prefix": "MCH",
     "address": "14 Lakeview Road, Pune 411001", "phone": "+91 20 4455 0100", "licence_no": "MH-HOSP-20481"},
    {"provider_id": "P-002", "provider_name": "Lotus Valley Multispeciality Hospital", "market": "IN", "city": "Jaipur",
     "provider_type": "hospital", "in_network": True, "profile": "normal", "invoice_prefix": "LVH",
     "address": "Plot 7, Ridge Avenue, Jaipur 302001", "phone": "+91 141 320 7700", "licence_no": "RJ-HOSP-11207"},
    {"provider_id": "P-003", "provider_name": "Sunrise Medical Centre", "market": "IN", "city": "Lucknow",
     "provider_type": "hospital", "in_network": True, "profile": "normal", "invoice_prefix": "SMC",
     "address": "9 Orchard Lane, Lucknow 226001", "phone": "+91 522 410 2200", "licence_no": "UP-HOSP-33015"},
    {"provider_id": "P-004", "provider_name": "Pearl Coast Hospital", "market": "AE", "city": "Dubai",
     "provider_type": "hospital", "in_network": True, "profile": "normal", "invoice_prefix": "PCH",
     "address": "Marina Crescent, Dubai", "phone": "+971 4 330 1200", "licence_no": "FL-DXB-5021"},
    {"provider_id": "P-005", "provider_name": "Desert Rose Clinic", "market": "AE", "city": "Abu Dhabi",
     "provider_type": "clinic", "in_network": True, "profile": "normal", "invoice_prefix": "DRC",
     "address": "Corniche Gardens, Abu Dhabi", "phone": "+971 2 610 4400", "licence_no": "FL-AUH-2277"},
    {"provider_id": "P-006", "provider_name": "Falcon Bay Medical Centre", "market": "AE", "city": "Sharjah",
     "provider_type": "hospital", "in_network": False, "profile": "normal", "invoice_prefix": "FBM",
     "address": "Harbour Street 3, Sharjah", "phone": "+971 6 520 8800", "licence_no": "FL-SHJ-1903"},
    {"provider_id": "P-007", "provider_name": "Crestview Super Speciality Hospital", "market": "IN", "city": "Indore",
     "provider_type": "hospital", "in_network": True, "profile": "inflated", "invoice_prefix": "CSH",
     "address": "22 Summit Road, Indore 452001", "phone": "+91 731 255 9900", "licence_no": "MP-HOSP-40872"},
    {"provider_id": "P-008", "provider_name": "Riverbend Nursing Home", "market": "IN", "city": "Nagpur",
     "provider_type": "hospital", "in_network": True, "profile": "related-party", "invoice_prefix": "RNH",
     "address": "5 Canal Side, Nagpur 440001", "phone": "+91 712 266 3100", "licence_no": "MH-HOSP-27730"},
]
IN_NORMAL_PROVIDERS = ["P-001", "P-002", "P-003"]
AE_NETWORK_PROVIDERS = ["P-004", "P-005"]       # the restricted network of most AE policies
AE_ALL_PROVIDERS = ["P-004", "P-005", "P-006"]
PROVIDER_INFLATED = "P-007"
PROVIDER_RELATED_PARTY = "P-008"

DOCTORS_IN = ["Dr. A. Raghunathan", "Dr. Priyanka Sethi", "Dr. Vikrant Oak", "Dr. Nalini Kurup", "Dr. S. Bhandarkar",
              "Dr. Mohit Taneja", "Dr. Farah Siddique", "Dr. Kedar Phadnis"]
DOCTORS_AE = ["Dr. Rania Khalil", "Dr. Omar Haddad", "Dr. Lina Mansour", "Dr. Yusuf Darwish", "Dr. Hana Saleh"]

# ---------------------------------------------------------------------------
# People (synthetic name parts)
# ---------------------------------------------------------------------------
FIRST_IN_M = ["Aarav", "Rohan", "Vikram", "Kabir", "Arjun", "Rahul", "Dev", "Nikhil", "Aditya", "Sameer",
              "Ishaan", "Varun", "Manav", "Siddharth", "Tanish", "Harsh", "Yash", "Pranav", "Rishi", "Kunal"]
FIRST_IN_F = ["Priya", "Ananya", "Neha", "Meera", "Sneha", "Pooja", "Isha", "Tara", "Riya", "Kavya",
              "Nandini", "Shreya", "Divya", "Aisha", "Ritika", "Pallavi", "Mitali", "Sanya", "Vani", "Juhi"]
LAST_IN = ["Sharma", "Verma", "Iyer", "Nair", "Patel", "Reddy", "Menon", "Joshi", "Kulkarni", "Mishra", "Bose",
           "Chawla", "Desai", "Rao", "Saxena", "Pillai", "Gupta", "Malhotra", "Trivedi", "Bhat"]
FIRST_AE_M = ["Omar", "Khalid", "Yousef", "Hamad", "Saeed", "Tariq", "Faisal", "Rashid", "Adel", "Majid",
              "Nabil", "Ziad", "Bilal", "Imran", "Hassan"]
FIRST_AE_F = ["Fatima", "Layla", "Mariam", "Noor", "Hessa", "Amira", "Dana", "Salma", "Huda", "Reem",
              "Sara", "Aya", "Lina", "Rana", "Zainab"]
LAST_AE = ["Al Hammadi", "Al Marzouqi", "Al Shamsi", "Al Ketbi", "Al Ameri", "Al Nuaimi", "Haddad", "Khoury",
           "Nasser", "Rahman", "Siddiqui", "Qureshi", "Fernandes", "Mathew", "Pereira", "Darwish"]

STREETS_IN = ["MG Road", "Station Road", "Nehru Nagar", "Lakeview Colony", "Hill Top Lane", "Civil Lines",
              "Garden Estate", "Park Street", "Model Town", "Temple Road"]
CITIES_IN = ["Pune", "Jaipur", "Lucknow", "Indore", "Nagpur", "Surat", "Bhopal", "Kochi", "Mysuru", "Vadodara"]
STREETS_AE = ["Al Wasl Street", "Corniche Road", "Khalifa Street", "Marina Walk", "Al Reem Boulevard",
              "Palm Avenue", "Harbour View", "Oasis Lane"]
CITIES_AE = ["Dubai", "Abu Dhabi", "Sharjah", "Ajman", "Al Ain"]

# ---------------------------------------------------------------------------
# Service catalogue, India (internal codes). code -> (description, category, base price)
# ---------------------------------------------------------------------------
IN_SERVICES: Dict[str, Tuple[str, str, float]] = {
    # per-day items
    "RM-TWIN": ("Room charges - Twin sharing (per day)", "room", 2600),
    "RM-SGL": ("Room charges - Single AC (per day)", "room", 4200),
    "RM-DLX": ("Room charges - Deluxe (per day)", "room", 7000),
    "ICU001": ("ICU charges (per day)", "icu", 5500),
    "NUR001": ("Nursing charges (per day)", "services", 600),
    "VIS001": ("Doctor visit charges (per day)", "professional fees", 800),
    # theatre / procedure
    "OT001": ("Operation theatre charges", "services", 12000),
    "OT-DC": ("Day care theatre charges", "services", 6000),
    "LR001": ("Labour room charges", "services", 5000),
    "ANE001": ("Anaesthesia charges", "professional fees", 6000),
    "SUR-APP": ("Laparoscopic appendectomy - surgeon fees", "surgery", 28000),
    "SUR-CHOL": ("Laparoscopic cholecystectomy - surgeon fees", "surgery", 32000),
    "SUR-HERN": ("Inguinal hernia repair (mesh) - surgeon fees", "surgery", 26000),
    "SUR-ORIF": ("ORIF fracture fixation - surgeon fees", "surgery", 35000),
    "SUR-TKR": ("Total knee replacement - surgeon fees", "surgery", 60000),
    "SUR-LSCS": ("LSCS (caesarean section) - surgeon fees", "surgery", 24000),
    "SUR-NVD": ("Normal vaginal delivery - obstetrician fees", "surgery", 15000),
    "SUR-CAT": ("Phacoemulsification with foldable IOL - surgeon fees", "surgery", 14000),
    "SUR-DEB": ("Wound debridement - surgeon fees", "surgery", 12000),
    "SUR-COS": ("Scar revision (cosmetic)", "surgery", 18000),
    "DEN-RCT": ("Root canal treatment (dental)", "surgery", 6500),
    "DEN-EXT": ("Tooth extraction (dental)", "surgery", 2500),
    # implants and payable medical items
    "MED-IOL": ("Foldable intraocular lens (IOL) implant", "medical", 12000),
    "MED-IOL-PREM": ("Premium multifocal IOL implant", "medical", 25000),
    "MED-KNEE": ("Knee implant (cemented)", "medical", 85000),
    "MED-MESH": ("Hernia mesh 15x15 cm", "medical", 9000),
    "MED-PLATE": ("Locking plate and screws", "medical", 22000),
    "MED-CAN": ("IV cannula 20G", "medical", 90),
    "MED-SET": ("IV infusion set", "medical", 70),
    "MED-DRS": ("Dressing pack (sterile)", "medical", 180),
    "MED-CATH": ("Foley catheter 16F", "medical", 220),
    "MED-SUT": ("Suture material (polyglactin 2-0)", "medical", 450),
    "MED-DRAIN": ("Surgical drain kit", "medical", 650),
    # labs
    "LAB-CBC": ("Complete Blood Count", "lab", 450),
    "LAB-LFT": ("Liver Function Test", "lab", 800),
    "LAB-KFT": ("Kidney Function Test", "lab", 750),
    "LAB-RBS": ("Random Blood Sugar", "lab", 120),
    "LAB-URINE": ("Urinalysis - routine and microscopy", "lab", 200),
    "LAB-LIPID": ("Lipid Profile", "lab", 900),
    "LAB-TSH": ("Thyroid Profile (T3 T4 TSH)", "lab", 650),
    "LAB-CRP": ("C-Reactive Protein", "lab", 550),
    "LAB-ELEC": ("Serum Electrolytes", "lab", 500),
    "LAB-PT": ("PT / INR", "lab", 400),
    "LAB-BLDGRP": ("Blood Grouping and Rh typing", "lab", 250),
    "LAB-VIRAL": ("HIV / HBsAg / HCV screening", "lab", 1200),
    "LAB-DENGUE": ("Dengue NS1 antigen", "lab", 950),
    "LAB-WIDAL": ("Widal test", "lab", 350),
    # radiology
    "RAD-XRAY": ("X-Ray Chest PA", "radiology", 500),
    "RAD-XRAY-KNEE": ("X-Ray Knee AP/Lateral", "radiology", 600),
    "RAD-USG": ("Ultrasound Whole Abdomen", "radiology", 1500),
    "RAD-CT": ("CT Scan Abdomen (contrast)", "radiology", 6500),
    "RAD-MRI": ("MRI Brain", "radiology", 8500),
    "RAD-ECG": ("ECG 12-lead", "radiology", 300),
    "RAD-ECHO": ("2D Echocardiography", "radiology", 2500),
    # sessions
    "PHY001": ("Physiotherapy session", "services", 700),
    "DIA001": ("Haemodialysis session", "services", 3200),
    "CHE001": ("Chemotherapy session (day care)", "services", 18000),
    "CONS-OPD": ("OPD consultation", "professional fees", 600),
    # pharmacy
    "PH-001": ("Inj. Ceftriaxone 1 g", "pharma", 85),
    "PH-002": ("Tab. Paracetamol 650 mg", "pharma", 3),
    "PH-003": ("Inj. Pantoprazole 40 mg", "pharma", 55),
    "PH-004": ("IV Fluid NS 500 ml", "pharma", 45),
    "PH-005": ("Inj. Ondansetron 4 mg", "pharma", 20),
    "PH-006": ("Inj. Enoxaparin 40 mg", "pharma", 420),
    "PH-007": ("Tab. Atorvastatin 10 mg", "pharma", 8),
    "PH-008": ("Cap. Omeprazole 20 mg", "pharma", 6),
    "PH-009": ("Inj. Tramadol 50 mg", "pharma", 25),
    "PH-010": ("Tab. Amoxicillin-Clavulanate 625 mg", "pharma", 28),
    "PH-011": ("Syp. Lactulose 100 ml", "pharma", 110),
    "PH-012": ("Inj. Metoclopramide 10 mg", "pharma", 15),
    "PH-013": ("Tab. Cefixime 200 mg", "pharma", 18),
    "PH-014": ("Eye drops Moxifloxacin 5 ml", "pharma", 140),
    "PH-015": ("Tab. Diclofenac 50 mg", "pharma", 5),
    "PH-016": ("Tab. Levocetirizine 5 mg", "pharma", 4),
    "PH-017": ("Inj. Hydrocortisone 100 mg", "pharma", 40),
    "PH-018": ("Cap. Pregabalin 75 mg", "pharma", 12),
    "PH-019": ("Tab. Folic acid 5 mg", "pharma", 2),
    "PH-020": ("Inj. Paclitaxel 300 mg", "pharma", 9500),
    "PH-021": ("Inj. Erythropoietin 4000 IU", "pharma", 850),
    "PH-022": ("Tab. Doxycycline 100 mg", "pharma", 9),
    "PH-023": ("ORS sachets", "pharma", 20),
    "PH-024": ("Inj. Oxytocin 10 IU", "pharma", 30),
    "PH-025": ("Tab. Azithromycin 500 mg", "pharma", 22),
    # non-payable consumables (descriptions start with the NON_PAYABLE_IN entry)
    "CONS-GLV": ("Surgical gloves (pair)", "medical", 60),
    "CONS-SYR": ("Disposable syringe 5 ml", "medical", 12),
    "CONS-COT": ("Cotton roll 500 g", "medical", 150),
    "CONS-THERM": ("Thermometer (digital)", "medical", 250),
    "CONS-ADM": ("Admission kit", "medical", 850),
    "CONS-TOIL": ("Toiletries kit", "other", 350),
    "CONS-WATER": ("Mineral water (1 L bottle)", "other", 25),
    "CONS-DIET": ("Diet charges for attendant (per day)", "other", 250),
    "CONS-TEL": ("Telephone charges", "other", 120),
    "CONS-TV": ("Television charges (per day)", "other", 200),
    "CONS-DOC": ("Documentation charges", "services", 300),
    "CONS-REG": ("Registration charges", "services", 500),
    "CONS-VIS": ("Visitor pass", "other", 50),
    "CONS-NEB": ("Nebuliser kit", "medical", 180),
    "CONS-HWB": ("Hot water bag", "medical", 220),
    "CONS-SLIP": ("Slippers", "other", 90),
    "CONS-MASK": ("Mask (non-surgical)", "medical", 15),
    "CONS-TIS": ("Tissue paper", "other", 45),
    "CONS-SAN": ("Sanitiser 100 ml", "medical", 80),
    "CONS-BP": ("Bed pan", "medical", 320),
    "CONS-UP": ("Urine pot", "medical", 150),
    "CONS-BELT": ("Belt / brace (non-implant) - lumbar support", "medical", 1200),
    "CONS-CREPE": ("Crepe bandage 10 cm", "medical", 90),
    "CONS-SPIRIT": ("Spirit / disinfectant 500 ml", "medical", 60),
    "CONS-ATT": ("Attendant charges (per day)", "other", 300),
}
IN_NON_PAYABLE_CODES = [c for c in IN_SERVICES if c.startswith("CONS-") and c != "CONS-OPD"]
IN_ROOM_CLASSES = [("RM-TWIN", "Twin sharing"), ("RM-SGL", "Single AC"), ("RM-DLX", "Deluxe")]
IN_LABS_COMMON = ["LAB-CBC", "LAB-LFT", "LAB-KFT", "LAB-RBS", "LAB-URINE", "LAB-ELEC", "LAB-CRP", "LAB-PT",
                  "LAB-BLDGRP", "LAB-VIRAL"]
IN_PHARMA_COMMON = ["PH-001", "PH-002", "PH-003", "PH-004", "PH-005", "PH-008", "PH-009", "PH-010", "PH-012",
                    "PH-013", "PH-015", "PH-016", "PH-017", "PH-025"]
IN_MEDICAL_PAYABLE = ["MED-CAN", "MED-SET", "MED-DRS", "MED-CATH", "MED-SUT"]

# ---------------------------------------------------------------------------
# Service catalogue, UAE. code -> (description, category, base price AED, code_system)
# ---------------------------------------------------------------------------
AE_SERVICES: Dict[str, Tuple[str, str, float, str]] = {
    "99203": ("Office visit, new patient, low complexity", "professional fees", 300, "CPT"),
    "99213": ("Office visit, established patient, low complexity", "professional fees", 250, "CPT"),
    "99214": ("Office visit, established patient, moderate complexity", "professional fees", 350, "CPT"),
    "99223": ("Initial hospital care, high complexity", "professional fees", 900, "CPT"),
    "99232": ("Subsequent hospital care, moderate complexity (per day)", "professional fees", 450, "CPT"),
    "80053": ("Comprehensive metabolic panel", "lab", 220, "CPT"),
    "85025": ("Complete blood count (CBC) with differential", "lab", 95, "CPT"),
    "80061": ("Lipid panel", "lab", 150, "CPT"),
    "84443": ("Thyroid stimulating hormone (TSH)", "lab", 120, "CPT"),
    "81001": ("Urinalysis, automated with microscopy", "lab", 60, "CPT"),
    "87086": ("Urine culture, quantitative", "lab", 110, "CPT"),
    "83036": ("Haemoglobin A1c", "lab", 130, "CPT"),
    "86140": ("C-reactive protein", "lab", 90, "CPT"),
    "71046": ("Chest X-ray, 2 views", "radiology", 180, "CPT"),
    "73630": ("X-ray foot, 3 views", "radiology", 160, "CPT"),
    "70450": ("CT head without contrast", "radiology", 950, "CPT"),
    "72148": ("MRI lumbar spine without contrast", "radiology", 1800, "CPT"),
    "93000": ("ECG 12-lead with interpretation", "radiology", 120, "CPT"),
    "76700": ("Ultrasound abdomen, complete", "radiology", 450, "CPT"),
    "97110": ("Therapeutic exercises, physiotherapy (per session)", "services", 180, "CPT"),
    "90935": ("Haemodialysis, single evaluation", "services", 900, "CPT"),
    "96413": ("Chemotherapy IV infusion, first hour", "services", 1500, "CPT"),
    "47562": ("Laparoscopic cholecystectomy", "surgery", 9500, "CPT"),
    "44970": ("Laparoscopic appendectomy", "surgery", 8500, "CPT"),
    "66984": ("Cataract surgery with IOL insertion", "surgery", 6500, "CPT"),
    "29881": ("Knee arthroscopy with meniscectomy", "surgery", 7500, "CPT"),
    "49505": ("Inguinal hernia repair, age 5 years or older", "surgery", 7000, "CPT"),
    "00840": ("Anaesthesia, intraperitoneal procedures, lower abdomen", "professional fees", 1800, "CPT"),
    "01400": ("Anaesthesia, knee joint procedures", "professional fees", 1500, "CPT"),
    "ROOM-STD": ("Inpatient room, standard private (per day)", "room", 1100, "service"),
    "ICU-01": ("Intensive care unit (per day)", "icu", 3200, "service"),
    "NUR-01": ("Nursing care (per day)", "services", 250, "service"),
    "OT-01": ("Operating room charges", "services", 3500, "service"),
    "D7140": ("Extraction, erupted tooth (dental)", "surgery", 350, "CDT"),
    "D3310": ("Endodontic therapy, anterior tooth - root canal (dental)", "surgery", 1200, "CDT"),
    "D0120": ("Periodic oral evaluation (dental)", "professional fees", 150, "CDT"),
    "92015": ("Determination of refractive state (optical)", "professional fees", 150, "CPT"),
    "15823": ("Blepharoplasty, upper eyelid (cosmetic)", "surgery", 6000, "CPT"),
    # drugs
    "DRG-0101": ("Amoxicillin 500 mg capsules x21", "pharma", 45, "drug"),
    "DRG-0102": ("Paracetamol 500 mg tablets x20", "pharma", 12, "drug"),
    "DRG-0103": ("Omeprazole 20 mg capsules x14", "pharma", 38, "drug"),
    "DRG-0104": ("Metformin 500 mg tablets x60", "pharma", 30, "drug"),
    "DRG-0105": ("Cetirizine 10 mg tablets x10", "pharma", 15, "drug"),
    "DRG-0106": ("Salbutamol inhaler 100 mcg", "pharma", 28, "drug"),
    "DRG-0107": ("Atorvastatin 20 mg tablets x30", "pharma", 65, "drug"),
    "DRG-0108": ("Ibuprofen 400 mg tablets x20", "pharma", 18, "drug"),
    "DRG-0109": ("Azithromycin 500 mg tablets x3", "pharma", 42, "drug"),
    "DRG-0110": ("Sodium chloride 0.9% 500 ml IV", "pharma", 22, "drug"),
    "DRG-0111": ("Ceftriaxone 1 g injection", "pharma", 55, "drug"),
    "DRG-0112": ("Ondansetron 4 mg injection", "pharma", 18, "drug"),
    "DRG-0113": ("Enoxaparin 40 mg injection", "pharma", 95, "drug"),
    "DRG-0114": ("Vitamin D3 50,000 IU capsules x4 (prescribed)", "pharma", 48, "drug"),
    "DRG-0115": ("Losartan 50 mg tablets x30", "pharma", 52, "drug"),
    "DRG-0116": ("Pantoprazole 40 mg injection", "pharma", 40, "drug"),
    "DRG-0117": ("Tramadol 50 mg capsules x10", "pharma", 30, "drug"),
    "DRG-0118": ("Mupirocin 2% ointment 15 g", "pharma", 25, "drug"),
    "DRG-0119": ("Loratadine 10 mg tablets x10", "pharma", 14, "drug"),
    "DRG-0120": ("Diclofenac 50 mg tablets x20", "pharma", 16, "drug"),
    # non-payable (descriptions start with the NON_PAYABLE_AE entry)
    "NP-AE-01": ("Non-prescription items - cough lozenges", "other", 20, "service"),
    "NP-AE-02": ("Cosmetics - moisturising skin cream", "other", 85, "service"),
    "NP-AE-03": ("Vitamins without prescription - multivitamin tablets", "other", 60, "service"),
    "NP-AE-04": ("Medical report fee", "services", 150, "service"),
    "NP-AE-05": ("Telephone charges", "other", 40, "service"),
    "NP-AE-06": ("Extra meals", "other", 90, "service"),
    "NP-AE-07": ("Companion bed (per day)", "other", 200, "service"),
    "NP-AE-08": ("Parking", "other", 30, "service"),
    "NP-AE-09": ("Toiletries", "other", 45, "service"),
    "NP-AE-10": ("Sick leave certificate fee", "services", 50, "service"),
    "NP-AE-11": ("Administrative fee", "services", 100, "service"),
    "NP-AE-12": ("Newspaper / magazines", "other", 15, "service"),
}
AE_NON_PAYABLE_CODES = [c for c in AE_SERVICES if c.startswith("NP-AE-")]
AE_OP_LABS = ["80053", "85025", "80061", "84443", "81001", "87086", "86140"]
AE_OP_RADIOLOGY = ["71046", "73630", "93000", "76700"]
AE_OP_DRUGS = ["DRG-0101", "DRG-0102", "DRG-0103", "DRG-0105", "DRG-0106", "DRG-0108", "DRG-0109", "DRG-0118",
               "DRG-0119", "DRG-0120"]
AE_PHARMACY_DRUGS = ["DRG-0101", "DRG-0102", "DRG-0103", "DRG-0104", "DRG-0105", "DRG-0106", "DRG-0107",
                     "DRG-0108", "DRG-0109", "DRG-0115", "DRG-0117", "DRG-0119", "DRG-0120"]
AE_IP_DRUGS = ["DRG-0110", "DRG-0111", "DRG-0112", "DRG-0113", "DRG-0116", "DRG-0102", "DRG-0103", "DRG-0117"]
AE_CONSULT_CODES = ["99213", "99214", "99203"]

# ---------------------------------------------------------------------------
# Diagnosis templates. Fields: diagnosis text, ICD-10 code, procedure code (or None), implant code (or None),
# stay range (nights), ICU nights range.
# ---------------------------------------------------------------------------
IN_INPATIENT_TEMPLATES: List[Dict[str, object]] = [
    {"dx": "Acute appendicitis", "icd": "K35.80", "proc": "SUR-APP", "implant": None, "stay": (2, 3), "icu": (0, 0)},
    {"dx": "Symptomatic cholelithiasis", "icd": "K80.20", "proc": "SUR-CHOL", "implant": None, "stay": (2, 3), "icu": (0, 0)},
    {"dx": "Right inguinal hernia", "icd": "K40.90", "proc": "SUR-HERN", "implant": "MED-MESH", "stay": (2, 2), "icu": (0, 0)},
    {"dx": "Closed fracture shaft of femur", "icd": "S72.30", "proc": "SUR-ORIF", "implant": "MED-PLATE", "stay": (5, 7), "icu": (0, 1)},
    {"dx": "Community-acquired pneumonia", "icd": "J18.9", "proc": None, "implant": None, "stay": (4, 6), "icu": (0, 2)},
    {"dx": "Acute gastroenteritis with dehydration", "icd": "A09", "proc": None, "implant": None, "stay": (2, 3), "icu": (0, 0)},
    {"dx": "Dengue fever without warning signs", "icd": "A97.0", "proc": None, "implant": None, "stay": (4, 5), "icu": (0, 0)},
    {"dx": "Acute pyelonephritis", "icd": "N10", "proc": None, "implant": None, "stay": (3, 4), "icu": (0, 0)},
    {"dx": "Lower respiratory tract infection", "icd": "J22", "proc": None, "implant": None, "stay": (3, 4), "icu": (0, 1)},
    {"dx": "Enteric fever", "icd": "A01.0", "proc": None, "implant": None, "stay": (5, 6), "icu": (0, 0)},
    {"dx": "Term pregnancy, normal vaginal delivery", "icd": "O80", "proc": "SUR-NVD", "implant": None, "stay": (2, 3), "icu": (0, 0)},
]
IN_TEMPLATE_TKR = {"dx": "Primary osteoarthritis right knee", "icd": "M17.11", "proc": "SUR-TKR", "implant": "MED-KNEE",
                   "stay": (7, 8), "icu": (0, 0)}
IN_TEMPLATE_LSCS = {"dx": "Term pregnancy, delivered by LSCS (caesarean section)", "icd": "O82", "proc": "SUR-LSCS",
                    "implant": None, "stay": (3, 4), "icu": (0, 0)}
IN_TEMPLATE_PED = {"dx": "Type 2 diabetes mellitus with diabetic foot ulcer - wound debridement", "icd": "E11.621",
                   "proc": "SUR-DEB", "implant": None, "stay": (4, 4), "icu": (0, 0)}
IN_TEMPLATE_CATARACT = {"dx": "Senile cataract, right eye", "icd": "H25.11", "proc": "SUR-CAT", "implant": "MED-IOL"}
IN_TEMPLATE_CHEMO = {"dx": "Carcinoma breast - chemotherapy cycle", "icd": "C50.9"}
IN_TEMPLATE_DIALYSIS = {"dx": "Chronic kidney disease stage 5 - maintenance haemodialysis", "icd": "N18.6"}
IN_TEMPLATE_PHYSIO = {"dx": "Post-operative rehabilitation, knee", "icd": "Z47.89"}

AE_OP_TEMPLATES: List[Tuple[str, str]] = [
    ("Acute upper respiratory infection", "J06.9"), ("Acute bronchitis", "J20.9"), ("Low back pain", "M54.5"),
    ("Urinary tract infection", "N39.0"), ("Gastro-oesophageal reflux disease", "K21.9"),
    ("Allergic rhinitis", "J30.9"), ("Ankle sprain", "S93.40"), ("Tension-type headache", "G44.2"),
    ("Hyperlipidaemia", "E78.5"), ("Acute tonsillitis", "J03.90"), ("Contact dermatitis", "L25.9"),
]
AE_IP_TEMPLATES: List[Dict[str, object]] = [
    {"dx": "Acute appendicitis", "icd": "K35.80", "proc": "44970", "anaes": "00840", "stay": (2, 3)},
    {"dx": "Cholelithiasis with cholecystitis", "icd": "K80.00", "proc": "47562", "anaes": "00840", "stay": (2, 3)},
    {"dx": "Community-acquired pneumonia", "icd": "J18.9", "proc": None, "anaes": None, "stay": (3, 5)},
    {"dx": "Medial meniscus tear, right knee", "icd": "S83.241", "proc": "29881", "anaes": "01400", "stay": (1, 2)},
    {"dx": "Unilateral inguinal hernia", "icd": "K40.90", "proc": "49505", "anaes": "00840", "stay": (1, 2)},
    {"dx": "Acute gastroenteritis with dehydration", "icd": "A09", "proc": None, "anaes": None, "stay": (2, 3)},
]

ROOM_CATEGORY_AE = "Standard private"


def in_service(code: str) -> Tuple[str, str, float]:
    return IN_SERVICES[code]


def ae_service(code: str) -> Tuple[str, str, float, str]:
    return AE_SERVICES[code]


def provider_by_id(provider_id: str) -> Dict[str, object]:
    for p in PROVIDERS:
        if p["provider_id"] == provider_id:
            return p
    raise KeyError(provider_id)


def non_payable_name_for(code: str, market: str) -> Optional[str]:
    """The non-payable list entry a consumable code maps to, or None when the item is payable."""
    desc = IN_SERVICES[code][0] if market == "IN" else AE_SERVICES[code][0]
    for item in (NON_PAYABLE_IN if market == "IN" else NON_PAYABLE_AE):
        if desc.lower().startswith(item.lower()):
            return item
    return None
