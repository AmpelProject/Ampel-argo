from ampel.core.AmpelContext import AmpelContext
from fastapi import FastAPI, status
from fastapi.responses import JSONResponse
from fastapi.encoders import jsonable_encoder
from fastapi.exceptions import HTTPException
from functools import cache
from ampel.model.job.JobModel import JobModel
from pydantic import ValidationError

from .settings import settings
from .job import render_job

app = FastAPI(
    title="Argo job service",
    version="0.1.0",
    root_path=settings.root_path,
)


@cache
def get_context():
    return AmpelContext.load(
        config=settings.ampel_config,
        freeze_config=True,
    )


@app.post("/jobs/lint")
async def lint_job(job: JobModel):
    try:
        return render_job(get_context(), job)
    except ValidationError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=jsonable_encoder(exc.errors()),
        )
