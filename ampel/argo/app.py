from ampel.core.AmpelContext import AmpelContext
from fastapi import Depends, FastAPI, status
from fastapi.encoders import jsonable_encoder
from fastapi.exceptions import HTTPException
from functools import cache
from pydantic import ValidationError

from .settings import settings
from .job import render_job, compact_json
from .auth import get_user, User
from .models import ArgoJobModel
from . import api

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    import httpx

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
async def lint_job(job: ArgoJobModel):
    """
    Check a job template for errors
    """
    try:
        return render_job(get_context(), job)
    except ValidationError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=jsonable_encoder(exc.errors()),
        )


@app.post("/jobs")
async def submit_job(job: ArgoJobModel, user: User = Depends(get_user)):
    """
    Submit a job template
    """
    try:
        template = render_job(get_context(), job)
    except ValidationError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=jsonable_encoder(exc.errors()),
        )
    settings = api.KubernetesSettings.get()
    async with api.api_client() as client:
        response = await client.post(
            f"api/v1/workflow-templates/{settings.namespace}",
            json={
                "template": {
                    "metadata": {
                        "name": job.name,
                        "labels": {
                            "ampelproject.github.io/creator": user.name,
                        },
                        "annotations": {
                            "ampelproject.github.io/job": compact_json(job.json()),
                        },
                    },
                    **template,
                }
            },
        )
    if response.status_code >= status.HTTP_400_BAD_REQUEST:
        raise HTTPException(status_code=response.status_code, detail=response.json())
    return response.json()

# If we are mounted under a (non-stripped) prefix path, create a potemkin root
# router and mount the actual root as a sub-application. This has no effect
# other than to prefix the paths of all routes with the root path.
if settings.root_path:
    wrapper = FastAPI()
    wrapper.mount(settings.root_path, app)
    app = wrapper