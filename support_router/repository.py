import csv
import json
import sqlite3
from pathlib import Path

from .catalog import TEAMS
from .privacy import redact_pii

BUILTIN_DATASET = Path(__file__).parent / "data" / "demo_tickets.csv"


class SupportRepository:
    def __init__(self, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        self.path = path
        with self._connect() as connection:
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS support_teams (
                    id TEXT PRIMARY KEY,
                    name TEXT NOT NULL,
                    description TEXT NOT NULL,
                    contact_phone TEXT NOT NULL DEFAULT '',
                    guidance TEXT NOT NULL DEFAULT '',
                    enabled INTEGER NOT NULL DEFAULT 1
                )
                """
            )
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS training_examples (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    text TEXT NOT NULL,
                    team_id TEXT NOT NULL REFERENCES support_teams(id) ON DELETE CASCADE,
                    source TEXT NOT NULL DEFAULT 'curated',
                    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
                )
                """
            )
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS app_metadata (
                    key TEXT PRIMARY KEY,
                    value TEXT NOT NULL
                )
                """
            )
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS routing_requests (
                    request_id TEXT PRIMARY KEY,
                    text TEXT NOT NULL,
                    status TEXT NOT NULL,
                    predicted_category TEXT NOT NULL,
                    recommended_team_id TEXT,
                    confidence_score REAL NOT NULL,
                    candidates_json TEXT NOT NULL,
                    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    resolved_team_id TEXT,
                    reviewer_note TEXT NOT NULL DEFAULT '',
                    resolved_at TEXT,
                    helpful INTEGER
                )
                """
            )
            team_columns = {
                row["name"]
                for row in connection.execute("PRAGMA table_info(support_teams)")
            }
            if "enabled" not in team_columns:
                connection.execute(
                    "ALTER TABLE support_teams ADD COLUMN enabled INTEGER NOT NULL DEFAULT 1"
                )
            example_columns = {
                row["name"]
                for row in connection.execute("PRAGMA table_info(training_examples)")
            }
            if "source" not in example_columns:
                connection.execute(
                    "ALTER TABLE training_examples ADD COLUMN source TEXT NOT NULL DEFAULT 'curated'"
                )
            for row in connection.execute("SELECT id, text FROM training_examples").fetchall():
                sanitized = redact_pii(row["text"])
                if sanitized != row["text"]:
                    connection.execute(
                        "UPDATE training_examples SET text = ? WHERE id = ?",
                        (sanitized, row["id"]),
                    )
            for row in connection.execute(
                "SELECT request_id, text, reviewer_note FROM routing_requests"
            ).fetchall():
                sanitized = redact_pii(row["text"])
                sanitized_note = redact_pii(row["reviewer_note"])
                if sanitized != row["text"] or sanitized_note != row["reviewer_note"]:
                    connection.execute(
                        """
                        UPDATE routing_requests SET text = ?, reviewer_note = ?
                        WHERE request_id = ?
                        """,
                        (sanitized, sanitized_note, row["request_id"]),
                    )
            catalog_initialized = connection.execute(
                "SELECT 1 FROM app_metadata WHERE key = 'builtin_catalog_initialized'"
            ).fetchone()
            if catalog_initialized is None:
                connection.executemany(
                    """
                    INSERT OR IGNORE INTO support_teams (id, name, description)
                    VALUES (?, ?, ?)
                    """,
                    [(team.id, team.name, team.description) for team in TEAMS],
                )
            connection.execute(
                """
                UPDATE support_teams
                SET name = ?, description = ?, contact_phone = ?, guidance = ?
                WHERE id = 'account_access'
                  AND contact_phone = ''
                  AND guidance = ''
                  AND name = 'Account Access'
                  AND NOT EXISTS (
                    SELECT 1 FROM app_metadata WHERE key = 'builtin_catalog_initialized'
                  )
                """,
                (
                    "Enat IT Department",
                    "Enat system login, password resets, locked accounts, identity verification, and profile access.",
                    "0986680289",
                    "For help resetting your Enat system password, call the IT Department at 0986680289. Never share your password or a one-time verification code.",
                ),
            )
            connection.execute(
                """
                UPDATE support_teams
                SET description = ?
                WHERE id = 'account_access'
                  AND description = 'Enat system login, password resets, locked accounts, identity verification, and profile access.'
                  AND NOT EXISTS (
                    SELECT 1 FROM app_metadata WHERE key = 'builtin_catalog_initialized'
                  )
                """,
                (
                    "Enat system login, password resets, locked accounts, KYC user roles, maker and checker access, and account permissions.",
                ),
            )
            connection.execute(
                """
                UPDATE support_teams
                SET guidance = ?
                WHERE id = 'account_access'
                  AND guidance = 'For help resetting your Enat system password, call the IT Department at 0986680289. Never share your password or a one-time verification code.'
                  AND NOT EXISTS (
                    SELECT 1 FROM app_metadata WHERE key = 'builtin_catalog_initialized'
                  )
                """,
                (
                    "For Enat password resets or approved KYC maker/checker role changes, contact the IT Department at 0986680289. Role changes require authorization and must follow your organization's access-control policy. Never share passwords or verification codes.",
                ),
            )
            connection.execute(
                """
                UPDATE support_teams
                SET description = ?, contact_phone = ?, guidance = ?
                WHERE id = 'human_resources'
                  AND name = 'Human Resources (HR)'
                  AND contact_phone = ''
                  AND guidance = ''
                  AND NOT EXISTS (
                    SELECT 1 FROM app_metadata WHERE key = 'builtin_catalog_initialized'
                  )
                """,
                (
                    "Employee records and HR profile corrections, including branch or department transfers, position, grade, name, and employment details.",
                    "0912121212",
                    "For corrections to your Enat employee profile after a transfer, or for an incorrect branch, department, position, grade, name, or account record, contact Human Resources at 0912121212. Do not send passwords or sensitive account credentials.",
                ),
            )
            connection.execute(
                """
                INSERT INTO training_examples (text, team_id, source)
                SELECT ?, 'account_access', 'demo'
                WHERE NOT EXISTS (
                    SELECT 1 FROM training_examples WHERE text = ? AND team_id = 'account_access'
                )
                  AND NOT EXISTS (
                    SELECT 1 FROM app_metadata WHERE key = 'builtin_catalog_initialized'
                )
                """,
                (
                    "I cannot log in to my Enat system. Who can reset my password?",
                    "I cannot log in to my Enat system. Who can reset my password?",
                ),
            )
            connection.executemany(
                """
                INSERT INTO training_examples (text, team_id, source)
                SELECT ?, ?, 'demo'
                WHERE NOT EXISTS (
                    SELECT 1 FROM training_examples WHERE text = ? AND team_id = ?
                )
                  AND NOT EXISTS (
                    SELECT 1 FROM app_metadata WHERE key = 'builtin_catalog_initialized'
                )
                """,
                [
                    (
                        "I transferred to another branch but my Enat profile still shows my old branch and department.",
                        "human_resources",
                        "I transferred to another branch but my Enat profile still shows my old branch and department.",
                        "human_resources",
                    ),
                    (
                        "My employee profile has the wrong position, grade, department, name, or account details.",
                        "human_resources",
                        "My employee profile has the wrong position, grade, department, name, or account details.",
                        "human_resources",
                    ),
                    (
                        "I moved to a different department but the Enat system still shows my previous department.",
                        "human_resources",
                        "I moved to a different department but the Enat system still shows my previous department.",
                        "human_resources",
                    ),
                    (
                        "I used the Enat KYC system as a maker and need to request a role change to checker.",
                        "account_access",
                        "I used the Enat KYC system as a maker and need to request a role change to checker.",
                        "account_access",
                    ),
                    (
                        "I need both maker and checker access in the KYC system. Who can review this access request?",
                        "account_access",
                        "I need both maker and checker access in the KYC system. Who can review this access request?",
                        "account_access",
                    ),
                    (
                        "Please change my Enat KYC user role from maker to checker.",
                        "account_access",
                        "Please change my Enat KYC user role from maker to checker.",
                        "account_access",
                    ),
                ],
            )
            connection.execute(
                """
                INSERT OR IGNORE INTO app_metadata (key, value)
                VALUES ('builtin_catalog_initialized', 'true')
                """
            )
            seeded = connection.execute(
                "SELECT 1 FROM app_metadata WHERE key = 'demo_examples_seeded'"
            ).fetchone()
            if seeded is None:
                with BUILTIN_DATASET.open(newline="", encoding="utf-8") as file:
                    builtin_rows = list(csv.DictReader(file))
                    for row in builtin_rows:
                        connection.execute(
                            """
                            INSERT INTO training_examples (text, team_id, source)
                            SELECT ?, ?, 'demo'
                            WHERE NOT EXISTS (
                                SELECT 1 FROM training_examples
                                WHERE text = ? AND team_id = ?
                            )
                            """,
                            (row["text"], row["team_id"], row["text"], row["team_id"]),
                        )
                connection.execute(
                    "INSERT INTO app_metadata (key, value) VALUES ('demo_examples_seeded', 'true')"
                )
            with BUILTIN_DATASET.open(newline="", encoding="utf-8") as file:
                builtin_rows = list(csv.DictReader(file))
            connection.executemany(
                """
                UPDATE training_examples SET source = 'demo'
                WHERE text = ? AND team_id = ? AND source = 'curated'
                """,
                [(row["text"], row["team_id"]) for row in builtin_rows]
                + [
                    (
                        "I cannot log in to my Enat system. Who can reset my password?",
                        "account_access",
                    ),
                    (
                        "I transferred to another branch but my Enat profile still shows my old branch and department.",
                        "human_resources",
                    ),
                    (
                        "My employee profile has the wrong position, grade, department, name, or account details.",
                        "human_resources",
                    ),
                    (
                        "I moved to a different department but the Enat system still shows my previous department.",
                        "human_resources",
                    ),
                    (
                        "I used the Enat KYC system as a maker and need to request a role change to checker.",
                        "account_access",
                    ),
                    (
                        "I need both maker and checker access in the KYC system. Who can review this access request?",
                        "account_access",
                    ),
                    (
                        "Please change my Enat KYC user role from maker to checker.",
                        "account_access",
                    ),
                ],
            )

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.path)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys = ON")
        return connection

    def get_teams(self, enabled_only: bool = False) -> list[dict[str, str | int]]:
        where = "WHERE enabled = 1" if enabled_only else ""
        with self._connect() as connection:
            rows = connection.execute(
                "SELECT id, name, description, contact_phone, guidance, enabled "
                f"FROM support_teams {where} ORDER BY name"
            ).fetchall()
        return [dict(row) for row in rows]

    def update_team(
        self,
        team_id: str,
        name: str,
        description: str,
        contact_phone: str,
        guidance: str,
    ) -> dict[str, str | int] | None:
        with self._connect() as connection:
            result = connection.execute(
                """
                UPDATE support_teams
                SET name = ?, description = ?, contact_phone = ?, guidance = ?
                WHERE id = ?
                """,
                (name, description, contact_phone, guidance, team_id),
            )
            if result.rowcount == 0:
                return None
        return next(team for team in self.get_teams() if team["id"] == team_id)

    def create_team(
        self,
        team_id: str,
        name: str,
        description: str,
        contact_phone: str,
        guidance: str,
        initial_example: str,
    ) -> dict[str, str | int]:
        with self._connect() as connection:
            exists = connection.execute(
                "SELECT 1 FROM support_teams WHERE id = ?", (team_id,)
            ).fetchone()
            if exists:
                raise ValueError("A team with this name already exists.")
            connection.execute(
                """
                INSERT INTO support_teams
                    (id, name, description, contact_phone, guidance)
                VALUES (?, ?, ?, ?, ?)
                """,
                (team_id, name, description, contact_phone, guidance),
            )
            connection.execute(
                "INSERT INTO training_examples (text, team_id) VALUES (?, ?)",
                (redact_pii(initial_example), team_id),
            )
        return next(team for team in self.get_teams() if team["id"] == team_id)

    def set_team_enabled(self, team_id: str, enabled: bool) -> dict[str, str | int] | None:
        with self._connect() as connection:
            exists = connection.execute(
                "SELECT 1 FROM support_teams WHERE id = ?", (team_id,)
            ).fetchone()
            if exists is None:
                return None
            if not enabled:
                active_count = connection.execute(
                    "SELECT COUNT(*) FROM support_teams WHERE enabled = 1"
                ).fetchone()[0]
                if active_count <= 1:
                    raise ValueError("At least one support team must remain enabled.")
            connection.execute(
                "UPDATE support_teams SET enabled = ? WHERE id = ?",
                (int(enabled), team_id),
            )
        return next(team for team in self.get_teams() if team["id"] == team_id)

    def delete_team(self, team_id: str) -> bool:
        with self._connect() as connection:
            connection.execute(
                "DELETE FROM training_examples WHERE team_id = ?", (team_id,)
            )
            result = connection.execute(
                "DELETE FROM support_teams WHERE id = ?", (team_id,)
            )
        return result.rowcount > 0

    def add_example(self, text: str, team_id: str) -> dict[str, int | str]:
        text = redact_pii(text).strip()
        if len(text) < 5:
            raise ValueError("The request is too short after sensitive data was removed.")
        with self._connect() as connection:
            team_exists = connection.execute(
                "SELECT 1 FROM support_teams WHERE id = ? AND enabled = 1",
                (team_id,),
            ).fetchone()
            if team_exists is None:
                raise ValueError("Choose a valid support team.")
            result = connection.execute(
                "INSERT INTO training_examples (text, team_id) VALUES (?, ?)",
                (text, team_id),
            )
            example_id = result.lastrowid
        return {"id": example_id, "text": text, "team_id": team_id}

    def import_authorized_examples(self, rows: list[dict[str, str]]) -> int:
        sanitized_rows = [
            (redact_pii(row["text"]).strip(), row["team_id"].strip())
            for row in rows
        ]
        if any(len(text) < 5 for text, _ in sanitized_rows):
            raise ValueError("A request is too short after sensitive data was removed.")
        with self._connect() as connection:
            enabled_ids = {
                row["id"]
                for row in connection.execute(
                    "SELECT id FROM support_teams WHERE enabled = 1"
                )
            }
            unknown = {team_id for _, team_id in sanitized_rows} - enabled_ids
            if unknown:
                raise ValueError(
                    f"Dataset contains unknown or disabled support teams: {', '.join(sorted(unknown))}"
                )
            before = connection.execute(
                "SELECT COUNT(*) FROM training_examples WHERE source = 'authorized'"
            ).fetchone()[0]
            connection.executemany(
                """
                INSERT INTO training_examples (text, team_id, source)
                SELECT ?, ?, 'authorized'
                WHERE NOT EXISTS (
                    SELECT 1 FROM training_examples
                    WHERE text = ? AND team_id = ?
                )
                """,
                [
                    (text, team_id, text, team_id)
                    for text, team_id in sanitized_rows
                ],
            )
            connection.executemany(
                """
                UPDATE training_examples SET source = 'authorized'
                WHERE text = ? AND team_id = ?
                """,
                [(text, team_id) for text, team_id in sanitized_rows],
            )
            imported = (
                connection.execute(
                    "SELECT COUNT(*) FROM training_examples WHERE source = 'authorized'"
                ).fetchone()[0]
                - before
            )
        return imported

    def get_examples(self) -> list[dict[str, int | str]]:
        with self._connect() as connection:
            rows = connection.execute(
                """
                SELECT training_examples.id, training_examples.text,
                       training_examples.team_id, support_teams.name AS team_name,
                       training_examples.source
                FROM training_examples
                JOIN support_teams ON support_teams.id = training_examples.team_id
                WHERE training_examples.source != 'demo'
                   OR NOT EXISTS (
                       SELECT 1 FROM training_examples WHERE source = 'authorized'
                   )
                ORDER BY training_examples.id
                """
            ).fetchall()
        return [dict(row) for row in rows]

    def update_example(
        self, example_id: int, text: str, team_id: str
    ) -> dict[str, int | str] | None:
        text = redact_pii(text).strip()
        if len(text) < 5:
            raise ValueError("The request is too short after sensitive data was removed.")
        with self._connect() as connection:
            example = connection.execute(
                "SELECT team_id FROM training_examples WHERE id = ?", (example_id,)
            ).fetchone()
            if example is None:
                return None
            target = connection.execute(
                "SELECT enabled FROM support_teams WHERE id = ?", (team_id,)
            ).fetchone()
            if target is None or (not target["enabled"] and team_id != example["team_id"]):
                raise ValueError("Choose an enabled support team.")
            original_team = example["team_id"]
            if original_team != team_id:
                remaining = connection.execute(
                    "SELECT COUNT(*) FROM training_examples WHERE team_id = ? AND id != ?",
                    (original_team, example_id),
                ).fetchone()[0]
                if remaining == 0:
                    raise ValueError(
                        "A team must keep at least one training example. Add another example first."
                    )
            connection.execute(
                "UPDATE training_examples SET text = ?, team_id = ? WHERE id = ?",
                (text, team_id, example_id),
            )
        return next(
            example
            for example in self.get_examples()
            if example["id"] == example_id
        )

    def delete_example(self, example_id: int) -> bool:
        with self._connect() as connection:
            example = connection.execute(
                "SELECT team_id FROM training_examples WHERE id = ?", (example_id,)
            ).fetchone()
            if example is None:
                return False
            remaining = connection.execute(
                "SELECT COUNT(*) FROM training_examples WHERE team_id = ? AND id != ?",
                (example["team_id"], example_id),
            ).fetchone()[0]
            if remaining == 0:
                raise ValueError(
                    "A team must keep at least one training example. Add another example first."
                )
            connection.execute("DELETE FROM training_examples WHERE id = ?", (example_id,))
        return True

    def count_examples(self) -> int:
        with self._connect() as connection:
            row = connection.execute(
                "SELECT COUNT(*) AS count FROM training_examples"
            ).fetchone()
        return int(row["count"])

    def save_routing_request(
        self,
        request_id: str,
        text: str,
        result: dict,
    ) -> None:
        text = redact_pii(text)
        recommended_team = result.get("recommended_team")
        with self._connect() as connection:
            connection.execute(
                """
                INSERT INTO routing_requests (
                    request_id, text, status, predicted_category,
                    recommended_team_id, confidence_score, candidates_json
                )
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    request_id,
                    text,
                    result["status"],
                    result["predicted_category"],
                    recommended_team["id"] if recommended_team else None,
                    result["confidence_score"],
                    json.dumps(result["candidates"], ensure_ascii=False),
                ),
            )

    def get_routing_requests(self, admin_view: bool = False) -> list[dict]:
        with self._connect() as connection:
            if admin_view:
                rows = connection.execute(
                    """
                    SELECT r.*, t.name AS resolved_team_name
                    FROM routing_requests r
                    LEFT JOIN support_teams t ON t.id = r.resolved_team_id
                    ORDER BY r.created_at DESC
                    """
                ).fetchall()
            else:
                rows = connection.execute(
                    """
                    SELECT request_id, status, predicted_category,
                           recommended_team_id, confidence_score, created_at,
                           resolved_team_id, helpful
                    FROM routing_requests
                    ORDER BY created_at DESC
                    """
                ).fetchall()
        records = [dict(row) for row in rows]
        for record in records:
            if "candidates_json" in record:
                record["candidates"] = json.loads(record.pop("candidates_json"))
        return records

    def get_human_review_queue(self) -> list[dict]:
        with self._connect() as connection:
            rows = connection.execute(
                """
                SELECT r.request_id, r.text, r.status, r.predicted_category,
                       r.recommended_team_id, r.confidence_score,
                       r.candidates_json, r.created_at, r.resolved_team_id,
                       r.reviewer_note, r.resolved_at, r.helpful
                FROM routing_requests r
                WHERE r.status = 'human_review' AND r.resolved_team_id IS NULL
                ORDER BY r.created_at ASC
                """
            ).fetchall()
        records = [dict(row) for row in rows]
        for record in records:
            record["candidates"] = json.loads(record.pop("candidates_json"))
        return records

    def resolve_routing_request(
        self,
        request_id: str,
        team_id: str,
        reviewer_note: str,
        add_training_example: bool,
    ) -> dict | None:
        with self._connect() as connection:
            request = connection.execute(
                "SELECT text FROM routing_requests WHERE request_id = ?",
                (request_id,),
            ).fetchone()
            if request is None:
                return None
            team = connection.execute(
                "SELECT id FROM support_teams WHERE id = ? AND enabled = 1",
                (team_id,),
            ).fetchone()
            if team is None:
                raise ValueError("Choose a valid enabled support team.")
            connection.execute(
                """
                UPDATE routing_requests
                SET resolved_team_id = ?, reviewer_note = ?, resolved_at = CURRENT_TIMESTAMP
                WHERE request_id = ?
                """,
                (team_id, redact_pii(reviewer_note.strip()), request_id),
            )
            if add_training_example:
                connection.execute(
                    "INSERT INTO training_examples (text, team_id) VALUES (?, ?)",
                    (redact_pii(request["text"]), team_id),
                )
        return {"request_id": request_id, "resolved_team_id": team_id}

    def set_routing_feedback(self, request_id: str, helpful: bool) -> bool:
        with self._connect() as connection:
            result = connection.execute(
                "UPDATE routing_requests SET helpful = ? WHERE request_id = ?",
                (int(helpful), request_id),
            )
        return result.rowcount > 0
