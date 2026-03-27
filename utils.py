import json
import re
from collections import defaultdict
from typing import Any, Dict, List, Optional, Tuple

from rapidfuzz import fuzz, process


VALID_INCOTERMS = {
    "FOB", "CIF", "CFR", "EXW", "DDP", "DAP", "FCA", "CPT", "CIP", "DPU"
}


# =========================================================
# TEXT NORMALIZATION
# =========================================================

def normalize_text(text: Optional[str]) -> str:
    """
    Normalize text for matching:
    - uppercase
    - normalize separators
    - collapse spaces
    """
    if not text:
        return ""
    text = text.upper().strip()
    text = text.replace("→", " TO ")
    text = text.replace("-", " ")
    text = re.sub(r"[/,;:()\[\]]", " ", text)
    text = re.sub(r"\s+", " ", text)
    return text.strip()


def is_null_like(text: Optional[str]) -> bool:
    """
    Assignment rule:
    missing values -> null
    """
    if text is None:
        return True
    norm = normalize_text(text)
    return norm in {
        "", "N/A", "NA", "NONE", "NULL", "TBD", "TO BE CONFIRMED", "UNKNOWN"
    }


# =========================================================
# PORT MAPPING / CANONICALIZATION
# =========================================================

def build_port_mappings(
    port_reference: List[Dict[str, str]]
) -> Tuple[Dict[str, List[str]], Dict[str, List[str]]]:
    """
    Returns:
      alias_to_codes: alias -> list of candidate codes
      code_to_names: code -> list of all known names

    Why alias_to_codes is List[str] instead of str:
    - same alias can appear for multiple codes
    - we resolve ambiguity later using raw text context
    """
    alias_to_codes: Dict[str, List[str]] = defaultdict(list)
    code_to_names: Dict[str, List[str]] = defaultdict(list)

    manual_aliases = {
        # Hong Kong / China
        "HK": "HKHKG",
        "HKG": "HKHKG",
        "HONG KONG": "HKHKG",
        "SHA": "CNSHA",
        "SHANGHAI": "CNSHA",
        "QINGDAO": "CNQIN",
        "SHENZHEN": "CNSZX",
        "GUANGZHOU": "CNGZG",
        "NANSHA": "CNNSA",
        "TIANJIN": "CNTXG",
        "XINGANG": "CNTXG",
        "XINGANG TIANJIN": "CNTXG",
        "TIANJIN XINGANG": "CNTXG",

        # India
        "MAA": "INMAA",
        "CHENNAI": "INMAA",
        "CHENNAI ICD": "INMAA",
        "ICD MAA": "INMAA",

        "BLR": "INBLR",
        "BANGALORE": "INBLR",
        "BANGALORE ICD": "INBLR",
        "BLR ICD": "INBLR",
        "ICD BANGALORE": "INBLR",

        "HYD": "INHYD",
        "HYDERABAD": "INHYD",
        "HYDERABAD ICD": "INHYD",
        "HYD ICD": "INHYD",

        "WHITEFIELD": "INWFD",
        "ICD WHITEFIELD": "INWFD",

        "NSA": "INNSA",
        "NHAVA SHEVA": "INNSA",
        "JNPT": "INNSA",
        "MUMBAI": "INNSA",
        "BOM": "INNSA",

        "MUNDRA": "INMUN",
        "MUNDRA ICD": "INMUN",

        # Middle East
        "JED": "SAJED",
        "JEDDAH": "SAJED",
        "DAMMAM": "SADMM",
        "DMM": "SADMM",
        "RUH": "SARUH",
        "RIYADH": "SARUH",

        "JBL": "AEJEA",
        "JEBEL ALI": "AEJEA",

        # SEA / APAC
        "SIN": "SGSIN",
        "SINGAPORE": "SGSIN",
        "SUB": "IDSUB",
        "SURABAYA": "IDSUB",
        "YOK": "JPYOK",
        "YOKOHAMA": "JPYOK",
        "KEL": "TWKEL",
        "KEELUNG": "TWKEL",
        "MNL": "PHMNL",
        "MANILA": "PHMNL",
        "HCM": "VNSGN",
        "HO CHI MINH": "VNSGN",
        "SAIGON": "VNSGN",
        "OSAKA": "JPOSA",

        # Europe / Africa / US
        "CPT": "ZACPT",
        "CAPE TOWN": "ZACPT",
        "HOU": "USHOU",
        "HOUSTON": "USHOU",
        "PUS": "KRPUS",
        "BUSAN": "KRPUS",
        "LAX": "USLAX",
        "LOS ANGELES": "USLAX",
        "LGB": "USLAX",
        "LONG BEACH": "USLAX",
        "HAMBURG": "DEHAM",
        "PORT KLANG": "MYPKG",
        "COLOMBO": "LKCMB",
        "LAEM CHABANG": "THLCH",
        "BANGKOK": "THBKK",
        "BANGKOK ICD": "THBKK",
        "IZMIR": "TRIZM",
        "AMBARLI": "TRAMR",
        "GENOA": "ITGOA",
        "DHAKA": "BDDAC",
    }

    def add_alias(alias: str, code: str):
        alias_norm = normalize_text(alias)
        code_norm = code.strip().upper()

        if not alias_norm:
            return

        if code_norm not in alias_to_codes[alias_norm]:
            alias_to_codes[alias_norm].append(code_norm)

    # -----------------------------------------------------
    # Build from reference file
    # -----------------------------------------------------
    for item in port_reference:
        code = item["code"].strip().upper()
        name = item["name"].strip()

        if name not in code_to_names[code]:
            code_to_names[code].append(name)

        # Full official name
        add_alias(name, code)

        # Full code
        add_alias(code, code)

        # Short code (e.g. INMAA -> MAA)
        if re.fullmatch(r"[A-Z]{5}", code):
            add_alias(code[2:], code)

        # Light-clean simplified variant
        simplified = normalize_text(name)
        simplified = re.sub(r"\b(PORT|SEAPORT|SEA PORT|TERMINAL)\b", " ", simplified)
        simplified = re.sub(r"\s+", " ", simplified).strip()
        if simplified:
            add_alias(simplified, code)

    # Manual aliases
    for alias, code in manual_aliases.items():
        add_alias(alias, code)

    return dict(alias_to_codes), dict(code_to_names)


def resolve_port_code(
    raw_text: Optional[str],
    alias_to_codes: Dict[str, List[str]],
    code_to_names: Dict[str, List[str]]
) -> Optional[str]:
    """
    Resolve raw location text to best single UN/LOCODE.

    Strategy:
    1. Exact alias match
    2. Embedded full code / short code
    3. Substring alias candidates
    4. Fuzzy alias fallback
    5. Rank candidate codes using closeness to known names
    """
    if not raw_text or is_null_like(raw_text):
        return None

    return _resolve_single_port_code(raw_text, alias_to_codes, code_to_names)


def _resolve_single_port_code(
    raw_text: Optional[str],
    alias_to_codes: Dict[str, List[str]],
    code_to_names: Dict[str, List[str]]
) -> Optional[str]:
    if not raw_text or is_null_like(raw_text):
        return None

    norm = normalize_text(raw_text)
    candidate_codes: List[str] = []

    # 1) Exact alias match
    if norm in alias_to_codes:
        candidate_codes.extend(alias_to_codes[norm])

    # 2) Full code match (e.g. INMAA)
    full_codes = re.findall(r"\b[A-Z]{5}\b", norm)
    for token in full_codes:
        if token in code_to_names:
            candidate_codes.append(token)

    # 3) Short code match (e.g. MAA, BLR, HKG)
    short_codes = re.findall(r"\b[A-Z]{3}\b", norm)
    for token in short_codes:
        if token in alias_to_codes:
            candidate_codes.extend(alias_to_codes[token])

    # 4) Substring alias match
    substring_hits = []
    for alias, codes in alias_to_codes.items():
        if alias and alias in norm:
            substring_hits.append((len(alias), alias, codes))

    substring_hits.sort(reverse=True, key=lambda x: x[0])
    for _, _, codes in substring_hits:
        candidate_codes.extend(codes)

    # 5) Fuzzy alias fallback
    if not candidate_codes:
        best = process.extractOne(norm, list(alias_to_codes.keys()), scorer=fuzz.ratio)
        if best and best[1] >= 88:
            candidate_codes.extend(alias_to_codes[best[0]])

    # Deduplicate
    candidate_codes = list(dict.fromkeys(candidate_codes))

    if not candidate_codes:
        return None

    if len(candidate_codes) == 1:
        return candidate_codes[0]

    # Rank candidate codes using known names
    scored = []
    for code in candidate_codes:
        names = code_to_names.get(code, [])
        best_score = 0

        for name in names:
            name_norm = normalize_text(name)
            score = fuzz.ratio(norm, name_norm)

            if norm == name_norm:
                score += 30
            elif norm in name_norm or name_norm in norm:
                score += 15

            # Penalize noisy slash-combined labels
            if "/" in name:
                score -= 10

            best_score = max(best_score, score)

        scored.append((best_score, code))

    scored.sort(reverse=True, key=lambda x: x[0])
    return scored[0][1]


def choose_best_name_for_code(
    code: Optional[str],
    raw_text: Optional[str],
    code_to_names: Dict[str, List[str]]
) -> Optional[str]:
    """
    Choose best final display name for a matched code using raw extracted text.

    Handles:
    - exact match
    - containment
    - fuzzy match
    """
    if not code:
        return None

    names = code_to_names.get(code, [])
    if not names:
        return None

    if not raw_text:
        return fallback_best_name(names)

    raw_norm = normalize_text(raw_text)

    # 1) Exact normalized match
    for name in names:
        if normalize_text(name) == raw_norm:
            return name

    # 2) Containment match
    containment_matches = []
    for name in names:
        name_norm = normalize_text(name)
        if raw_norm in name_norm or name_norm in raw_norm:
            containment_matches.append(name)

    if containment_matches:
        return rank_names(containment_matches, raw_norm)[0]

    # 3) Fuzzy match within same code
    scored = []
    for name in names:
        score = fuzz.ratio(raw_norm, normalize_text(name))
        scored.append((score, name))

    scored.sort(reverse=True, key=lambda x: x[0])

    if scored and scored[0][0] >= 75:
        return scored[0][1]

    return fallback_best_name(names)


def fallback_best_name(names: List[str]) -> Optional[str]:
    """
    Choose cleanest default display name when raw text is weak.

    Preference:
    - avoid slash-combined names
    - prefer non-ICD if possible
    - shorter clean names
    """
    if not names:
        return None

    unique = list(dict.fromkeys(n.strip() for n in names if n and n.strip()))
    if not unique:
        return None

    no_slash = [n for n in unique if "/" not in n]
    if no_slash:
        unique = no_slash

    non_icd = [n for n in unique if "ICD" not in n.upper()]
    if non_icd:
        unique = non_icd

    return min(unique, key=len)


def rank_names(names: List[str], raw_norm: str) -> List[str]:
    """
    Rank candidate names for one code using closeness + cleanliness.
    """
    scored = []

    for name in names:
        name_norm = normalize_text(name)
        score = fuzz.ratio(raw_norm, name_norm)

        if "/" in name:
            score -= 15

        if "ICD" in raw_norm and "ICD" in name_norm:
            score += 5

        scored.append((score, name))

    scored.sort(reverse=True, key=lambda x: x[0])
    return [name for _, name in scored]


# =========================================================
# BUSINESS RULES
# =========================================================

def is_india_code(code: Optional[str]) -> bool:
    return bool(code and code.upper().startswith("IN"))


def derive_product_line(origin_code: Optional[str], destination_code: Optional[str]) -> Optional[str]:
    """
    Rule:
      Destination India -> pl_sea_import_lcl
      Else if Origin India -> pl_sea_export_lcl
      Else null
    """
    if is_india_code(destination_code):
        return "pl_sea_import_lcl"
    if is_india_code(origin_code):
        return "pl_sea_export_lcl"
    return None


def normalize_incoterm(value: Optional[str], full_text: str = "") -> str:
    """
    Rules:
      - valid incoterms only
      - uppercase normalize
      - ambiguous / multiple terms -> FOB
      - missing -> FOB
    """
    candidates = []

    for source in [value]:
        if not source:
            continue
        norm = normalize_text(source)
        found = re.findall(r"\b(FOB|CIF|CFR|EXW|DDP|DAP|FCA|CPT|CIP|DPU)\b", norm)
        candidates.extend(found)

    unique = list(dict.fromkeys(candidates))

    if len(unique) == 1 and unique[0] in VALID_INCOTERMS:
        return unique[0]

    return "FOB"


def detect_dangerous(text: str) -> bool:
    """
    Dangerous goods detection with negation precedence.
    """
    norm = normalize_text(text)

    negative_patterns = [
        r"\bNON DG\b",
        r"\bNON HAZARDOUS\b",
        r"\bNONHAZARDOUS\b",
        r"\bNOT DANGEROUS\b",
        r"\bNON DANGEROUS\b",
        r"\bNONDG\b",
    ]
    for pat in negative_patterns:
        if re.search(pat, norm):
            return False

    positive_patterns = [
        r"\bDG\b",
        r"\bDANGEROUS\b",
        r"\bHAZARDOUS\b",
        r"\bIMO\b",
        r"\bIMDG\b",
        r"\bUN\s*\d{3,4}\b",
        r"\bCLASS\s*\d+\b",
    ]
    for pat in positive_patterns:
        if re.search(pat, norm):
            return True

    return False


# =========================================================
# NUMERIC PARSING
# =========================================================

# def parse_weight_kg(raw: Optional[str], full_text: str = "") -> Optional[float]:
#     """
#     Rules:
#       - kg as-is
#       - lbs -> kg
#       - tonnes/MT -> kg
#       - null-like -> None
#       - explicit zero -> 0.0
#       - positive numbers only otherwise
#     """
#     text = raw or full_text
#     if not text or is_null_like(text):
#         return None

#     norm = text.replace(",", "")
#     upper = norm.upper()

#     if re.search(r"\b(TBD|N/A|TO BE CONFIRMED)\b", upper):
#         return None

#     zero_match = re.search(r"\b0(?:\.0+)?\s*(KG|KGS|KILO|KILOS|LB|LBS|TONNE|TONNES|TON|TONS|MT)\b", upper)
#     if zero_match:
#         return 0.0

#     patterns = [
#         (r"(\d+(?:\.\d+)?)\s*(KG|KGS|KILO|KILOS)\b", "kg"),
#         (r"(\d+(?:\.\d+)?)\s*(LB|LBS)\b", "lb"),
#         (r"(\d+(?:\.\d+)?)\s*(TONNE|TONNES|TON|TONS|MT)\b", "ton"),
#     ]

#     for pattern, unit in patterns:
#         m = re.search(pattern, upper)
#         if m:
#             value = float(m.group(1))

#             if value < 0:
#                 return None

#             if unit == "kg":
#                 return round(value, 2)
#             elif unit == "lb":
#                 return round(value * 0.453592, 2)
#             elif unit == "ton":
#                 return round(value * 1000, 2)

#     return None
def parse_weight_kg(raw: Optional[str], full_text: str = "") -> Optional[float]:
    """
    Rules:
      - kg as-is
      - lbs -> kg
      - tonnes/MT -> kg
      - null-like -> None
      - explicit zero -> 0.0
      - positive numbers only otherwise
    """
    text = raw or full_text
    if not text or is_null_like(text):
        return None

    norm = text.replace(",", "")
    upper = norm.upper()

    if re.search(r"\b(TBD|N/A|TO BE CONFIRMED)\b", upper):
        return None

    zero_match = re.search(r"(?<![\d.])0(?:\.0+)?\s*(KG|KGS|KILO|KILOS|LB|LBS|TONNE|TONNES|TON|TONS|MT)\b", upper)
    if zero_match:
        return 0.0

    patterns = [
        (r"(\d+(?:\.\d+)?)\s*(KG|KGS|KILO|KILOS)\b", "kg"),
        (r"(\d+(?:\.\d+)?)\s*(LB|LBS)\b", "lb"),
        (r"(\d+(?:\.\d+)?)\s*(TONNE|TONNES|TON|TONS|MT)\b", "ton"),
    ]

    for pattern, unit in patterns:
        m = re.search(pattern, upper)
        if m:
            value = float(m.group(1))

            if value < 0:
                return None

            if unit == "kg":
                return round(value, 2)
            elif unit == "lb":
                return round(value * 0.453592, 2)
            elif unit == "ton":
                return round(value * 1000, 2)

    return None

def looks_like_dimensions(text: str) -> bool:
    """
    Detect LxWxH patterns to avoid calculating CBM from dimensions.
    """
    upper = text.upper().replace(" ", "")
    patterns = [
        r"\d+(\.\d+)?X\d+(\.\d+)?X\d+(\.\d+)?",
        r"\d+(\.\d+)?\*\d+(\.\d+)?\*\d+(\.\d+)?",
    ]
    return any(re.search(p, upper) for p in patterns)


# def parse_cbm(raw: Optional[str], full_text: str = "") -> Optional[float]:
#     """
#     Rules:
#       - CBM/CMB/RT accepted
#       - dimensions only -> null (do not calculate)
#       - null-like -> None
#       - explicit zero -> 0.0
#       - positive numbers only otherwise
#     """
#     text = raw or full_text
#     if not text or is_null_like(text):
#         return None

#     if looks_like_dimensions(text):
#         return None

#     norm = text.replace(",", "")
#     upper = norm.upper()

#     if re.search(r"\b(TBD|N/A|TO BE CONFIRMED)\b", upper):
#         return None

#     zero_match = re.search(r"\b0(?:\.0+)?\s*(CBM|CMB|RT)\b", upper)
#     if zero_match:
#         return 0.0

#     m = re.search(r"(\d+(?:\.\d+)?)\s*(CBM|CMB|RT)\b", upper)
#     if m:
#         value = float(m.group(1))
#         if value < 0:
#             return None
#         return round(value, 2)

#     return None
def parse_cbm(raw: Optional[str], full_text: str = "") -> Optional[float]:
    """
    Rules:
      - CBM/CMB/RT accepted
      - dimensions only -> null (do not calculate)
      - null-like -> None
      - explicit zero -> 0.0
      - positive numbers only otherwise
    """
    text = raw or full_text
    if not text or is_null_like(text):
        return None

    if looks_like_dimensions(text):
        return None

    norm = text.replace(",", "")
    upper = norm.upper()

    if re.search(r"\b(TBD|N/A|TO BE CONFIRMED)\b", upper):
        return None

    # Safer explicit zero detection
    zero_match = re.search(r"(?<![\d.])0(?:\.0+)?\s*(CBM|CMB|RT)\b", upper)
    if zero_match:
        return 0.0

    m = re.search(r"(\d+(?:\.\d+)?)\s*(CBM|CMB|RT)\b", upper)
    if m:
        value = float(m.group(1))
        if value < 0:
            return None
        return round(value, 2)

    return None

# =========================================================
# EMAIL HELPERS
# =========================================================

def body_over_subject(subject: str, body: str) -> str:
    """
    Business rule:
      body takes precedence over subject
    We still keep subject appended for fallback detection.
    """
    return f"{body}\n{subject}"


def null_result(email_id: str) -> Dict[str, Any]:
    return {
        "id": email_id,
        "product_line": None,
        "origin_port_code": None,
        "origin_port_name": None,
        "destination_port_code": None,
        "destination_port_name": None,
        "incoterm": None,
        "cargo_weight_kg": None,
        "cargo_cbm": None,
        "is_dangerous": False,
    }


def load_json(path: str):
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)
    
def normalize_string(value: Optional[str]) -> Optional[str]:
    if value is None:
        return None
    return str(value).strip().lower()


def normalize_float(value: Any) -> Optional[float]:
    if value is None:
        return None
    try:
        return round(float(value), 2)
    except Exception:
        return None