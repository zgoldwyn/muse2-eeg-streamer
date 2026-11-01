"""Calculate artifact-detector metrics for the ten-window synthetic example."""


def safe_divide(numerator: int, denominator: int) -> float | None:
    """Return None when a metric is undefined instead of silently returning zero."""
    return None if denominator == 0 else numerator / denominator


def show_metric(name: str, value: float | None) -> None:
    if value is None:
        print(f"{name}: unavailable (zero denominator)")
    else:
        print(f"{name}: {value:.4f}")


def main() -> None:
    true_positives = 3
    false_negatives = 1
    false_positives = 1
    true_negatives = 5
    total_windows = 10

    recall = safe_divide(true_positives, true_positives + false_negatives)
    precision = safe_divide(true_positives, true_positives + false_positives)
    clean_retention = safe_divide(true_negatives, true_negatives + false_positives)
    accepted_contamination = safe_divide(false_negatives, true_negatives + false_negatives)
    coverage = safe_divide(true_negatives + false_negatives, total_windows)

    show_metric("Recall", recall)
    show_metric("Precision", precision)
    show_metric("Clean retention", clean_retention)
    show_metric("Accepted contamination", accepted_contamination)
    show_metric("Coverage", coverage)


if __name__ == "__main__":
    main()
