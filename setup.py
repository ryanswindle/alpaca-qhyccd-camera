from fastapi import APIRouter
from fastapi.responses import HTMLResponse

router = APIRouter(tags=["Setup"])


@router.get("/setup", response_class=HTMLResponse, summary="")
async def server_setup():
    return "<html><body><h2>Server setup is in config.yaml</h2></body></html>"


@router.get("/setup/v1/camera/{devnum}/setup", response_class=HTMLResponse, summary="")
async def device_setup(devnum: int):
    return "<html><body><h2>Device setup is in config.yaml</h2></body></html>"