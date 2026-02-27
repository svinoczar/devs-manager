from datetime import datetime
from http import HTTPStatus
from fastapi import FastAPI, HTTPException, Header
from fastapi.params import Depends
from fastapi.responses import JSONResponse
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
import logging

from src.api.routes import auth, org, project, team, stats, sync
from src.services.internal.process import process_repo
from src.adapters.db.base import SessionLocal
from src.adapters.db.repositories.repository_repo import RepositoryRepository
from src.core.config import settings


logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


app = FastAPI(title=settings.app_name, debug=settings.debug)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# region models

app.include_router(auth.router)
app.include_router(org.router)
app.include_router(project.router)
app.include_router(team.router)
app.include_router(stats.router)
app.include_router(sync.router)


class RepoRequest(BaseModel):
    owner: str
    repo: str
    since: datetime | None = None
    max_commits: int | None = None


class UpdateCommitsRequest(BaseModel):
    repository_id: int
    limit: int = 100
    since: datetime | None = None
    max_commits: int | None = None


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


# endregion


@app.get("/")
def root():
    return {"message": "Welcome to Devs Manager API"}


@app.get("/healthcheck")
def api_process_repo():
    return {"status": "Alive"}


# region repo


@app.post("/repo/init")
def api_process_repo(
    req: RepoRequest,
    github_token: str = Header(None, alias="ght"),
    scope: str = Header(None, alias="acc-scope"),  # username:id
    settings: str = Header(None, alias="analysis-settings"),
):
    if not github_token:
        raise HTTPException(status_code=400, detail="GitHub token header missing")
    try:
        scope_type, scope_id = scope.split(":")
        process_repo_response = process_repo(
            req.owner,
            req.repo,
            token=github_token,
            scope_type=scope_type,
            scope_id=scope_id,
            settings=settings,
            since=req.since,
            max_commits=req.max_commits,
        )

        response = {"status": "success"}
        response["code"] = HTTPStatus.OK
        # if int(process_repo_response["new-commits"]) == 0:
        #     print(process_repo_response["new-commits"])
        #     response["code"] = HTTPStatus.NO_CONTENT
        # else:
        #     print(process_repo_response["new-commits"])
        #     response["code"] = HTTPStatus.OK

        return JSONResponse(content=response | process_repo_response)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# endregion


# region settings
@app.get("/settings/")
def api_process_repo(
    github_token: str = Header(None, alias="ght"),
    scope: str = Header(None, alias="acc-scope"),  # username:id
):
    if not github_token:
        raise HTTPException(status_code=400, detail="GitHub token header missing")
    try:
        scope_type, scope_id = scope.split(":")
        process_repo_response = process_repo(
            req.owner,
            req.repo,
            token=github_token,
            scope_type=scope_type,
            scope_id=scope_id,
            settings=settings,
            since=req.since,
            max_commits=req.max_commits,
        )

        response = {"status": "success"}
        response["code"] = HTTPStatus.OK
        # if int(process_repo_response["new-commits"]) == 0:
        #     print(process_repo_response["new-commits"])
        #     response["code"] = HTTPStatus.NO_CONTENT
        # else:
        #     print(process_repo_response["new-commits"])
        #     response["code"] = HTTPStatus.OK

        return JSONResponse(content=response | process_repo_response)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# endregion


# region org
@app.post("/org/add")
def api_process_repo(
    github_token: str = Header(None, alias="ght"),
    scope: str = Header(None, alias="acc-scope"),
):
    if not github_token:
        raise HTTPException(status_code=400, detail="GitHub token header missing")
    try:
        scope_type, scope_id = scope.split(":")
        process_repo_response = process_repo(
            req.owner,
            req.repo,
            token=github_token,
            scope_type=scope_type,
            scope_id=scope_id,
            settings=settings,
            since=req.since,
            max_commits=req.max_commits,
        )

        response = {"status": "success"}
        response["code"] = HTTPStatus.OK
        # if int(process_repo_response["new-commits"]) == 0:
        #     print(process_repo_response["new-commits"])
        #     response["code"] = HTTPStatus.NO_CONTENT
        # else:
        #     print(process_repo_response["new-commits"])
        #     response["code"] = HTTPStatus.OK

        return JSONResponse(content=response | process_repo_response)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# endregion


# @app.post("/commits/update")
# def api_update_commits(
#     req: UpdateCommitsRequest,
#     db: Session = Depends(get_db),
#     github_token: str = Header(None, alias='ght')
#     ):
#     try:
#         count = update_commits(
#             db=db,
#             repository_id=req.repository_id,
#             token=github_token,
#             limit=req.limit,
#             since=req.since
#             )
#         return {
#             "status": "success",
#             "updated_commits": count
#         }
#     except Exception as e:
#         raise HTTPException(status_code=500, detail=str(e))


# @app.get("/repos")
# def list_repos():
#     with SessionLocal() as session:
#         repo_repo = RepositoryRepository(session)
#         repos = session.query(
#             repo_repo.db.query(
#                 repo_repo.db.query(repo_repo.db._decl_class_registry.values()).first()
#             )
#         ).all()
#         # проще пока просто отдавать owner+name
#         return [{"id": r.id, "owner": r.owner, "name": r.name} for r in repos]
