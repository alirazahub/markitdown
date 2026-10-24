from __future__ import annotations

from io import BytesIO
from pathlib import Path

from fastapi import FastAPI, File, HTTPException, UploadFile
from fastapi.responses import HTMLResponse, Response
from markitdown import MarkItDown

app = FastAPI(title="MarkItDown Web", docs_url=None, redoc_url=None)
MAX_UPLOAD_BYTES = 4 * 1024 * 1024
_converter = MarkItDown(enable_plugins=False)


@app.get("/", response_class=HTMLResponse)
async def home() -> str:
    return PAGE


@app.post("/api/convert")
async def convert(file: UploadFile = File(...)) -> Response:
    filename = Path(file.filename or "upload").name
    data = await file.read(MAX_UPLOAD_BYTES + 1)
    if not data:
        raise HTTPException(status_code=400, detail="The uploaded file is empty.")
    if len(data) > MAX_UPLOAD_BYTES:
        raise HTTPException(status_code=413, detail="Please upload a file smaller than 4 MB.")

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


PAGE = r'''<!doctype html>
<html lang="en"><head>
<meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<meta name="theme-color" content="#f7f6f2"><title>MarkItDown - convert files to Markdown</title>
<style>
:root{font-family:Inter,ui-sans-serif,system-ui,-apple-system,BlinkMacSystemFont,"Segoe UI",sans-serif;color:#17221e;background:#f7f6f2}
*{box-sizing:border-box}body{margin:0;min-height:100vh;background:radial-gradient(ellipse at 50% -20%,#dceee4 0,transparent 52%),#f7f6f2}
header{height:76px;border-bottom:1px solid #e7e8e1;display:flex;align-items:center;justify-content:space-between;padding:0 max(24px,calc((100vw - 1120px)/2))}
.brand{display:flex;gap:11px;align-items:center;font-weight:750;letter-spacing:-.03em}.mark{display:grid;place-items:center;width:34px;height:34px;border-radius:11px;background:#153f32;color:white;font-size:15px}
.badge{font-size:12px;color:#597064;border:1px solid #dce4dc;border-radius:999px;padding:7px 11px;background:#ffffff80}
main{width:min(100% - 40px,840px);margin:76px auto 64px}.eyebrow{color:#267354;font-size:12px;font-weight:750;letter-spacing:.14em;text-transform:uppercase;text-align:center}
h1{text-align:center;font-size:clamp(38px,6vw,62px);letter-spacing:-.065em;line-height:1.04;margin:17px 0 15px}.sub{text-align:center;color:#65736c;line-height:1.65;font-size:16px;margin:0 auto 38px;max-width:590px}
.card{background:#fff;border:1px solid #e7e8e1;border-radius:22px;box-shadow:0 18px 55px #273d3010;padding:20px}
.drop{min-height:230px;border:1.5px dashed #cbd8cd;border-radius:15px;display:flex;flex-direction:column;align-items:center;justify-content:center;text-align:center;padding:22px;transition:.18s;background:#fbfcfa}
.drop.drag{border-color:#267354;background:#f1f8f3}.upload-icon{width:46px;height:46px;border-radius:15px;background:#e8f3eb;display:grid;place-items:center;color:#267354;font-size:22px;margin-bottom:13px}
.drop strong{font-size:16px}.drop p{margin:7px 0 16px;color:#7a857f;font-size:13px}.choose{border:0;background:#173f32;color:#fff;border-radius:9px;padding:10px 15px;font-weight:650;cursor:pointer}.choose:hover,.action.primary:hover{background:#205741}
input[type=file]{display:none}.formats{text-align:center;color:#89938d;font-size:12px;margin:16px 0 0}.selected{margin-top:14px;color:#53655b;font-size:13px;min-height:18px}
.result{display:none;margin-top:18px}.result-top{display:flex;align-items:center;justify-content:space-between;margin-bottom:10px}.result-top strong{font-size:14px}.actions{display:flex;gap:8px}.action{border:1px solid #e0e5df;background:white;border-radius:8px;padding:8px 11px;font-weight:600;font-size:12px;color:#35483e;cursor:pointer}.action.primary{background:#173f32;color:#fff;border-color:#173f32}
pre{margin:0;max-height:420px;overflow:auto;background:#f8faf8;border:1px solid #e9ede8;border-radius:12px;padding:16px;white-space:pre-wrap;overflow-wrap:anywhere;color:#34463c;font:13px/1.65 ui-monospace,SFMono-Regular,Consolas,monospace}
.notice{display:none;margin-top:14px;border-radius:10px;padding:11px 13px;font-size:13px}.notice.error{display:block;background:#fff3f0;color:#a43c28}.notice.ok{display:block;background:#edf7ef;color:#286141}
.privacy{display:flex;justify-content:center;align-items:center;gap:7px;color:#758078;font-size:12px;margin:19px 0 0}.dot{width:7px;height:7px;border-radius:50%;background:#50a06e}
footer{text-align:center;color:#919a94;font-size:12px;margin-top:30px}footer a{color:#526d5d;text-decoration:none}
@media(max-width:560px){header{height:64px}.badge{font-size:11px}main{margin-top:52px}.card{padding:12px}.drop{min-height:210px}.result-top{align-items:flex-start;gap:8px;flex-direction:column}}
</style></head><body>
<header><div class="brand"><span class="mark">M</span><span>MarkItDown</span></div><span class="badge">Runs on Microsoft MarkItDown</span></header>
<main><div class="eyebrow">Document converter</div><h1>Turn files into<br>clean Markdown.</h1>
<p class="sub">Drop in a document and get Markdown you can copy, download, or use in your next project.</p>
<section class="card">
<div class="drop" id="drop"><div class="upload-icon">+</div><strong>Drag a file here to get started</strong>
<p>or choose a file from your device</p><button class="choose" id="choose" type="button">Choose file</button>
<input id="file" type="file" accept=".pdf,.docx,.pptx,.xlsx,.xls,.html,.htm,.csv,.json,.xml,.txt,.md,.epub,.zip,.jpg,.jpeg,.png,.gif,.bmp,.tif,.tiff,.wav,.mp3">
<div class="selected" id="selected"></div></div>
<div class="formats">PDF | Word | PowerPoint | Excel | HTML | CSV | JSON | images | audio | and more</div>
<div class="notice" id="notice" role="status"></div>
<div class="result" id="result"><div class="result-top"><strong>Markdown output</strong><div class="actions"><button class="action" id="copy" type="button">Copy</button><button class="action primary" id="download" type="button">Download .md</button></div></div><pre id="output"></pre></div>
</section><div class="privacy"><span class="dot"></span> Files are processed for conversion and not saved by this app | 4 MB max</div>
<footer>Powered by <a href="https://github.com/microsoft/markitdown" target="_blank" rel="noreferrer">Microsoft MarkItDown</a></footer></main>
<script>
const fileInput=document.querySelector("#file"),drop=document.querySelector("#drop"),selected=document.querySelector("#selected"),notice=document.querySelector("#notice"),result=document.querySelector("#result"),output=document.querySelector("#output");let converted="";
document.querySelector("#choose").addEventListener("click",()=>fileInput.click());fileInput.addEventListener("change",()=>fileInput.files[0]&&convert(fileInput.files[0]));
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


