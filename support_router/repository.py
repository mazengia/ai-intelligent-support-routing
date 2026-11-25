import sqlite3
from pathlib import Path

from .catalog import TEAMS


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
                    guidance TEXT NOT NULL DEFAULT ''
                )
                """
            )
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS training_examples (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    text TEXT NOT NULL,
                    team_id TEXT NOT NULL REFERENCES support_teams(id),
                    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
                )
                """
            )
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
                INSERT OR IGNORE INTO support_teams (id, name, description)
                VALUES (?, ?, ?)
                """,
                (
                    "human_resources",
                    "Human Resources (HR)",
                    "Employee records and HR profile corrections, including branch or department transfers, position, grade, name, and employment details.",
                ),
            )
            connection.execute(
                """
                UPDATE support_teams
                SET description = ?
                WHERE id = 'account_access'
                  AND description = 'Enat system login, password resets, locked accounts, identity verification, and profile access.'
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
                """,
                (
                    "For Enat password resets or approved KYC maker/checker role changes, contact the IT Department at 0986680289. Role changes require authorization and must follow your organization's access-control policy. Never share passwords or verification codes.",
                ),
            )
            connection.execute(
                """
                INSERT OR IGNORE INTO support_teams
                    (id, name, description, contact_phone, guidance)
                VALUES (?, ?, ?, ?, ?)
                """,
                (
                    "human_resources",
                    "Human Resources (HR)",
                    "Employee records and HR profile corrections, including branch or department transfers, position, grade, name, and employment details.",
                    "0912121212",
                    "For corrections to your Enat employee profile after a transfer, or for an incorrect branch, department, position, grade, name, or account record, contact Human Resources at 0912121212. Do not send passwords or sensitive account credentials.",
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
                """,
                (
                    "Employee records and HR profile corrections, including branch or department transfers, position, grade, name, and employment details.",
                    "0912121212",
                    "For corrections to your Enat employee profile after a transfer, or for an incorrect branch, department, position, grade, name, or account record, contact Human Resources at 0912121212. Do not send passwords or sensitive account credentials.",
                ),
            )
            connection.execute(
                """
                INSERT INTO training_examples (text, team_id)
                SELECT ?, 'account_access'
                WHERE NOT EXISTS (
                    SELECT 1 FROM training_examples WHERE text = ? AND team_id = 'account_access'
                )
                """,
                (
                    "I cannot log in to my Enat system. Who can reset my password?",
                    "I cannot log in to my Enat system. Who can reset my password?",
                ),
            )
            connection.executemany(
                """
                INSERT INTO training_examples (text, team_id)
                SELECT ?, ?
                WHERE NOT EXISTS (
                    SELECT 1 FROM training_examples WHERE text = ? AND team_id = ?
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

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.path)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys = ON")
        return connection

    def get_teams(self) -> list[dict[str, str]]:
        with self._connect() as connection:
            rows = connection.execute(
                "SELECT id, name, description, contact_phone, guidance "
                "FROM support_teams ORDER BY name"
            ).fetchall()
        return [dict(row) for row in rows]

    def update_team(
        self,
        team_id: str,
        name: str,
        description: str,
        contact_phone: str,
        guidance: str,
    ) -> dict[str, str] | None:
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

    def add_example(self, text: str, team_id: str) -> dict[str, int | str]:
        with self._connect() as connection:
            team_exists = connection.execute(
                "SELECT 1 FROM support_teams WHERE id = ?", (team_id,)
            ).fetchone()
            if team_exists is None:
                raise ValueError("Choose a valid support team.")
            result = connection.execute(
                "INSERT INTO training_examples (text, team_id) VALUES (?, ?)",
                (text, team_id),
            )
            example_id = result.lastrowid
        return {"id": example_id, "text": text, "team_id": team_id}

    def get_examples(self) -> list[dict[str, str]]:
        with self._connect() as connection:
            rows = connection.execute(
                "SELECT text, team_id FROM training_examples ORDER BY id"
            ).fetchall()
        return [dict(row) for row in rows]

    def count_examples(self) -> int:
        with self._connect() as connection:
            row = connection.execute(
                "SELECT COUNT(*) AS count FROM training_examples"
            ).fetchone()
        return int(row["count"])
