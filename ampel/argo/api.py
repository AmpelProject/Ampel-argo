# interact with the argo API

import httpx
from contextlib import asynccontextmanager
from functools import cache
from pydantic import BaseSettings, Field

from typing import AsyncIterator


class KubernetesSettings(BaseSettings):
    serviceaccount: str = Field(..., env="SERVICE_ACCOUNT_TOKEN")
    base_url: str = Field(..., env="ARGO_BASE_URL")
    namespace: str = Field("ampel", env="ARGO_NAMESPACE")

    verify_ssl: bool = Field(True, env="VERIFY_SSL")

    @classmethod
    @cache
    def get(cls) -> "KubernetesSettings":
        kwargs = {}
        try:
            with open("/var/run/secrets/kubernetes.io/serviceaccount/token") as f:
                kwargs["serviceaccount"] = f.read()
        except FileNotFoundError:
            pass
        return cls(**kwargs)


@asynccontextmanager
async def api_client() -> AsyncIterator[httpx.AsyncClient]:
    settings = KubernetesSettings.get()
    async with httpx.AsyncClient(base_url=settings.base_url, verify=settings.verify_ssl) as client:
        client.headers.update({"Authorization": f"Bearer {settings.serviceaccount}"})
        yield client


async def post_manifest(manifest: dict):
    settings = KubernetesSettings.get()
    async with api_client() as client:
        response = await client.post(
            f"api/v1/workflow-templates/{settings.namespace}", json=manifest
        )
        
        response.raise_for_status()
