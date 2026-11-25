from contextlib import asynccontextmanager
import hmac
import os
from pathlib import Path
import re
from typing import Literal
from uuid import uuid4

from fastapi import Depends, FastAPI, HTTPException
from fastapi.security import HTTPBasic, HTTPBasicCredentials
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field

from .catalog import TEAMS
from .repository import SupportRepository
from .router import SupportRouter

security = HTTPBasic(auto_error=False)
DEFAULT_DATABASE = Path("support_router.sqlite3")


@asynccontextmanager
async def lifespan(app: FastAPI):
    app.state.repository = SupportRepository(
        Path(os.getenv("SUPPORT_ROUTER_DB", str(DEFAULT_DATABASE)))
    )
    app.state.router = SupportRouter(repository=app.state.repository)
    app.state.requests = []
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
    suggested_team: dict[str, str]
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


class TrainingExample(BaseModel):
    text: str = Field(min_length=5, max_length=2000)
    team_id: str


def require_admin(
    credentials: HTTPBasicCredentials | None = Depends(security),
) -> str:
    expected_password = os.getenv("SUPPORT_ADMIN_PASSWORD", "")
    if not expected_password:
        raise HTTPException(
            status_code=503,
            detail=(
                "Admin access is not configured. Set the SUPPORT_ADMIN_PASSWORD "
                "environment variable and restart the application."
            ),
        )
    valid_username = credentials is not None and hmac.compare_digest(
        credentials.username.encode("utf-8"), b"admin"
    )
    valid_password = credentials is not None and hmac.compare_digest(
        credentials.password.encode("utf-8"), expected_password.encode("utf-8")
    )
    if not (valid_username and valid_password):
        raise HTTPException(
            status_code=401,
            detail="Admin username or password is incorrect.",
            headers={"WWW-Authenticate": "Basic"},
        )
    return credentials.username


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
    return app.state.repository.get_teams()


@app.get("/api/admin/teams", dependencies=[Depends(require_admin)])
def list_admin_teams():
    return app.state.repository.get_teams()


@app.post("/api/admin/teams", dependencies=[Depends(require_admin)], status_code=201)
def create_admin_team(payload: TeamCreate):
    name = payload.name.strip()
    description = payload.description.strip()
    initial_example = payload.initial_example.strip()
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


@app.put("/api/admin/teams/{team_id}", dependencies=[Depends(require_admin)])
def update_admin_team(team_id: str, payload: TeamUpdate):
    team = app.state.repository.update_team(
        team_id=team_id,
        name=payload.name.strip(),
        description=payload.description.strip(),
        contact_phone=payload.contact_phone.strip(),
        guidance=payload.guidance.strip(),
    )
    if team is None:
        raise HTTPException(status_code=404, detail="Support team was not found.")
    app.state.router = SupportRouter(repository=app.state.repository)
    return {"team": team, "message": "Support details saved."}


@app.post("/api/admin/examples", dependencies=[Depends(require_admin)])
def add_training_example(payload: TrainingExample):
    text = payload.text.strip()
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
    text = payload.text.strip()
    if not text:
        raise HTTPException(status_code=422, detail="Request text cannot be blank.")
    try:
        result = app.state.router.recommend(text, top_k=payload.top_k)
    except ValueError as error:
        raise HTTPException(status_code=422, detail=str(error)) from error

    request_id = str(uuid4())
    record = {
        "request_id": request_id,
        "text": text,
        **result,
    }
    app.state.requests.append(record)
    return {"request_id": request_id, **result}


@app.get("/api/requests")
def list_requests():
    return [
        {
            "request_id": record["request_id"],
            "status": record["status"],
            "predicted_category": record["predicted_category"],
            "recommended_team": record["recommended_team"],
        }
        for record in reversed(app.state.requests)
    ]
