import csv
import re
import unicodedata
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.dummy import DummyClassifier
from sklearn.linear_model import LogisticRegression
from sklearn.metrics.pairwise import cosine_similarity

from .catalog import TEAM_BY_ID, TEAMS
from .repository import SupportRepository


DEFAULT_DATASET = Path(__file__).parent / "data" / "demo_tickets.csv"


@dataclass(frozen=True)
class Candidate:
    team_id: str
    name: str
    score: float
    category_score: float
    semantic_score: float


class SupportRouter:
    """Classify a request and rank eligible support teams."""

    @staticmethod
    def normalize_text(text: str) -> str:
        """Normalize common support phrases before training and prediction."""
        normalized = unicodedata.normalize("NFKC", text).lower().strip()
        normalized = re.sub(r"[^\w\s]+", " ", normalized, flags=re.UNICODE)
        normalized = re.sub(r"\s+", " ", normalized)
        phrases = []

        if "password" in normalized and any(
            term in normalized
            for term in ("reset", "recover", "recovering", "forgot", "forgotten")
        ):
            phrases.append("canonical account password reset")
        if any(term in normalized for term in ("cannot log in", "cannot login", "can not log in", "locked out")):
            phrases.append("canonical account sign in")
        if "kyc" in normalized and (
            "maker" in normalized or "checker" in normalized or "role" in normalized
        ):
            phrases.append("canonical kyc maker checker access")
        if any(term in normalized for term in ("transferred", "transfer", "branch transfer")) and any(
            term in normalized for term in ("profile", "department", "position", "grade", "employee")
        ):
            phrases.append("canonical employee record transfer")
        if "payment" in normalized or "transfer" in normalized:
            if any(term in normalized for term in ("missing", "not received", "pending", "reconciliation")):
                phrases.append("canonical missing transfer payment")

        return f"{normalized} {' '.join(phrases)}".strip()

    def __init__(
        self,
        dataset_path: Path = DEFAULT_DATASET,
        confidence_threshold: float = 0.34,
        margin_threshold: float = 0.05,
        repository: SupportRepository | None = None,
    ) -> None:
        self.confidence_threshold = confidence_threshold
        self.margin_threshold = margin_threshold
        self.teams = repository.get_teams(enabled_only=True) if repository else [
            {
                "id": team.id,
                "name": team.name,
                "description": team.description,
                "contact_phone": "",
                "guidance": "",
            }
            for team in TEAMS
        ]
        enabled_team_ids = {team["id"] for team in self.teams}
        if repository:
            examples = [
                example
                for example in repository.get_examples()
                if example["team_id"] in enabled_team_ids
            ]
        else:
            examples = [
                row
                for row in self._load_examples(dataset_path)
                if row["team_id"] in enabled_team_ids
            ]
        texts = [self.normalize_text(row["text"]) for row in examples]
        labels = [row["team_id"] for row in examples]

        self.vectorizer = TfidfVectorizer(
            lowercase=True,
            ngram_range=(1, 2),
            strip_accents="unicode",
            sublinear_tf=True,
        )
        training_vectors = self.vectorizer.fit_transform(texts)
        if len(set(labels)) == 1:
            self.classifier = DummyClassifier(strategy="constant", constant=labels[0])
        else:
            self.classifier = LogisticRegression(
                max_iter=1000,
                class_weight="balanced",
                random_state=42,
            )
        self.classifier.fit(training_vectors, labels)
        self.team_vectors = self.vectorizer.transform(
            [self.normalize_text(team["description"]) for team in self.teams]
        )
        self.team_ids = [team["id"] for team in self.teams]

    @staticmethod
    def _load_examples(path: Path) -> list[dict[str, str]]:
        with path.open(newline="", encoding="utf-8") as file:
            rows = list(csv.DictReader(file))
        if not rows or not {"text", "team_id"}.issubset(rows[0]):
            raise ValueError("The training dataset must contain text and team_id columns.")
        unknown = {row["team_id"] for row in rows} - set(TEAM_BY_ID)
        if unknown:
            raise ValueError(f"Dataset contains unknown support teams: {', '.join(sorted(unknown))}")
        return rows

    def recommend(self, text: str, top_k: int = 3) -> dict[str, Any]:
        cleaned_text = text.strip()
        if not cleaned_text:
            raise ValueError("Request text cannot be empty.")
        if top_k < 1:
            raise ValueError("top_k must be at least 1.")

        request_vector = self.vectorizer.transform([self.normalize_text(cleaned_text)])
        category_probabilities = self.classifier.predict_proba(request_vector)[0]
        class_ids = list(self.classifier.classes_)
        category_scores = dict(zip(class_ids, category_probabilities))

        similarities = cosine_similarity(request_vector, self.team_vectors)[0]
        semantic_scores = dict(zip(self.team_ids, similarities))
        max_similarity = max(semantic_scores.values(), default=0.0)

        candidates = []
        for team in self.teams:
            semantic_score = semantic_scores[team["id"]]
            normalized_semantic_score = (
                semantic_score / max_similarity if max_similarity > 0 else 0.0
            )
            category_score = float(category_scores.get(team["id"], 0.0))
            score = 0.85 * category_score + 0.15 * normalized_semantic_score
            candidates.append(
                Candidate(
                    team_id=team["id"],
                    name=team["name"],
                    score=score,
                    category_score=category_score,
                    semantic_score=float(semantic_score),
                )
            )
        candidates.sort(key=lambda candidate: candidate.score, reverse=True)

        best = candidates[0]
        team_details = next(team for team in self.teams if team["id"] == best.team_id)
        runner_up_score = candidates[1].score if len(candidates) > 1 else 0.0
        margin = best.score - runner_up_score
        confident = (
            best.score >= self.confidence_threshold
            and margin >= self.margin_threshold
            and best.semantic_score >= 0.015
        )
        explanation = (
            f"The request most closely matches {team_details['name']}'s service description "
            f"and examples of {team_details['name'].lower()} requests."
        )

        return {
            "status": "recommended" if confident else "human_review",
            "predicted_category": best.team_id,
            "recommended_team": (
                {
                    "id": team_details["id"],
                    "name": team_details["name"],
                }
                if confident
                else None
            ),
            "suggested_team": (
                {
                    key: team_details[key]
                    for key in ("id", "name", "description", "contact_phone", "guidance")
                }
                if confident
                else None
            ),
            "candidates": [
                {
                    "id": candidate.team_id,
                    "name": candidate.name,
                    "score": float(round(candidate.score, 4)),
                }
                for candidate in candidates[:top_k]
            ],
            "confidence_score": round(best.score, 4),
            "score_is_calibrated_probability": False,
            "explanation": explanation,
            "next_step": (
                "Review the recommendation and submit the request."
                if confident
                else "A support specialist should review this request or ask a clarifying question."
            ),
        }
