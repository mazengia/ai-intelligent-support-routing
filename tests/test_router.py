from fastapi.testclient import TestClient
import pytest

from support_router.api import app
from support_router.evaluate import evaluate_authorized_dataset
from support_router.privacy import redact_pii
from support_router.repository import SupportRepository
from support_router.router import SupportRouter


def test_clear_request_gets_relevant_team():
    router = SupportRouter()
    result = router.recommend(
        "I transferred money but the recipient has not received the payment."
    )

    assert result["status"] == "recommended"
    assert result["recommended_team"]["id"] == "payments"
    assert result["candidates"][0]["id"] == "payments"


def test_empty_or_invalid_requests_are_rejected():
    router = SupportRouter()
    with pytest.raises(ValueError, match="cannot be empty"):
        router.recommend("   ")


def test_vague_request_is_escalated():
    result = SupportRouter().recommend("I need help with something.")

    assert result["status"] == "human_review"
    assert result["recommended_team"] is None
    assert result["suggested_team"] is None


def test_unrelated_request_is_not_assigned_a_default_team():
    result = SupportRouter().recommend("sdsgwef")

    assert result["status"] == "human_review"
    assert result["recommended_team"] is None
    assert result["suggested_team"] is None


def test_equivalent_password_reset_wording_gets_the_same_team():
    router = SupportRouter()
    reset_first = router.recommend("Reset my Enat system password")
    noun_phrase = router.recommend("enat system password reset")

    assert reset_first["recommended_team"]["id"] == "account_access"
    assert noun_phrase["recommended_team"]["id"] == "account_access"


def test_api_serves_ui_and_routes_request(tmp_path, monkeypatch):
    monkeypatch.setenv("SUPPORT_ROUTER_DB", str(tmp_path / "test.sqlite3"))
    with TestClient(app) as client:
        assert client.get("/health").json() == {"status": "ok"}
        page = client.get("/")
        assert page.status_code == 200
        assert "Forgot password" in page.text
        assert "Never share your password" in page.text
        assert "Routing score:" not in page.text
        assert "Staff workspace" in page.text
        assert "Interactive prototype" in page.text
        assert "Keep a human in the loop" in page.text
        response = client.post(
            "/api/route",
            json={"text": "I cannot log in to my Enat system. Who can reset my password?"},
        )

    assert response.status_code == 200
    payload = response.json()
    assert payload["recommended_team"]["id"] == "account_access"
    assert payload["suggested_team"]["contact_phone"] == "0986680289"
    assert payload["request_id"]


def test_enat_employee_record_issues_route_to_hr(tmp_path, monkeypatch):
    monkeypatch.setenv("SUPPORT_ROUTER_DB", str(tmp_path / "enat-hr.sqlite3"))

    with TestClient(app) as client:
        response = client.post(
            "/api/route",
            json={
                "text": (
                    "I transferred to another branch but my profile still shows "
                    "my old branch. My position, grade, department and name are wrong."
                )
            },
        )

    data = response.json()
    assert response.status_code == 200
    assert data["recommended_team"]["id"] == "human_resources"
    assert data["suggested_team"]["contact_phone"] == "0912121212"


def test_enat_kyc_maker_checker_access_routes_to_it(tmp_path, monkeypatch):
    monkeypatch.setenv("SUPPORT_ROUTER_DB", str(tmp_path / "enat-kyc.sqlite3"))

    with TestClient(app) as client:
        response = client.post(
            "/api/route",
            json={
                "text": (
                    "I used Enat KYC as a maker and need to request a role change "
                    "to checker or both maker and checker access."
                )
            },
        )

    data = response.json()
    assert response.status_code == 200
    assert data["recommended_team"]["id"] == "account_access"
    assert data["suggested_team"]["contact_phone"] == "0986680289"
    assert "authorization" in data["suggested_team"]["guidance"]


def test_api_rejects_blank_request():
    with TestClient(app) as client:
        response = client.post("/api/route", json={"text": "   "})

    assert response.status_code == 422


def test_admin_can_update_contact_and_add_training_example(tmp_path, monkeypatch):
    monkeypatch.setenv("SUPPORT_ROUTER_DB", str(tmp_path / "admin.sqlite3"))
    monkeypatch.setenv("SUPPORT_ADMIN_PASSWORD", "test-admin-password")

    with TestClient(app) as client:
        assert client.get("/api/admin/teams").status_code == 401
        headers = {"Authorization": "Basic YWRtaW46dGVzdC1hZG1pbi1wYXNzd29yZA=="}
        teams = client.get("/api/admin/teams", headers=headers)
        assert teams.status_code == 200

        updated = client.put(
            "/api/admin/teams/account_access",
            headers=headers,
            json={
                "name": "Enat IT Department",
                "description": "Enat password resets, sign in, and account access.",
                "contact_phone": "0986680289",
                "guidance": "Call the Enat IT Department at 0986680289 for password reset help.",
            },
        )
        assert updated.status_code == 200
        learned = client.post(
            "/api/admin/examples",
            headers=headers,
            json={
                "text": "My Enat login is blocked and I need to reset it.",
                "team_id": "account_access",
            },
        )
        assert learned.status_code == 200
        assert "retrained" in learned.json()["message"]
        customer_result = client.post(
            "/api/route",
            json={"text": "My Enat login is blocked and I need to reset it."},
        ).json()

    assert customer_result["suggested_team"]["name"] == "Enat IT Department"
    assert customer_result["suggested_team"]["contact_phone"] == "0986680289"


def test_admin_can_add_team_and_model_uses_it(tmp_path, monkeypatch):
    monkeypatch.setenv("SUPPORT_ROUTER_DB", str(tmp_path / "new-team.sqlite3"))
    monkeypatch.setenv("SUPPORT_ADMIN_PASSWORD", "test-admin-password")
    headers = {"Authorization": "Basic YWRtaW46dGVzdC1hZG1pbi1wYXNzd29yZA=="}
    request_text = "My payroll salary has not been deposited into my account."

    with TestClient(app) as client:
        response = client.post(
            "/api/admin/teams",
            headers=headers,
            json={
                "name": "Payroll Support",
                "description": "Salary payments, payroll records, and payslips.",
                "contact_phone": "0900000000",
                "guidance": "Contact Payroll Support for salary payment help.",
                "initial_example": request_text,
            },
        )
        assert response.status_code == 201
        assert response.json()["team"]["id"] == "payroll_support"

        teams = client.get("/api/admin/teams", headers=headers).json()
        assert any(team["id"] == "payroll_support" for team in teams)
        route_response = client.post("/api/route", json={"text": request_text})
        assert route_response.status_code == 200
        result = route_response.json()

        duplicate = client.post(
            "/api/admin/teams",
            headers=headers,
            json={
                "name": "Payroll Support",
                "description": "Duplicate team.",
                "initial_example": "A duplicate example request.",
            },
        )

    assert result["recommended_team"]["id"] == "payroll_support"
    assert result["suggested_team"]["contact_phone"] == "0900000000"
    assert duplicate.status_code == 409


def test_admin_can_disable_enable_edit_and_delete_team(tmp_path, monkeypatch):
    monkeypatch.setenv("SUPPORT_ROUTER_DB", str(tmp_path / "team-controls.sqlite3"))
    monkeypatch.setenv("SUPPORT_ADMIN_PASSWORD", "test-admin-password")
    headers = {"Authorization": "Basic YWRtaW46dGVzdC1hZG1pbi1wYXNzd29yZA=="}

    with TestClient(app) as client:
        created = client.post(
            "/api/admin/teams",
            headers=headers,
            json={
                "name": "Payroll Support",
                "description": "Payroll and salary questions.",
                "contact_phone": "0900000000",
                "guidance": "Contact payroll.",
                "initial_example": "My salary payment is missing.",
            },
        )
        team_id = created.json()["team"]["id"]
        example_id = client.get("/api/admin/examples", headers=headers).json()[-1]["id"]

        disabled = client.patch(
            f"/api/admin/teams/{team_id}/enabled?enabled=false", headers=headers
        )
        assert disabled.status_code == 200
        assert disabled.json()["team"]["enabled"] == 0
        assert team_id not in {team["id"] for team in client.get("/api/teams").json()}

        edited = client.put(
            f"/api/admin/teams/{team_id}",
            headers=headers,
            json={
                "name": "Enat Payroll",
                "description": "Enat salary and payslip questions.",
                "contact_phone": "0911111111",
                "guidance": "Contact Enat payroll.",
            },
        )
        assert edited.status_code == 200
        assert edited.json()["team"]["contact_phone"] == "0911111111"

        enabled = client.patch(
            f"/api/admin/teams/{team_id}/enabled?enabled=true", headers=headers
        )
        assert enabled.status_code == 200
        assert team_id in {team["id"] for team in client.get("/api/teams").json()}

        deleted = client.delete(f"/api/admin/teams/{team_id}", headers=headers)
        remaining_ids = {
            team["id"]
            for team in client.get("/api/admin/teams", headers=headers).json()
        }
        examples = client.get("/api/admin/examples", headers=headers).json()

    assert deleted.status_code == 200
    assert team_id not in remaining_ids
    assert example_id not in {example["id"] for example in examples}
    with TestClient(app) as client:
        persisted_ids = {
            team["id"]
            for team in client.get("/api/admin/teams", headers=headers).json()
        }
    assert team_id not in persisted_ids


def test_admin_can_edit_delete_examples_and_protect_last_custom_example(
    tmp_path, monkeypatch
):
    monkeypatch.setenv("SUPPORT_ROUTER_DB", str(tmp_path / "example-controls.sqlite3"))
    monkeypatch.setenv("SUPPORT_ADMIN_PASSWORD", "test-admin-password")
    headers = {"Authorization": "Basic YWRtaW46dGVzdC1hZG1pbi1wYXNzd29yZA=="}

    with TestClient(app) as client:
        created = client.post(
            "/api/admin/teams",
            headers=headers,
            json={
                "name": "Payroll Support",
                "description": "Payroll and salary questions.",
                "contact_phone": "0900000000",
                "guidance": "Contact payroll.",
                "initial_example": "My salary payment is missing.",
            },
        )
        team_id = created.json()["team"]["id"]
        example_id = client.get("/api/admin/examples", headers=headers).json()[-1]["id"]
        changed = client.put(
            f"/api/admin/examples/{example_id}",
            headers=headers,
            json={
                "text": "My payslip and salary payment have not arrived.",
                "team_id": team_id,
            },
        )
        blocked_delete = client.delete(
            f"/api/admin/examples/{example_id}", headers=headers
        )

        client.post(
            "/api/admin/examples",
            headers=headers,
            json={
                "text": "I have a question about my payroll record.",
                "team_id": team_id,
            },
        )
        deleted = client.delete(
            f"/api/admin/examples/{example_id}", headers=headers
        )

    assert changed.status_code == 200
    assert changed.json()["example"]["text"] == "My payslip and salary payment have not arrived."
    assert blocked_delete.status_code == 409
    assert deleted.status_code == 200


def test_admin_cannot_disable_last_enabled_team(tmp_path, monkeypatch):
    monkeypatch.setenv("SUPPORT_ROUTER_DB", str(tmp_path / "last-team.sqlite3"))
    monkeypatch.setenv("SUPPORT_ADMIN_PASSWORD", "test-admin-password")
    headers = {"Authorization": "Basic YWRtaW46dGVzdC1hZG1pbi1wYXNzd29yZA=="}

    with TestClient(app) as client:
        teams = client.get("/api/admin/teams", headers=headers).json()
        for team in teams[1:]:
            response = client.patch(
                f"/api/admin/teams/{team['id']}/enabled?enabled=false",
                headers=headers,
            )
            assert response.status_code == 200
        last_team = teams[0]
        response = client.patch(
            f"/api/admin/teams/{last_team['id']}/enabled?enabled=false",
            headers=headers,
        )

    assert response.status_code == 409


def test_admin_page_is_available_but_admin_api_requires_password(tmp_path, monkeypatch):
    monkeypatch.setenv("SUPPORT_ROUTER_DB", str(tmp_path / "locked.sqlite3"))
    monkeypatch.delenv("SUPPORT_ADMIN_PASSWORD", raising=False)

    with TestClient(app) as client:
        assert client.get("/admin").status_code == 200
        admin_page = client.get("/admin").text
        assert "Add a support team" in admin_page
        assert "Delete team" in admin_page
        assert "Training examples" in admin_page
        assert 'class="workspace-sidebar"' in admin_page
        assert 'aria-label="Admin sections"' in admin_page
        assert "min(1800px, 100%)" in admin_page
        assert "grid-template-columns: 238px minmax(0, 1fr)" in admin_page
        assert 'class="breadcrumbs"' in admin_page
        assert "@media (min-width: 601px) and (max-width: 920px)" in admin_page
        assert "Human review" in admin_page
        assert 'autocomplete="new-password"' in admin_page
        assert 'id="session-card"' in admin_page
        assert 'id="logout-button"' in admin_page
        assert "expires after 8 hours" in admin_page
        response = client.get("/api/admin/teams")

    assert response.status_code == 503


def test_admin_session_survives_refresh_and_logout_revokes_it(tmp_path, monkeypatch):
    monkeypatch.setenv("SUPPORT_ROUTER_DB", str(tmp_path / "admin-session.sqlite3"))
    monkeypatch.setenv("SUPPORT_ADMIN_PASSWORD", "test-admin-password")
    headers = {"Authorization": "Basic YWRtaW46dGVzdC1hZG1pbi1wYXNzd29yZA=="}

    with TestClient(app) as client:
        assert client.get("/api/admin/session").json() == {"authenticated": False}
        login = client.post("/api/admin/session", headers=headers)
        assert login.status_code == 200
        assert login.json() == {"authenticated": True}
        cookie = client.cookies.get("support_admin_session")
        assert cookie
        assert client.get("/api/admin/session").json() == {"authenticated": True}
        assert client.get("/api/admin/teams").status_code == 200
        client.get("/admin")
        assert client.get("/api/admin/session").json() == {"authenticated": True}
        assert client.get("/api/admin/teams").status_code == 200
        logout = client.delete("/api/admin/session")
        assert logout.status_code == 200
        assert client.get("/api/admin/session").json() == {"authenticated": False}
        assert client.get("/api/admin/teams").status_code == 401


def test_routing_requests_persist_and_feedback_is_saved(tmp_path, monkeypatch):
    db_path = tmp_path / "persistent.sqlite3"
    monkeypatch.setenv("SUPPORT_ROUTER_DB", str(db_path))
    monkeypatch.setenv("SUPPORT_ADMIN_PASSWORD", "test-admin-password")
    headers = {"Authorization": "Basic YWRtaW46dGVzdC1hZG1pbi1wYXNzd29yZA=="}

    with TestClient(app) as client:
        routed = client.post(
            "/api/route",
            json={"text": "I transferred money but the recipient has not received it"},
        )
        assert routed.status_code == 200
        request_id = routed.json()["request_id"]
        feedback = client.post(
            f"/api/requests/{request_id}/feedback",
            json={"helpful": True},
        )
        assert feedback.status_code == 200
        requests = client.get("/api/requests").json()

    assert any(request["request_id"] == request_id for request in requests)

    with TestClient(app) as client:
        requests = client.get("/api/requests").json()
        assert any(
            request["request_id"] == request_id and request["helpful"] == 1
            for request in requests
        )
        queue = client.get("/api/admin/review", headers=headers).json()
        admin_requests = client.get("/api/admin/review", headers=headers).json()

    assert isinstance(queue, list)
    assert isinstance(admin_requests, list)


def test_admin_can_resolve_human_review_and_add_verified_example(tmp_path, monkeypatch):
    db_path = tmp_path / "review.sqlite3"
    monkeypatch.setenv("SUPPORT_ROUTER_DB", str(db_path))
    monkeypatch.setenv("SUPPORT_ADMIN_PASSWORD", "test-admin-password")
    headers = {"Authorization": "Basic YWRtaW46dGVzdC1hZG1pbi1wYXNzd29yZA=="}

    with TestClient(app) as client:
        routed = client.post(
            "/api/route",
            json={"text": "I need help with something"},
        )
        request_id = routed.json()["request_id"]
        assert routed.status_code == 200
        assert routed.json()["status"] == "human_review"

        resolved = client.post(
            f"/api/admin/review/{request_id}",
            headers=headers,
            json={
                "team_id": "payments",
                "reviewer_note": "Verified by a support specialist.",
                "add_training_example": True,
            },
        )
        assert resolved.status_code == 200
        queue = client.get("/api/admin/review", headers=headers).json()

    assert request_id not in {record["request_id"] for record in queue}


def test_pii_redaction_masks_email_phone_and_credentials():
    sanitized = redact_pii(
        "Contact jane.doe@example.com at +1 (202) 555-0199. Password: SecretToken123!"
    )

    assert "jane.doe@example.com" not in sanitized
    assert "202" not in sanitized
    assert "SecretToken123" not in sanitized
    assert "[REDACTED_EMAIL]" in sanitized
    assert "[REDACTED_CREDENTIAL]" in sanitized
    assert "password reset" in redact_pii("I need a password reset").lower()


def test_route_persists_redacted_text_only(tmp_path, monkeypatch):
    database = tmp_path / "private.sqlite3"
    monkeypatch.setenv("SUPPORT_ROUTER_DB", str(database))
    with TestClient(app) as client:
        response = client.post(
            "/api/route",
            json={
                "text": "My email is jane.doe@example.com and password is SecretToken123!"
            },
        )
        request_id = response.json()["request_id"]

    records = SupportRepository(database).get_routing_requests(admin_view=True)
    record = next(item for item in records if item["request_id"] == request_id)
    assert "jane.doe@example.com" not in record["text"]
    assert "SecretToken123" not in record["text"]


def test_authorized_held_out_evaluation_runs_on_sanitized_data(tmp_path, capsys):
    dataset = tmp_path / "authorized.csv"
    dataset.write_text(
        "text,team_id\n"
        "I cannot access my account after password reset,account_access\n"
        "Please help me log in to my account,account_access\n"
        "My account password is incorrect,account_access\n"
        "I forgot the password for my account,account_access\n"
        "The payment transfer is missing,payments\n"
        "My transfer has not arrived,payments\n"
        "A payment is still pending,payments\n"
        "I need help with a missing deposit,payments\n",
        encoding="utf-8",
    )

    evaluate_authorized_dataset(dataset, test_size=0.25)
    report = capsys.readouterr().out
    assert "held-out test" in report
    assert "Accuracy:" in report
    assert "Macro F1:" in report


def test_authorized_evaluation_rejects_conflicting_duplicate_labels(tmp_path):
    dataset = tmp_path / "conflicting.csv"
    dataset.write_text(
        "text,team_id\n"
        "Reset my Enat system password,account_access\n"
        "Reset my Enat system password,payments\n"
        "Help with account login,account_access\n"
        "Help with payment transfer,payments\n",
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="conflicting team labels"):
        evaluate_authorized_dataset(dataset, test_size=0.5)


def test_authorized_import_sanitizes_and_excludes_demo_examples(tmp_path):
    repository = SupportRepository(tmp_path / "imported.sqlite3")
    imported = repository.import_authorized_examples(
        [
            {
                "text": "My email is jane.doe@example.com and I need account access",
                "team_id": "account_access",
            },
            {
                "text": "Please reset my account password with my phone 0912121212",
                "team_id": "account_access",
            },
        ]
    )
    examples = repository.get_examples()

    assert imported == 2
    assert all(example["source"] != "demo" for example in examples)
    assert any("[REDACTED_EMAIL]" in example["text"] for example in examples)
    assert all("jane.doe@example.com" not in example["text"] for example in examples)
