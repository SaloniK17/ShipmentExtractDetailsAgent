import json
import logging
import os
from typing import List, Dict, Any

from dotenv import load_dotenv
from pydantic import ValidationError
from tenacity import (
    retry,
    stop_after_attempt,
    wait_exponential,
    retry_if_exception_type,
    before_sleep_log,
)

from langchain_core.prompts import ChatPromptTemplate
from langchain_groq import ChatGroq

from schemas import RawExtraction, ShipmentExtraction
from prompts import ACTIVE_PROMPT
from utils import (
    build_port_mappings,
    resolve_port_code,
    choose_best_name_for_code,
    normalize_incoterm,
    detect_dangerous,
    parse_weight_kg,
    parse_cbm,
    derive_product_line,
    null_result,
    body_over_subject,
)

INPUT_EMAILS_FILE = "emails_input.json"
PORT_CODES_FILE = "port_codes_reference.json"
OUTPUT_FILE = "output.json"
MODEL_NAME = "llama-3.1-8b-instant"

load_dotenv()

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


def load_json(path: str):
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def build_chain():
    llm = ChatGroq(
        model=MODEL_NAME,
        temperature=0,
        groq_api_key=os.getenv("GROQ_API_KEY"),
    )

    structured_llm = llm.with_structured_output(RawExtraction)

    prompt = ChatPromptTemplate([
        ("system", ACTIVE_PROMPT)
    ])

    return prompt | structured_llm


@retry(
    stop=stop_after_attempt(3),
    wait=wait_exponential(multiplier=2, min=2, max=10),
    retry=retry_if_exception_type((ValidationError, ValueError, KeyError, Exception)),
    before_sleep=before_sleep_log(logger, logging.WARNING),
    reraise=True,
)
def call_llm(chain, subject: str, body: str) -> RawExtraction:
    result = chain.invoke({
        "subject": subject,
        "body": body,
    })

    if isinstance(result, RawExtraction):
        return result

    if isinstance(result, dict):
        return RawExtraction(**result)

    raise ValueError(f"Unexpected LLM output type: {type(result)}")


def process_email(
    chain,
    email: Dict[str, Any],
    alias_to_codes: Dict[str, List[str]],
    code_to_names: Dict[str, List[str]],
) -> Dict[str, Any]:
    email_id = email["id"]
    subject = email.get("subject", "") or ""
    body = email.get("body", "") or ""

    # Business rule: body takes precedence over subject
    full_text = body_over_subject(subject, body)

    try:
        raw = call_llm(chain, subject, body)

        print("Raw Data extract by llm:", raw)
        print("*" * 100)

        # Resolve ports using improved deterministic logic
        origin_code = resolve_port_code(raw.origin_text, alias_to_codes, code_to_names)
        destination_code = resolve_port_code(raw.destination_text, alias_to_codes, code_to_names)

        origin_name = choose_best_name_for_code(origin_code, raw.origin_text, code_to_names)
        destination_name = choose_best_name_for_code(destination_code, raw.destination_text, code_to_names)

        # Normalize business fields
        incoterm = normalize_incoterm(raw.incoterm, full_text)
        cargo_weight_kg = parse_weight_kg(raw.cargo_weight_raw, full_text)
        cargo_cbm = parse_cbm(raw.cargo_cbm_raw, full_text)

        # Deterministic business rule wins
        is_dangerous = detect_dangerous(full_text)

        product_line = derive_product_line(origin_code, destination_code)

        result = ShipmentExtraction(
            id=email_id,
            product_line=product_line,
            origin_port_code=origin_code,
            origin_port_name=origin_name,
            destination_port_code=destination_code,
            destination_port_name=destination_name,
            incoterm=incoterm,
            cargo_weight_kg=cargo_weight_kg,
            cargo_cbm=cargo_cbm,
            is_dangerous=is_dangerous,
        )

        return result.model_dump()

    except (ValidationError, Exception) as e:
        logger.warning(f"Failed processing {email_id}: {e}")
        return null_result(email_id)


def main():
    if not os.getenv("GROQ_API_KEY"):
        raise ValueError("Missing GROQ_API_KEY in environment variables.")

    emails: List[Dict[str, Any]] = load_json(INPUT_EMAILS_FILE)
    port_reference: List[Dict[str, str]] = load_json(PORT_CODES_FILE)

    alias_to_codes, code_to_names = build_port_mappings(port_reference)
    chain = build_chain()

    results = []
    for idx, email in enumerate(emails, start=1):
        logger.info(f"Processing {idx}/{len(emails)} - {email['id']}")
        result = process_email(chain, email, alias_to_codes, code_to_names)
        results.append(result)

    with open(OUTPUT_FILE, "w", encoding="utf-8") as f:
        json.dump(results, f, indent=2, ensure_ascii=False)

    logger.info(f"Done. Saved results to {OUTPUT_FILE}")


if __name__ == "__main__":
    main()