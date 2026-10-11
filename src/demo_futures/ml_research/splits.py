"""Timestamp partitions, conservative interval purge and a fixed four-hour buffer."""
from collections import Counter
from .config import START, DEV_END, VALIDATION_END, DATA_END, BUFFER, FOLDS


def nonoverlapping(rows):
    selected, eligible_at = [], -1
    for row in sorted(rows, key=lambda r: (r.decision_time, r.symbol)):
        if row.interval_start >= eligible_at:
            selected.append(row.row_id)
            eligible_at = row.interval_end
    return selected


def sufficiency(rows, stage):
    if stage not in ("train", "development_evaluation"):
        raise PermissionError("Selection-validation/final outcomes are locked")
    rows = tuple(rows)
    if (len({r.row_id for r in rows}) != len(rows)
            or any(not START <= r.decision_time < DEV_END for r in rows)):
        raise PermissionError("Sample counts require unique development rows only")
    counts = Counter(row.y for row in rows)
    if any(row.status != "VALID" for row in rows):
        raise ValueError("Sample gates accept valid labels only")
    minimum_rows, minimum_class, minimum_independent = (
        (200, 40, 0) if stage == "train" else (100, 20, 30))
    independent = nonoverlapping(rows)
    checks = {"rows": len(rows) >= minimum_rows, "class_0": counts[0] >= minimum_class,
              "class_1": counts[1] >= minimum_class,
              "nonoverlap": len(independent) >= minimum_independent}
    return {"status": "SUFFICIENT" if all(checks.values()) else "INSUFFICIENT",
            "row_count": len(rows), "class_0": counts[0], "class_1": counts[1],
            "nonoverlap_count": len(independent), "checks": checks,
            "minimums": {"rows": minimum_rows, "each_class": minimum_class,
                         "nonoverlap": minimum_independent},
            "nonoverlap_ids": independent}


def split_manifest(labels):
    labels = tuple(sorted(labels, key=lambda r: (r.decision_time, r.symbol)))
    if (len({r.row_id for r in labels}) != len(labels)
            or any(not START <= r.decision_time < DEV_END for r in labels)):
        raise PermissionError("Split input must contain unique development opportunities only")
    valid = tuple(r for r in labels if r.status == "VALID")
    for r in valid:
        if r.interval_start != r.decision_time + 1 or r.interval_end != r.interval_start + BUFFER or r.interval_end > DEV_END:
            raise ValueError("Invalid/mismatched label interval")
    folds = []
    for number, (begin, end) in enumerate(FOLDS, 1):
        train, evaluation, exclusions = [], [], Counter()
        excluded_ids = {}
        for row in labels:
            reason = None
            if row.decision_time < begin:
                if row.status != "VALID":
                    reason = row.status
                elif row.interval_end > begin:
                    reason = "PURGED_OVERLAP"
                elif row.interval_end > begin - BUFFER:
                    reason = "FOUR_HOUR_BUFFER"
                else:
                    train.append(row)
            elif row.decision_time < end:
                if row.status != "VALID":
                    reason = row.status
                elif row.interval_end > end:
                    reason = "EVALUATION_HORIZON_CUTOFF"
                else:
                    evaluation.append(row)
            if reason:
                exclusions[reason] += 1
                excluded_ids[row.row_id] = reason
        folds.append({"fold": number, "train_start": START, "train_end": begin,
                      "evaluation_start": begin, "evaluation_end": end,
                      "maximum_training_label_end": begin-BUFFER,
                      "train_ids": [r.row_id for r in train],
                      "evaluation_ids": [r.row_id for r in evaluation],
                      "exclusion_counts": dict(sorted(exclusions.items())),
                      "excluded_ids": excluded_ids,
                      "train_gate": sufficiency(train, "train"),
                      "evaluation_gate": sufficiency(evaluation, "development_evaluation")})
    return {"interval_semantics": "UTC half-open; grouping by decision timestamp",
            "full_horizon_ms": 14_400_000, "additional_pre_evaluation_buffer_ms": BUFFER,
            "folds": folds,
            "selection_validation": {"start": DEV_END, "end": VALIDATION_END,
                                     "status": "LOCKED / NOT EVALUATED"},
            "final": {"start": VALIDATION_END, "end": DATA_END,
                      "status": "LOCKED / NOT EVALUATED",
                      "previously_inspected_by_baseline_research": True}}
