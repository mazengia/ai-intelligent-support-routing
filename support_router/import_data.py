import argparse
import csv
import os
from pathlib import Path

from .privacy import redact_pii
from .repository import SupportRepository


def load_dataset(path: Path) -> list[dict[str, str]]:
    with path.open(newline="", encoding="utf-8-sig") as file:
        reader = csv.DictReader(file)
        if not reader.fieldnames or not {"text", "team_id"}.issubset(reader.fieldnames):
            raise ValueError("CSV must include text and team_id columns.")
        rows = [
            {
                "text": redact_pii((row.get("text") or "").strip()),
                "team_id": (row.get("team_id") or "").strip(),
            }
            for row in reader
        ]
    if not rows or any(len(row["text"]) < 5 or not row["team_id"] for row in rows):
        raise ValueError("Dataset must contain non-empty request text and team labels.")
    return rows


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Import locally held, authorized, de-identified support tickets."
    )
    parser.add_argument("dataset", type=Path, help="Local CSV with text and team_id columns")
    parser.add_argument(
        "--confirm-authorized",
        action="store_true",
        help="Confirm you have permission to use this data for model training.",
    )
    args = parser.parse_args()
    if not args.confirm_authorized:
        parser.error("Pass --confirm-authorized only after obtaining data-owner approval.")
    repository = SupportRepository(
        Path(os.getenv("SUPPORT_ROUTER_DB", "support_router.sqlite3"))
    )
    imported = repository.import_authorized_examples(load_dataset(args.dataset))
    print(
        f"Imported {imported} sanitized examples into the configured local database. "
        "When authorized examples are present, built-in demo examples are excluded from training."
    )


if __name__ == "__main__":
    main()
