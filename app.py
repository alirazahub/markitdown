from __future__ import annotations

import http.client
import ipaddress
import mimetypes
import socket
import ssl
from email.message import Message
from io import BytesIO
from pathlib import Path
from urllib.parse import unquote, urljoin, urlsplit

from fastapi import FastAPI, File, HTTPException, UploadFile
from fastapi.responses import HTMLResponse, Response
from markitdown import MarkItDown
from pydantic import BaseModel, Field

app = FastAPI(title="MarkItDown Web", docs_url=None, redoc_url=None)
MAX_UPLOAD_BYTES = 4 * 1024 * 1024
_converter = MarkItDown(enable_plugins=False)


@app.get("/", response_class=HTMLResponse)
async def home() -> str:
    return PAGE


class URLRequest(BaseModel):
    url: str = Field(min_length=8, max_length=2048)


class PinnedHTTPSConnection(http.client.HTTPSConnection):
    """HTTPS connection pinned to a validated public IP to prevent DNS rebinding."""

    def __init__(self, hostname: str, ip: str) -> None:
        super().__init__(hostname, port=443, timeout=12, context=ssl.create_default_context())
        self.pinned_ip = ip

    def connect(self) -> None:
        raw_socket = socket.create_connection((self.pinned_ip, self.port), timeout=self.timeout)
        self.sock = self._context.wrap_socket(raw_socket, server_hostname=self.host)


def _validated_url_target(url: str) -> tuple[str, str, str]:
    if any(ord(char) < 32 for char in url):
        raise HTTPException(status_code=400, detail="The URL contains invalid characters.")
    try:
        parsed = urlsplit(url)
        port = parsed.port
    except ValueError as exc:
        raise HTTPException(status_code=400, detail="Please enter a valid HTTPS file URL.") from exc

    if parsed.scheme.lower() != "https" or not parsed.hostname:
        raise HTTPException(status_code=400, detail="Only public HTTPS file URLs are supported.")
    if parsed.username is not None or parsed.password is not None:
        raise HTTPException(status_code=400, detail="URLs with embedded credentials are not supported.")
    if port not in (None, 443):
        raise HTTPException(status_code=400, detail="Only standard HTTPS links on port 443 are supported.")

    hostname = parsed.hostname.rstrip(".").encode("idna").decode("ascii").lower()
    if not hostname or hostname == "localhost" or hostname.endswith((".localhost", ".local", ".internal")):
        raise HTTPException(status_code=400, detail="The URL must point to a public internet host.")

    try:
        literal_ip = ipaddress.ip_address(hostname)
        addresses = [literal_ip]
    except ValueError:
        try:
            records = socket.getaddrinfo(hostname, 443, type=socket.SOCK_STREAM)
            addresses = list({ipaddress.ip_address(record[4][0]) for record in records})
        except (OSError, ValueError) as exc:
            raise HTTPException(status_code=400, detail="The URL host could not be resolved.") from exc

    if not addresses or any(not address.is_global for address in addresses):
        raise HTTPException(status_code=400, detail="The URL must resolve only to public internet addresses.")

    request_path = parsed.path or "/"
    if parsed.query:
        request_path += "?" + parsed.query
    return hostname, str(addresses[0]), request_path


def _fetch_public_file(url: str) -> tuple[bytes, str]:
    current_url = url.strip()
    for redirect_count in range(4):
        hostname, pinned_ip, request_path = _validated_url_target(current_url)
        try:
            connection = PinnedHTTPSConnection(hostname, pinned_ip)
            host_header = f"[{hostname}]" if ":" in hostname else hostname
            connection.request(
                "GET",
                request_path,
                headers={
                    "Host": host_header,
                    "User-Agent": "MarkItDown-URL-Import/1.0",
                    "Accept": "*/*",
                    "Accept-Encoding": "identity",
                    "Connection": "close",
                },
            )
            response = connection.getresponse()
            if response.status in (301, 302, 303, 307, 308):
                location = response.getheader("Location")
                connection.close()
                if not location or redirect_count == 3:
                    raise HTTPException(status_code=422, detail="The file link redirected too many times.")
                current_url = urljoin(current_url, location)
                continue
            if response.status != 200:
                connection.close()
                raise HTTPException(status_code=422, detail=f"The file server returned HTTP {response.status}.")
            length = response.getheader("Content-Length")
            if length and int(length) > MAX_UPLOAD_BYTES:
                connection.close()
                raise HTTPException(status_code=413, detail="Please use a file smaller than 4 MB.")
            data = response.read(MAX_UPLOAD_BYTES + 1)
            headers = response.headers
            connection.close()
        except HTTPException:
            raise
        except (OSError, ssl.SSLError, http.client.HTTPException, TimeoutError) as exc:
            raise HTTPException(status_code=422, detail="The file could not be fetched from that URL.") from exc

        if not data:
            raise HTTPException(status_code=422, detail="The linked file is empty.")
        if len(data) > MAX_UPLOAD_BYTES:
            raise HTTPException(status_code=413, detail="Please use a file smaller than 4 MB.")

        filename = ""
        disposition = headers.get("Content-Disposition")
        if disposition:
            message = Message()
            message["content-disposition"] = disposition
            filename = message.get_filename() or ""
        if not filename:
            filename = unquote(urlsplit(current_url).path).replace("\\", "/").rsplit("/", 1)[-1]
        filename = Path(filename).name
        if not Path(filename).suffix:
            media_type = headers.get_content_type()
            filename += mimetypes.guess_extension(media_type) or ""
        if not Path(filename).suffix:
            raise HTTPException(status_code=422, detail="The file type could not be identified from the link.")
        return data, filename

    raise HTTPException(status_code=422, detail="The file link could not be followed.")


def _convert_bytes(data: bytes, filename: str) -> Response:
    try:
        result = _converter.convert_stream(BytesIO(data), file_extension=Path(filename).suffix.lower())
    except Exception as exc:
        raise HTTPException(
            status_code=422,
            detail="This file could not be converted. Check that its format is supported and the file is valid.",
        ) from exc
    return Response(
        content=result.markdown,
        media_type="text/markdown; charset=utf-8",
        headers={"Content-Disposition": 'inline; filename="converted.md"'},
    )


@app.post("/api/convert")
async def convert(file: UploadFile = File(...)) -> Response:
    filename = Path(file.filename or "upload").name
    data = await file.read(MAX_UPLOAD_BYTES + 1)
    if not data:
        raise HTTPException(status_code=400, detail="The uploaded file is empty.")
    if len(data) > MAX_UPLOAD_BYTES:
        raise HTTPException(status_code=413, detail="Please upload a file smaller than 4 MB.")
    return _convert_bytes(data, filename)


@app.post("/api/convert-url")
def convert_url(payload: URLRequest) -> Response:
    data, filename = _fetch_public_file(payload.url)
    return _convert_bytes(data, filename)


PAGE = r'''<!doctype html>
<html lang="en"><head>
<meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<meta name="theme-color" content="#f7f6f2"><title>MarkItDown by Ali Raza</title>
<style>
:root{font-family:Inter,ui-sans-serif,system-ui,-apple-system,BlinkMacSystemFont,"Segoe UI",sans-serif;color:#17221e;background:#f7f6f2}
*{box-sizing:border-box}body{margin:0;min-height:100vh;background:radial-gradient(ellipse at 50% -20%,#dceee4 0,transparent 52%),#f7f6f2}
header{height:76px;border-bottom:1px solid #e7e8e1;display:flex;align-items:center;justify-content:space-between;padding:0 max(24px,calc((100vw - 1120px)/2))}
.brand{display:flex;gap:11px;align-items:center;font-weight:750;letter-spacing:-.03em;color:inherit;text-decoration:none}.brand-copy{display:flex;flex-direction:column;gap:3px;line-height:1.1}.brand-copy strong{font-size:16px}.brand-copy a{color:#597064;font-size:11px;font-weight:550;letter-spacing:0;text-decoration:none}.brand-copy a:hover{text-decoration:underline}.mark{display:grid;place-items:center;width:38px;height:38px;border-radius:12px;background:#153f32;color:white;box-shadow:0 3px 9px #153f3226}.mark svg{display:block;width:25px;height:25px}
.badge{font-size:12px;color:#597064;border:1px solid #dce4dc;border-radius:999px;padding:7px 11px;background:#ffffff80}
main{width:min(100% - 40px,840px);margin:76px auto 64px}.eyebrow{color:#267354;font-size:12px;font-weight:750;letter-spacing:.14em;text-transform:uppercase;text-align:center}
h1{text-align:center;font-size:clamp(38px,6vw,62px);letter-spacing:-.065em;line-height:1.04;margin:17px 0 15px}.sub{text-align:center;color:#65736c;line-height:1.65;font-size:16px;margin:0 auto 38px;max-width:590px}
.card{background:#fff;border:1px solid #e7e8e1;border-radius:22px;box-shadow:0 18px 55px #273d3010;padding:20px}
.drop{min-height:230px;border:1.5px dashed #cbd8cd;border-radius:15px;display:flex;flex-direction:column;align-items:center;justify-content:center;text-align:center;padding:22px;transition:.18s;background:#fbfcfa}
.drop.drag{border-color:#267354;background:#f1f8f3}.upload-icon{width:46px;height:46px;border-radius:15px;background:#e8f3eb;display:grid;place-items:center;color:#267354;font-size:22px;margin-bottom:13px}
.drop strong{font-size:16px}.drop p{margin:7px 0 16px;color:#7a857f;font-size:13px}.choose{border:0;background:#173f32;color:#fff;border-radius:9px;padding:10px 15px;font-weight:650;cursor:pointer}.choose:hover,.action.primary:hover{background:#205741}
input[type=file]{display:none}.url-import{margin-top:18px;padding-top:17px;border-top:1px solid #edf0ec}.url-import label{display:block;color:#35483e;font-size:13px;font-weight:650;margin-bottom:8px}.url-row{display:flex;gap:8px}.url-input{flex:1;min-width:0;border:1px solid #dfe6df;border-radius:9px;padding:11px 12px;color:#26382e;font:inherit;font-size:13px}.url-input:focus{outline:2px solid #b8d8c1;border-color:#267354}.url-button{border:0;background:#173f32;color:#fff;border-radius:9px;padding:0 14px;font-weight:650;cursor:pointer}.url-button:hover{background:#205741}.url-help{margin:8px 0 0;color:#89938d;font-size:11px}.formats{text-align:center;color:#89938d;font-size:12px;margin:16px 0 0}.selected{margin-top:14px;color:#53655b;font-size:13px;min-height:18px}
.result{display:none;margin-top:18px}.result-top{display:flex;align-items:center;justify-content:space-between;margin-bottom:10px}.result-top strong{font-size:14px}.actions{display:flex;gap:8px}.action{border:1px solid #e0e5df;background:white;border-radius:8px;padding:8px 11px;font-weight:600;font-size:12px;color:#35483e;cursor:pointer}.action.primary{background:#173f32;color:#fff;border-color:#173f32}
pre{margin:0;max-height:420px;overflow:auto;background:#f8faf8;border:1px solid #e9ede8;border-radius:12px;padding:16px;white-space:pre-wrap;overflow-wrap:anywhere;color:#34463c;font:13px/1.65 ui-monospace,SFMono-Regular,Consolas,monospace}
.notice{display:none;margin-top:14px;border-radius:10px;padding:11px 13px;font-size:13px}.notice.error{display:block;background:#fff3f0;color:#a43c28}.notice.ok{display:block;background:#edf7ef;color:#286141}
.privacy{display:flex;justify-content:center;align-items:center;gap:7px;color:#758078;font-size:12px;margin:19px 0 0}.dot{width:7px;height:7px;border-radius:50%;background:#50a06e}
footer{text-align:center;color:#919a94;font-size:12px;margin-top:30px}footer a{color:#526d5d;text-decoration:none}
@media(max-width:560px){header{height:64px}.badge{font-size:11px}main{margin-top:52px}.card{padding:12px}.drop{min-height:210px}.url-row{flex-direction:column}.url-button{padding:11px}.result-top{align-items:flex-start;gap:8px;flex-direction:column}}
</style></head><body>
<header><div class="brand"><span class="mark" aria-hidden="true"><svg viewBox="0 0 36 36" fill="none" xmlns="http://www.w3.org/2000/svg"><path d="M10 6.75h10l6 6V29.25H10V6.75Z" stroke="white" stroke-width="1.8" stroke-linejoin="round"/><path d="M20 7v6h6M18 16.5v8m-3.5-3.5L18 24.5l3.5-3.5" stroke="white" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"/></svg></span><span class="brand-copy"><strong>MarkItDown</strong><a href="https://aliraza.fr" target="_blank" rel="noreferrer">by Ali Raza</a></span></div><span class="badge">Runs on Microsoft MarkItDown</span></header>
<main><div class="eyebrow">Document converter</div><h1>Turn files into<br>clean Markdown.</h1>
<p class="sub">Drop in a document and get Markdown you can copy, download, or use in your next project.</p>
<section class="card">
<div class="drop" id="drop"><div class="upload-icon">+</div><strong>Drag a file here to get started</strong>
<p>or choose a file from your device</p><button class="choose" id="choose" type="button">Choose file</button>
<input id="file" type="file" accept=".pdf,.docx,.pptx,.xlsx,.xls,.html,.htm,.csv,.json,.xml,.txt,.md,.epub,.zip,.jpg,.jpeg,.png,.gif,.bmp,.tif,.tiff,.wav,.mp3">
<div class="selected" id="selected"></div></div>
<form class="url-import" id="url-form"><label for="url-input">Or convert from a public file URL</label><div class="url-row"><input class="url-input" id="url-input" type="url" placeholder="https://example.com/document.pdf" autocomplete="url" required><button class="url-button" id="url-submit" type="submit">Convert URL</button></div><p class="url-help">Direct HTTPS file links only. Maximum file size: 4 MB.</p></form>
<div class="formats">PDF | Word | PowerPoint | Excel | HTML | CSV | JSON | images | audio | and more</div>
<div class="notice" id="notice" role="status"></div>
<div class="result" id="result"><div class="result-top"><strong>Markdown output</strong><div class="actions"><button class="action" id="copy" type="button">Copy</button><button class="action primary" id="download" type="button">Download .md</button></div></div><pre id="output"></pre></div>
</section><div class="privacy"><span class="dot"></span> Files are processed for conversion and not saved by this app | 4 MB max</div>
<footer>MarkItDown by <a href="https://aliraza.fr" target="_blank" rel="noreferrer">Ali Raza · aliraza.fr</a> | Powered by <a href="https://github.com/microsoft/markitdown" target="_blank" rel="noreferrer">Microsoft MarkItDown</a></footer></main>
<script>
const fileInput=document.querySelector("#file"),drop=document.querySelector("#drop"),selected=document.querySelector("#selected"),notice=document.querySelector("#notice"),result=document.querySelector("#result"),output=document.querySelector("#output");let converted="";
const urlForm=document.querySelector("#url-form"),urlInput=document.querySelector("#url-input"),urlSubmit=document.querySelector("#url-submit");
document.querySelector("#choose").addEventListener("click",()=>fileInput.click());fileInput.addEventListener("change",()=>fileInput.files[0]&&convert(fileInput.files[0]));
urlForm.addEventListener("submit",event=>{event.preventDefault();if(urlInput.value.trim())convertUrl(urlInput.value.trim())});
async function convertUrl(url){notice.className="notice";notice.textContent="";result.style.display="none";selected.textContent="Fetching file from URL...";urlSubmit.disabled=true;urlSubmit.textContent="Converting...";
try{const response=await fetch("/api/convert-url",{method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify({url})});if(!response.ok){const data=await response.json().catch(()=>({}));throw new Error(data.detail||"Could not convert that URL.")}converted=await response.text();output.textContent=converted;result.style.display="block";selected.textContent="URL converted";notice.className="notice ok";notice.textContent="Conversion complete."}
catch(error){showError(error.message)}finally{urlSubmit.disabled=false;urlSubmit.textContent="Convert URL"}}
for(const event of ["dragenter","dragover"])drop.addEventListener(event,e=>{e.preventDefault();drop.classList.add("drag")});
for(const event of ["dragleave","drop"])drop.addEventListener(event,e=>{e.preventDefault();drop.classList.remove("drag")});
drop.addEventListener("drop",e=>e.dataTransfer.files[0]&&convert(e.dataTransfer.files[0]));
async function convert(file){notice.className="notice";notice.textContent="";result.style.display="none";selected.textContent=file.name;if(file.size>4*1024*1024){showError("Please choose a file smaller than 4 MB.");return}
selected.textContent=file.name+" | Converting.";const body=new FormData();body.append("file",file);
try{const response=await fetch("/api/convert",{method:"POST",body});if(!response.ok){const data=await response.json().catch(()=>({}));throw new Error(data.detail||"Conversion failed. Please try another file.")}
converted=await response.text();output.textContent=converted;result.style.display="block";selected.textContent=file.name+" | Converted";notice.className="notice ok";notice.textContent="Conversion complete."}
catch(error){showError(error.message)}}
function showError(message){notice.className="notice error";notice.textContent=message;selected.textContent=""}
document.querySelector("#copy").addEventListener("click",async()=>{await navigator.clipboard.writeText(converted);document.querySelector("#copy").textContent="Copied";setTimeout(()=>document.querySelector("#copy").textContent="Copy",1300)});
document.querySelector("#download").addEventListener("click",()=>{const url=URL.createObjectURL(new Blob([converted],{type:"text/markdown;charset=utf-8"}));const a=document.createElement("a");a.href=url;a.download="converted.md";a.click();URL.revokeObjectURL(url)});
</script></body></html>'''


