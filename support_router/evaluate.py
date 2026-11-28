import argparse
import csv
from collections import Counter
from pathlib import Path

from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import (
    accuracy_score,
    classification_report,
    confusion_matrix,
    f1_score,
)
from sklearn.model_selection import StratifiedKFold, cross_val_predict, train_test_split
from sklearn.pipeline import make_pipeline

from .privacy import redact_pii
from .router import DEFAULT_DATASET, SupportRouter


KEYWORDS = {
    "account_access": ("password", "login", "sign in", "account", "profile", "locked"),
    "payments": ("transfer", "deposit", "recipient", "transaction", "reconcil", "payment"),
    "cards": ("card", "debit", "credit", "stolen", "declined"),
    "billing": ("invoice", "charge", "bill", "statement", "fee", "balance"),
    "loans": ("loan", "repay", "installment", "eligibility"),
    "technical_support": (
        "application",
        "app",
        "website",
        "error",
        "crash",
        "install",
        "screen",
        "freeze",
        "unavailable",
    ),
}


def keyword_prediction(text: str) -> str:
    lowered = text.lower()
    counts = {
        team_id: sum(lowered.count(term) for term in terms)
        for team_id, terms in KEYWORDS.items()
    }
    return max(counts, key=counts.get)


def evaluate_authorized_dataset(dataset: Path, test_size: float) -> None:
    with dataset.open(newline="", encoding="utf-8-sig") as file:
        rows = list(csv.DictReader(file))
    if not rows or not {"text", "team_id"}.issubset(rows[0]):
        raise ValueError("The dataset must contain text and team_id columns.")

    unique_rows: dict[str, str] = {}
    duplicate_count = 0
    for row in rows:
        text = redact_pii((row.get("text") or "").strip())
        team_id = (row.get("team_id") or "").strip()
        if len(text) < 5 or not team_id:
            raise ValueError("Every row must have request text and a team_id label.")
        normalized = SupportRouter.normalize_text(text)
        previous_label = unique_rows.get(normalized)
        if previous_label is not None:
            if previous_label != team_id:
                raise ValueError(
                    "Duplicate normalized requests have conflicting team labels; resolve them before evaluation."
                )
            duplicate_count += 1
            continue
        unique_rows[normalized] = team_id

    texts = list(unique_rows)
    labels = list(unique_rows.values())
    counts = Counter(labels)
    if len(counts) < 2 or min(counts.values()) < 2:
        raise ValueError(
            "At least two distinct requests per team are required for a held-out split."
        )
    if not 0.1 <= test_size <= 0.5:
        raise ValueError("test_size must be between 0.1 and 0.5.")
    class_count = len(counts)
    if int(len(labels) * test_size) < class_count:
        raise ValueError(
            "The test split is too small to include every team; increase test_size or add more labeled data."
        )

    train_texts, test_texts, train_labels, test_labels = train_test_split(
        texts,
        labels,
        test_size=test_size,
        random_state=42,
        stratify=labels,
    )
    model = make_pipeline(
        TfidfVectorizer(
            ngram_range=(1, 2),
            strip_accents="unicode",
            sublinear_tf=True,
        ),
        LogisticRegression(max_iter=1000, class_weight="balanced", random_state=42),
    )
    model.fit(train_texts, train_labels)
    predictions = model.predict(test_texts)
    class_labels = sorted(counts)

    print(f"Dataset: {dataset.name} ({len(labels)} unique, sanitized requests)")
    print(f"Split: {len(train_labels)} train / {len(test_labels)} held-out test (stratified)")
    print(f"Exact normalized duplicates excluded: {duplicate_count}")
    print(f"Accuracy: {accuracy_score(test_labels, predictions):.3f}")
    print(
        f"Macro F1: {f1_score(test_labels, predictions, average='macro', zero_division=0):.3f}"
    )
    print("Per-class metrics:")
    print(
        classification_report(
            test_labels,
            predictions,
            labels=class_labels,
            zero_division=0,
        )
    )
    print("Confusion matrix (rows=true, columns=predicted; labels sorted alphabetically):")
    print(confusion_matrix(test_labels, predictions, labels=class_labels))
    print(
        "Evaluation only; it does not prove deployment readiness. Review authorization, "
        "label quality, split design, and privacy with the data owner."
    )


def evaluate_demo_dataset() -> None:
    with DEFAULT_DATASET.open(newline="", encoding="utf-8") as file:
        rows = list(csv.DictReader(file))
    texts = [row["text"] for row in rows]
    labels = [row["team_id"] for row in rows]
    least_populated_class = min(Counter(labels).values())
    folds = min(5, least_populated_class)
    if folds < 2:
        raise ValueError("At least two labeled examples per team are required.")

    splitter = StratifiedKFold(n_splits=folds, shuffle=True, random_state=42)
    model = make_pipeline(
        TfidfVectorizer(
            ngram_range=(1, 2),
            strip_accents="unicode",
            sublinear_tf=True,
        ),
        LogisticRegression(max_iter=1000, class_weight="balanced", random_state=42),
    )
    model_predictions = cross_val_predict(model, texts, labels, cv=splitter)
    keyword_predictions = [keyword_prediction(text) for text in texts]

    print(f"Dataset: {DEFAULT_DATASET.name} ({len(rows)} synthetic requests)")
    print(f"Evaluation: stratified {folds}-fold cross-validation for the learned model")
    print("Scores are illustrative and do not estimate real-world performance.")
    for name, predictions in (
        ("Keyword baseline", keyword_predictions),
        ("TF-IDF + Logistic Regression", model_predictions),
    ):
        print(
            f"{name}: accuracy={accuracy_score(labels, predictions):.3f}, "
            f"macro_f1={f1_score(labels, predictions, average='macro', zero_division=0):.3f}"
        )


def main() -> None:
    parser = argparse.ArgumentParser(description="Evaluate support-routing training data.")
    parser.add_argument(
        "--dataset",
        type=Path,
        help="Evaluate a local authorized CSV using a stratified held-out test split.",
    )
    parser.add_argument(
        "--authorized-data",
        action="store_true",
        help="Confirm the data owner authorized this data for evaluation.",
    )
    parser.add_argument("--test-size", type=float, default=0.2)
    args = parser.parse_args()
    if args.dataset:
        if not args.authorized_data:
            parser.error("Pass --authorized-data only after obtaining data-owner approval.")
        evaluate_authorized_dataset(args.dataset, args.test_size)
    else:
        if args.authorized_data:
            parser.error("--authorized-data requires --dataset.")
        evaluate_demo_dataset()


if __name__ == "__main__":
    main()
