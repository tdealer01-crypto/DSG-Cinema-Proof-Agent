from __future__ import annotations

from fastapi import APIRouter
from fastapi.responses import HTMLResponse, Response

router = APIRouter(tags=["remote-browser-smoke"])


@router.get("/remote-browser/smoke", response_class=HTMLResponse, include_in_schema=False)
def smoke_page() -> HTMLResponse:
    return HTMLResponse("""<!doctype html>
<html><head><meta charset="utf-8"><title>DSG Remote Browser Smoke</title></head>
<body>
<input id="message" aria-label="Smoke message" value="">
<button id="apply" type="button">Apply</button>
<button id="status" type="button" disabled>idle</button>
<input id="upload" aria-label="Smoke upload" type="file">
<button id="upload-status" type="button" disabled>no-file</button>
<a id="download" href="/remote-browser/smoke/download">Download smoke file</a>
<script>
const message=document.getElementById('message');
const apply=document.getElementById('apply');
const status=document.getElementById('status');
const upload=document.getElementById('upload');
const uploadStatus=document.getElementById('upload-status');
apply.onclick=()=>{status.textContent='applied:'+message.value};
upload.onchange=()=>{uploadStatus.textContent='uploaded:'+(upload.files[0]?.name||'none')};
</script>
</body></html>""", headers={"Cache-Control":"no-store"})


@router.get("/remote-browser/smoke/download", include_in_schema=False)
def smoke_download() -> Response:
    return Response(
        content=b"DSG remote browser download smoke fixture\n",
        media_type="text/plain",
        headers={
            "Content-Disposition": 'attachment; filename="dsg-remote-browser-smoke.txt"',
            "Cache-Control": "no-store",
        },
    )


def install(app) -> None:
    app.include_router(router)
