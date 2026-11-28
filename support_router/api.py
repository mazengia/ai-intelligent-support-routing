from contextlib import asynccontextmanager
import hmac
import os
from pathlib import Path
import re
import time
from typing import Literal
from uuid import uuid4

from fastapi import Depends, FastAPI, HTTPException, Request, Response
from fastapi.security import HTTPBasic, HTTPBasicCredentials
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field

from .repository import SupportRepository
from .privacy import redact_pii
from .router import SupportRouter

security = HTTPBasic(auto_error=False)
DEFAULT_DATABASE = Path("support_router.sqlite3")
ADMIN_SESSION_COOKIE = "support_admin_session"
ADMIN_SESSION_MAX_AGE = 8 * 60 * 60


@asynccontextmanager
async def lifespan(app: FastAPI):
    app.state.repository = SupportRepository(
        Path(os.getenv("SUPPORT_ROUTER_DB", str(DEFAULT_DATABASE)))
    )
    app.state.router = SupportRouter(repository=app.state.repository)
    yield


app = FastAPI(
    title="Intelligent Support Routing",
    description="A research prototype for confidence-aware customer support routing.",
    version="0.1.0",
    lifespan=lifespan,
)


class RouteRequest(BaseModel):
    text: str = Field(min_length=1, max_length=5000)
    top_k: int = Field(default=3, ge=1, le=50)


class RouteResponse(BaseModel):
    request_id: str
    status: Literal["recommended", "human_review"]
    predicted_category: str
    recommended_team: dict[str, str] | None
    suggested_team: dict[str, str] | None
    candidates: list[dict[str, str | float]]
    confidence_score: float
    score_is_calibrated_probability: bool
    explanation: str
    next_step: str


class TeamUpdate(BaseModel):
    name: str = Field(min_length=1, max_length=100)
    description: str = Field(min_length=1, max_length=2000)
    contact_phone: str = Field(default="", max_length=50)
    guidance: str = Field(default="", max_length=2000)


class TeamCreate(TeamUpdate):
    initial_example: str = Field(min_length=5, max_length=2000)


class TrainingExampleUpdate(BaseModel):
    text: str = Field(min_length=5, max_length=2000)
    team_id: str


class TrainingExample(BaseModel):
    text: str = Field(min_length=5, max_length=2000)
    team_id: str


class RoutingFeedback(BaseModel):
    helpful: bool


class HumanReviewResolution(BaseModel):
    team_id: str
    reviewer_note: str = Field(default="", max_length=2000)
    add_training_example: bool = True


def _configured_admin_password() -> str:
    expected_password = os.getenv("SUPPORT_ADMIN_PASSWORD", "")
    if not expected_password:
        raise HTTPException(
            status_code=503,
            detail=(
                "Admin access is not configured. Set the SUPPORT_ADMIN_PASSWORD "
                "environment variable and restart the application."
            ),
        )
    return expected_password


def _valid_basic_credentials(
    credentials: HTTPBasicCredentials | None,
    expected_password: str,
) -> bool:
    valid_username = credentials is not None and hmac.compare_digest(
        credentials.username.encode("utf-8"), b"admin"
    )
    valid_password = credentials is not None and hmac.compare_digest(
        credentials.password.encode("utf-8"), expected_password.encode("utf-8")
    )
    return bool(valid_username and valid_password)


def _create_admin_session_token(expected_password: str) -> str:
    issued_at = str(int(time.time()))
    signature = hmac.new(
        expected_password.encode("utf-8"),
        f"support-admin-session:{issued_at}".encode("utf-8"),
        "sha256",
    ).hexdigest()
    return f"{issued_at}.{signature}"


def _valid_admin_session(token: str | None, expected_password: str) -> bool:
    if not token:
        return False
    try:
        issued_at_text, provided_signature = token.split(".", 1)
        issued_at = int(issued_at_text)
    except (ValueError, TypeError):
        return False
    now = int(time.time())
    if issued_at > now + 30 or now - issued_at > ADMIN_SESSION_MAX_AGE:
        return False
    expected_signature = hmac.new(
        expected_password.encode("utf-8"),
        f"support-admin-session:{issued_at_text}".encode("utf-8"),
        "sha256",
    ).hexdigest()
    return hmac.compare_digest(provided_signature, expected_signature)


def require_admin(
    request: Request,
    credentials: HTTPBasicCredentials | None = Depends(security),
) -> str:
    expected_password = _configured_admin_password()
    if _valid_admin_session(
        request.cookies.get(ADMIN_SESSION_COOKIE), expected_password
    ):
        return "admin"
    if not _valid_basic_credentials(credentials, expected_password):
        raise HTTPException(
            status_code=401,
            detail="Admin username or password is incorrect.",
            headers={"WWW-Authenticate": "Basic"},
        )
    return credentials.username


@app.get("/api/admin/session")
def admin_session_status(request: Request, response: Response):
    expected_password = os.getenv("SUPPORT_ADMIN_PASSWORD", "")
    response.headers["Cache-Control"] = "no-store"
    return {
        "authenticated": bool(expected_password)
        and _valid_admin_session(
            request.cookies.get(ADMIN_SESSION_COOKIE), expected_password
        )
    }


@app.post("/api/admin/session")
def create_admin_session(
    request: Request,
    response: Response,
    credentials: HTTPBasicCredentials | None = Depends(security),
):
    expected_password = _configured_admin_password()
    if not _valid_basic_credentials(credentials, expected_password):
        raise HTTPException(
            status_code=401,
            detail="Admin username or password is incorrect.",
            headers={"WWW-Authenticate": "Basic"},
        )
    response.set_cookie(
        ADMIN_SESSION_COOKIE,
        _create_admin_session_token(expected_password),
        max_age=ADMIN_SESSION_MAX_AGE,
        httponly=True,
        secure=request.url.scheme == "https",
        samesite="strict",
        path="/api/admin",
    )
    response.headers["Cache-Control"] = "no-store"
    return {"authenticated": True}


@app.delete("/api/admin/session")
def delete_admin_session(request: Request, response: Response):
    response.delete_cookie(
        ADMIN_SESSION_COOKIE,
        httponly=True,
        secure=request.url.scheme == "https",
        samesite="strict",
        path="/api/admin",
    )
    return {"authenticated": False}


@app.get("/", include_in_schema=False)
def home():
    return FileResponse(Path(__file__).parent / "static" / "index.html")


@app.get("/admin", include_in_schema=False)
def admin():
    return FileResponse(Path(__file__).parent / "static" / "admin.html")


@app.get("/health")
def health():
    return {"status": "ok"}


@app.get("/api/teams")
def list_teams():
    return app.state.repository.get_teams(enabled_only=True)


@app.get("/api/admin/teams", dependencies=[Depends(require_admin)])
def list_admin_teams():
    return app.state.repository.get_teams()


@app.post("/api/admin/teams", dependencies=[Depends(require_admin)], status_code=201)
def create_admin_team(payload: TeamCreate):
    name = payload.name.strip()
    description = payload.description.strip()
    initial_example = redact_pii(payload.initial_example).strip()
    if not name or not description or len(initial_example) < 5:
        raise HTTPException(
            status_code=422,
            detail="Enter a team name, description, and a meaningful example request.",
        )
    team_id = re.sub(r"[^a-z0-9]+", "_", name.lower()).strip("_")
    if not team_id:
        raise HTTPException(
            status_code=422,
            detail="The team name must contain at least one English letter or number.",
        )
    try:
        team = app.state.repository.create_team(
            team_id=team_id,
            name=name,
            description=description,
            contact_phone=payload.contact_phone.strip(),
            guidance=payload.guidance.strip(),
            initial_example=initial_example,
        )
        app.state.router = SupportRouter(repository=app.state.repository)
    except ValueError as error:
        raise HTTPException(status_code=409, detail=str(error)) from error
    return {
        "team": team,
        "message": "Support team created. The initial example was saved and the model was retrained.",
        "training_example_count": app.state.repository.count_examples(),
    }


@app.patch("/api/admin/teams/{team_id}/enabled", dependencies=[Depends(require_admin)])
def set_admin_team_enabled(team_id: str, enabled: bool):
    try:
        team = app.state.repository.set_team_enabled(team_id, enabled)
        if team is None:
            raise HTTPException(status_code=404, detail="Support team was not found.")
        app.state.router = SupportRouter(repository=app.state.repository)
    except ValueError as error:
        raise HTTPException(status_code=409, detail=str(error)) from error
    return {
        "team": team,
        "message": f"Support team {'enabled' if enabled else 'disabled'}.",
    }


@app.delete("/api/admin/teams/{team_id}", dependencies=[Depends(require_admin)])
def delete_admin_team(team_id: str):
    if not app.state.repository.delete_team(team_id):
        raise HTTPException(status_code=404, detail="Support team was not found.")
    app.state.router = SupportRouter(repository=app.state.repository)
    return {"message": "Support team and its saved training examples were deleted."}


@app.get("/api/admin/examples", dependencies=[Depends(require_admin)])
def list_admin_examples():
    return app.state.repository.get_examples()


@app.put(
    "/api/admin/examples/{example_id}", dependencies=[Depends(require_admin)]
)
def update_admin_example(example_id: int, payload: TrainingExampleUpdate):
    text = redact_pii(payload.text).strip()
    if len(text) < 5:
        raise HTTPException(
            status_code=422, detail="Please enter a longer example request."
        )
    try:
        example = app.state.repository.update_example(
            example_id, text, payload.team_id
        )
        if example is None:
            raise HTTPException(status_code=404, detail="Training example was not found.")
        app.state.router = SupportRouter(repository=app.state.repository)
    except ValueError as error:
        raise HTTPException(status_code=409, detail=str(error)) from error
    return {
        "example": example,
        "message": "Training example updated and the model was retrained.",
    }


@app.delete(
    "/api/admin/examples/{example_id}", dependencies=[Depends(require_admin)]
)
def delete_admin_example(example_id: int):
    try:
        deleted = app.state.repository.delete_example(example_id)
        if not deleted:
            raise HTTPException(status_code=404, detail="Training example was not found.")
        app.state.router = SupportRouter(repository=app.state.repository)
    except ValueError as error:
        raise HTTPException(status_code=409, detail=str(error)) from error
    return {
        "message": "Training example deleted and the model was retrained.",
        "training_example_count": app.state.repository.count_examples(),
    }


@app.put("/api/admin/teams/{team_id}", dependencies=[Depends(require_admin)])
def update_admin_team(team_id: str, payload: TeamUpdate):
    name = payload.name.strip()
    description = payload.description.strip()
    if not name or not description:
        raise HTTPException(
            status_code=422, detail="Team name and description cannot be blank."
        )
    team = app.state.repository.update_team(
        team_id=team_id,
        name=name,
        description=description,
        contact_phone=payload.contact_phone.strip(),
        guidance=payload.guidance.strip(),
    )
    if team is None:
        raise HTTPException(status_code=404, detail="Support team was not found.")
    app.state.router = SupportRouter(repository=app.state.repository)
    return {"team": team, "message": "Support details saved."}


@app.post("/api/admin/examples", dependencies=[Depends(require_admin)])
def add_training_example(payload: TrainingExample):
    text = redact_pii(payload.text).strip()
    if len(text) < 5:
        raise HTTPException(
            status_code=422, detail="Please enter a longer example request."
        )
    try:
        example = app.state.repository.add_example(text, payload.team_id)
        app.state.router = SupportRouter(repository=app.state.repository)
    except ValueError as error:
        raise HTTPException(status_code=422, detail=str(error)) from error
    return {
        "example": example,
        "training_example_count": app.state.repository.count_examples(),
        "message": "Example saved and the routing model was retrained.",
    }


@app.post("/api/route", response_model=RouteResponse)
def route_request(payload: RouteRequest):
    text = redact_pii(payload.text).strip()
    if not text:
        raise HTTPException(status_code=422, detail="Request text cannot be blank.")
    try:
        result = app.state.router.recommend(text, top_k=payload.top_k)
    except ValueError as error:
        raise HTTPException(status_code=422, detail=str(error)) from error

    request_id = str(uuid4())
    app.state.repository.save_routing_request(request_id, text, result)
    return {"request_id": request_id, **result}


@app.get("/api/requests")
def list_requests():
    return app.state.repository.get_routing_requests()


@app.post("/api/requests/{request_id}/feedback")
def submit_routing_feedback(request_id: str, payload: RoutingFeedback):
    if not app.state.repository.set_routing_feedback(request_id, payload.helpful):
        raise HTTPException(status_code=404, detail="Routing request was not found.")
    return {"message": "Feedback saved."}


@app.get(
    "/api/admin/review",
    dependencies=[Depends(require_admin)],
)
def list_human_review_queue():
    return app.state.repository.get_human_review_queue()


@app.post(
    "/api/admin/review/{request_id}",
    dependencies=[Depends(require_admin)],
)
def resolve_human_review(request_id: str, payload: HumanReviewResolution):
    try:
        resolved = app.state.repository.resolve_routing_request(
            request_id=request_id,
            team_id=payload.team_id,
            reviewer_note=payload.reviewer_note,
            add_training_example=payload.add_training_example,
        )
    except ValueError as error:
        raise HTTPException(status_code=422, detail=str(error)) from error
    if resolved is None:
        raise HTTPException(status_code=404, detail="Routing request was not found.")
    if payload.add_training_example:
        app.state.router = SupportRouter(repository=app.state.repository)
    return {
        **resolved,
        "message": "Human review saved.",
    }
