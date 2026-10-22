"""Public questionnaire, isolated from accounts even for signed-in visitors."""
from typing import Any

from fastapi import APIRouter, Query, Request, Response
from pydantic import UUID4, BaseModel, ConfigDict, Field, StrictBool, StrictStr

from api.services.guguta.survey import SurveyService, questionnaire
from open_notebook.auth.guguta.actor import ActorDenied

survey_router = APIRouter(prefix="/api/v1/survey", tags=["survey"])


class SurveySubmission(BaseModel):
    model_config = ConfigDict(extra="forbid")
    submission_id: UUID4
    token: str = Field(max_length=300)
    version: str = Field(max_length=64)
    acknowledged: StrictBool
    answers: dict[str, StrictStr | list[StrictStr]] = Field(min_length=20, max_length=20)


def service(request: Request) -> SurveyService:
    return request.app.state.guguta_survey


@survey_router.get("")
async def get_questionnaire() -> dict[str, Any]:
    return questionnaire()


@survey_router.get("/session")
async def start_survey(request: Request) -> dict[str, str]:
    return service(request).start()


@survey_router.post("/responses", status_code=201)
async def submit_survey(body: SurveySubmission, request: Request) -> dict[str, bool]:
    if (request.headers.get("origin") not in request.app.state.guguta_config.cors_origins
            or request.headers.get("x-guguta-survey") != "1"):
        raise ActorDenied("Trimite răspunsurile din pagina sondajului.")
    return await service(request).submit(body.submission_id, body.token, body.version, body.answers, body.acknowledged)


@survey_router.get("/results")
async def survey_results(request: Request) -> dict[str, Any]:
    return await service(request).results()


@survey_router.get("/comments")
async def survey_comments(request: Request, question: str = Query(pattern="^q(19|20)$"),
                          offset: int = Query(default=0, ge=0, le=1_000_000)) -> dict[str, Any]:
    comments = await service(request).comments(question, offset)
    return {"comments": comments, "offset": offset}


@survey_router.get("/export.csv")
async def export_survey(request: Request) -> Response:
    return Response(await service(request).export(), media_type="text/csv; charset=utf-8",
                    headers={"Content-Disposition": 'attachment; filename="guguta-sondaj-rezultate.csv"'})
