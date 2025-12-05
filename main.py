import io
import httpx
from fastapi import FastAPI, File, UploadFile, HTTPException
from fastapi.responses import JSONResponse

app = FastAPI(title="Document Summary Agent")

OLLAMA_BASE_URL = "http://localhost:11434"
OLLAMA_MODEL = "llama3.2"


def extract_text(filename: str, content: bytes) -> str:
    ext = filename.rsplit(".", 1)[-1].lower() if "." in filename else ""

    if ext == "pdf":
        try:
            import pypdf
            reader = pypdf.PdfReader(io.BytesIO(content))
            return "\n".join(page.extract_text() or "" for page in reader.pages)
        except ImportError:
            raise HTTPException(status_code=422, detail="pypdf not installed — cannot parse PDF")

    if ext == "docx":
        try:
            import docx
            doc = docx.Document(io.BytesIO(content))
            return "\n".join(p.text for p in doc.paragraphs)
        except ImportError:
            raise HTTPException(status_code=422, detail="python-docx not installed — cannot parse DOCX")

    try:
        return content.decode("utf-8")
    except UnicodeDecodeError:
        return content.decode("latin-1")


async def summarize_with_ollama(text: str) -> str:
    prompt = (
        "You are a helpful assistant. Summarize the following document concisely, "
        "capturing the main points and key information.\n\n"
        f"Document:\n{text}\n\n"
        "Summary:"
    )

    async with httpx.AsyncClient(timeout=120.0) as client:
        try:
            response = await client.post(
                f"{OLLAMA_BASE_URL}/api/generate",
                json={"model": OLLAMA_MODEL, "prompt": prompt, "stream": False},
            )
            response.raise_for_status()
        except httpx.ConnectError:
            raise HTTPException(status_code=503, detail="Cannot connect to Ollama — is it running?")
        except httpx.HTTPStatusError as e:
            raise HTTPException(status_code=502, detail=f"Ollama error: {e.response.text}")

    data = response.json()
    return data.get("response", "").strip()


@app.post("/summarize")
async def summarize(file: UploadFile = File(...)):
    content = await file.read()
    if not content:
        raise HTTPException(status_code=400, detail="Uploaded file is empty")

    text = extract_text(file.filename or "", content).strip()
    if not text:
        raise HTTPException(status_code=422, detail="Could not extract any text from the document")

    words = text.split()
    if len(words) > 8000:
        text = " ".join(words[:8000])

    summary = await summarize_with_ollama(text)
    return JSONResponse({"filename": file.filename, "summary": summary})


@app.get("/health")
async def health():
    async with httpx.AsyncClient(timeout=5.0) as client:
        try:
            r = await client.get(f"{OLLAMA_BASE_URL}/api/tags")
            ollama_ok = r.status_code == 200
        except httpx.ConnectError:
            ollama_ok = False
    return {"status": "ok", "ollama": "reachable" if ollama_ok else "unreachable"}
