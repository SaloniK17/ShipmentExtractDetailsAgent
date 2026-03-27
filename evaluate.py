import json
from typing import Any, Dict, List, Optional

from utils import load_json, normalize_float, normalize_string


GROUND_TRUTH_FILE = "ground_truth.json"
PREDICTIONS_FILE = "output.json"

EVAL_FIELDS = [
    "product_line",
    "origin_port_code",
    "origin_port_name",
    "destination_port_code",
    "destination_port_name",
    "incoterm",
    "cargo_weight_kg",
    "cargo_cbm",
    "is_dangerous",
]

def values_equal(field: str, pred: Any, truth: Any) -> bool:
    if field in {"cargo_weight_kg", "cargo_cbm"}:
        return normalize_float(pred) == normalize_float(truth)

    if isinstance(truth, bool) or isinstance(pred, bool):
        return pred == truth

    return normalize_string(pred) == normalize_string(truth)


def main():
    ground_truth: List[Dict[str, Any]] = load_json(GROUND_TRUTH_FILE)
    predictions: List[Dict[str, Any]] = load_json(PREDICTIONS_FILE)

    pred_map = {item["id"]: item for item in predictions}
    gt_map = {item["id"]: item for item in ground_truth}

    field_correct = {field: 0 for field in EVAL_FIELDS}
    field_total = {field: 0 for field in EVAL_FIELDS}

    total_correct = 0
    total_fields = 0
    mismatches = []

    for email_id, truth in gt_map.items():
        pred = pred_map.get(email_id, {})

        for field in EVAL_FIELDS:
            field_total[field] += 1
            total_fields += 1

            if values_equal(field, pred.get(field), truth.get(field)):
                field_correct[field] += 1
                total_correct += 1
            else:
                mismatches.append({
                    "id": email_id,
                    "field": field,
                    "predicted": pred.get(field),
                    "expected": truth.get(field),
                })

    print("\n=== Accuracy Report ===\n")
    for field in EVAL_FIELDS:
        acc = (field_correct[field] / field_total[field]) * 100 if field_total[field] else 0
        print(f"{field:22s}: {field_correct[field]:>2}/{field_total[field]:<2} ({acc:.2f}%)")

    overall = (total_correct / total_fields) * 100 if total_fields else 0
    print(f"\nOverall Accuracy       : {total_correct}/{total_fields} ({overall:.2f}%)")

    print("\n=== Sample Mismatches (first 20) ===\n")
    for row in mismatches[:20]:
        print(
            f"{row['id']} | {row['field']} | "
            f"pred={row['predicted']} | exp={row['expected']}"
        )


if __name__ == "__main__":
    main()