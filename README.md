# MarkItDown Web

A small web interface for converting files to Markdown with Microsoft's [MarkItDown](https://github.com/microsoft/markitdown). Built-in conversion runs in the Python app and needs no AI or cloud API key.

## Run locally

Requires Python 3.10-3.14.

```powershell
py -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
uvicorn app:app --reload
```

Open http://127.0.0.1:8000.

## Deploy to Vercel

1. Push this folder to a GitHub repository.
2. In Vercel, choose **Add New  Project** and import that repository.
3. Deploy. Vercel detects the FastAPI `app` in `app.py` and installs `requirements.txt`.

No environment variables are required for built-in conversion. Uploads are limited to 4 MB to stay below Vercel Functions' 4.5 MB request-body limit. Larger files need direct-to-object-storage uploads and a separate processing strategy.

## Privacy

This app does not persist uploaded files or conversion results; the file is held in request memory while converting. Review MarkItDown's security guidance before accepting uploads from untrusted users.


