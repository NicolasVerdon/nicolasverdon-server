import uvicorn
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates

app = FastAPI(title="nicolasverdon")
templates = Jinja2Templates(directory="templates")

# Configure CORS
origins = [
    "http://nicolasverdon.com",
    "https://nicolasverdon.com",
    "http://www.nicolasverdon.com",
    "https://www.nicolasverdon.com",
]

app.add_middleware(
    CORSMiddleware,
    allow_origins=origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# 1. Root route: Serves the main HTMX-enabled homepage
@app.get("/", response_class=HTMLResponse)
async def read_home(request: Request):
    return templates.TemplateResponse(request, "index.html")

# 2. HTMX endpoint: Returns raw HTML fragments instead of JSON
@app.get("/api/hello", response_class=HTMLResponse)
async def get_hello_fragment():
    return "<p>Hello! This content was loaded via HTMX without refreshing the page.</p>"

@app.get("/health")
def health_check():
    return {"status": "healthy"}


if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=8000)
