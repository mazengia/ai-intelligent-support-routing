from fastapi.testclient import TestClient
import pytest

from support_router.api import app
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


def test_api_serves_ui_and_routes_request(tmp_path, monkeypatch):
    monkeypatch.setenv("SUPPORT_ROUTER_DB", str(tmp_path / "test.sqlite3"))
    with TestClient(app) as client:
        assert client.get("/health").json() == {"status": "ok"}
        page = client.get("/")
        assert page.status_code == 200
        assert "Forgot password" in page.text
        assert "Never share your password" in page.text
        assert "Routing score:" not in page.text
        assert "Support team setup" in page.text
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


def test_admin_page_is_available_but_admin_api_requires_password(tmp_path, monkeypatch):
    monkeypatch.setenv("SUPPORT_ROUTER_DB", str(tmp_path / "locked.sqlite3"))
    monkeypatch.delenv("SUPPORT_ADMIN_PASSWORD", raising=False)

    with TestClient(app) as client:
        assert client.get("/admin").status_code == 200
        assert "Add a support team" in client.get("/admin").text
        response = client.get("/api/admin/teams")

    assert response.status_code == 503
