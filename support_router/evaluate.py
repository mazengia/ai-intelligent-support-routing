import csv
from collections import Counter

from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import accuracy_score, f1_score
from sklearn.model_selection import StratifiedKFold, cross_val_predict
from sklearn.pipeline import make_pipeline

from .router import DEFAULT_DATASET


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


def main() -> None:
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


if __name__ == "__main__":
    main()
