import os
from contextlib import asynccontextmanager

import asyncpg
import uvicorn
from fastapi import FastAPI, HTTPException, Request, Response, Depends
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from pathlib import Path
from pydantic import BaseModel
import pendulum as pdl
import bcrypt
import pyotp

# Database pool reference
db_pool: asyncpg.Pool | None = None

# Base directory for static files
BASE_DIR = Path(__file__).resolve().parent.parent

# Database initialization on startup
@asynccontextmanager
async def lifespan(app: FastAPI):
    global db_pool
    database_url = os.getenv("DATABASE_URL")

    # Initialize connection pool
    if database_url:
        db_pool = await asyncpg.create_pool(dsn=database_url)

        # Create tables and default data
        async with db_pool.acquire() as conn:
            # 1. Create users table for family members
            await conn.execute("""
                CREATE TABLE IF NOT EXISTS users (
                    id BIGSERIAL PRIMARY KEY,
                    username VARCHAR(50) UNIQUE NOT NULL,
                    password_hash TEXT NOT NULL,
                    mfa_secret TEXT,
                    is_mfa_enabled BOOLEAN DEFAULT FALSE,
                    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
                );
            """)
            await conn.execute("""
                CREATE TABLE IF NOT EXISTS todos (
                    id BIGINT,
                    user_id BIGINT REFERENCES users(id) ON DELETE CASCADE,
                    text TEXT NOT NULL,
                    completed BOOLEAN DEFAULT FALSE,
                    due_date TIMESTAMP WITH TIME ZONE,
                    notified BOOLEAN DEFAULT FALSE,
                    PRIMARY KEY (id, user_id)
                );
            """)
            await conn.execute("""
                CREATE TABLE IF NOT EXISTS cities (
                    id BIGINT,
                    user_id BIGINT REFERENCES users(id) ON DELETE CASCADE,
                    name VARCHAR(100) NOT NULL,
                    lat DOUBLE PRECISION NOT NULL,
                    lon DOUBLE PRECISION NOT NULL,
                    PRIMARY KEY (id, user_id)
                );
            """)

            count = await conn.fetchval("SELECT COUNT(*) FROM cities")
            if count == 0:
                await conn.execute("""
                    INSERT INTO cities (id, name, lat, lon, user_id) VALUES 
                    (1, 'Paris', 48.8534, 2.3488, 1),
                    (2, 'Lyon', 45.7485, 4.8467, 1)
                """)
    yield
    if db_pool:
        await db_pool.close()


app = FastAPI(title="nicolasverdon", lifespan=lifespan)
templates = Jinja2Templates(directory="templates")

# CORS Configuration
app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://nicolasverdon.com",
        "https://nicolasverdon.com",
        "http://www.nicolasverdon.com",
        "https://www.nicolasverdon.com",
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# --- Pydantic Models ---
class TodoCreate(BaseModel):
    id: int
    text: str
    completed: bool = False
    dueDate: str | None = None
    notified: bool = False


class TodoUpdate(BaseModel):
    text: str | None = None
    completed: bool | None = None
    notified: bool | None = None


class CityCreate(BaseModel):
    id: int
    name: str
    lat: float
    lon: float

# MFA endpoints
class LoginRequest(BaseModel):
    username: str
    password: str
    mfa_code: str | None

@app.post("/api/auth/login")
async def login(data: LoginRequest, response: Response):
    async with db_pool.acquire() as conn:
        user = await conn.fetchrow("SELECT * FROM users WHERE username = $1", data.username)
        if not user or not bcrypt.checkpw(data.password.encode('utf-8'), user['password_hash'].encode('utf-8')):
            raise HTTPException(status_code=400, detail="Invalid username or password")
        
        # Check if MFA is enabled for this family member account
        if user['is_mfa_enabled']:
            if not data.mfa_code:
                return {"mfa_required": True, "message": "MFA code required"}
            
            totp = pyotp.TOTP(user['mfa_secret'])
            if not totp.verify(data.mfa_code):
                raise HTTPException(status_code=400, detail="Invalid MFA code")

        # Set an HttpOnly secure session cookie upon successful verification
        response.set_cookie(
            key="session_user",
            value=str(user['id']),
            httponly=True,
            secure=True,
            samesite="lax",
            max_age=60 * 60 * 24 * 7 # Active for 7 days
        )
        return {"status": "success", "username": user['username']}

async def get_current_user(request: Request) -> int:
    user_id = request.cookies.get("session_user")
    if not user_id:
        raise HTTPException(status_code=401, detail="Not authenticated")
    return int(user_id)

# --- HTMX / Homepage Routes ---
@app.get("/", response_class=HTMLResponse)
async def read_home(request: Request):
    return templates.TemplateResponse(request, "index.html")


@app.get("/api/hello", response_class=HTMLResponse)
async def get_hello_fragment():
    return "<p>Hello! This content was loaded via HTMX without refreshing the page.</p>"


# --- TODOS API ---
@app.get("/api/todos")
async def get_todos(user_id: int = Depends(get_current_user)):
    async with db_pool.acquire() as conn:
        rows = await conn.fetch("SELECT * FROM todos WHERE user_id = $1 ORDER BY id ASC", user_id)
        return [dict(row) for row in rows]


@app.post("/api/todos", status_code=201)
async def create_todo(todo: TodoCreate, user_id: int = Depends(get_current_user)):
    async with db_pool.acquire() as conn:
        #convert dueDate to timestamp if provided
        todo.dueDate = pdl.parse(todo.dueDate) if todo.dueDate else None
        row = await conn.fetchrow(
            """
            INSERT INTO todos (id, text, completed, due_date, notified, user_id)
            VALUES ($1, $2, $3, $4, $5, $6)
            RETURNING *
            """,
            todo.id,
            todo.text,
            todo.completed,
            todo.dueDate,
            todo.notified,
            user_id
        )
        return dict(row)


@app.put("/api/todos/{todo_id}")
async def update_todo(todo_id: int, todo: TodoUpdate, user_id: int = Depends(get_current_user)):
    async with db_pool.acquire() as conn:
        row = await conn.fetchrow(
            """
            UPDATE todos 
            SET text = COALESCE($1, text),
                completed = COALESCE($2, completed), 
                notified = COALESCE($3, notified) 
            WHERE id = $4 AND user_id = $5
            RETURNING *
            """,
            todo.text,
            todo.completed,
            todo.notified,
            todo_id,
            user_id
        )
        if not row:
            raise HTTPException(status_code=404, detail="Tâche non trouvée")
        return dict(row)


@app.delete("/api/todos/{todo_id}")
async def delete_todo(todo_id: int, user_id: int = Depends(get_current_user)):
    async with db_pool.acquire() as conn:
        row = await conn.fetchrow(
            "DELETE FROM todos WHERE id = $1 AND user_id = $2 RETURNING *", todo_id, user_id
        )
        if not row:
            raise HTTPException(status_code=404, detail="Tâche non trouvée")
        return {"message": "Tâche supprimée avec succès"}


# --- CITIES API ---
@app.get("/api/cities")
async def get_cities(user_id: int = Depends(get_current_user)):
    async with db_pool.acquire() as conn:
        rows = await conn.fetch("SELECT * FROM cities WHERE user_id = $1 ORDER BY id ASC", user_id)
        return [dict(row) for row in rows]


@app.post("/api/cities", status_code=201)
async def create_city(city: CityCreate, user_id: int = Depends(get_current_user)):
    async with db_pool.acquire() as conn:
        row = await conn.fetchrow(
            """
            INSERT INTO cities (id, name, lat, lon, user_id) 
            VALUES ($1, $2, $3, $4, $5) 
            RETURNING *
            """,
            city.id,
            city.name,
            city.lat,
            city.lon,
            user_id
        )
        return dict(row)


@app.delete("/api/cities/{city_id}")
async def delete_city(city_id: int, user_id: int = Depends(get_current_user)):
    async with db_pool.acquire() as conn:
        row = await conn.fetchrow(
            "DELETE FROM cities WHERE id = $1 AND user_id = $2 RETURNING *", city_id, user_id
        )
        if not row:
            raise HTTPException(status_code=404, detail="Ville non trouvée")
        return {"message": "Ville supprimée avec succès"}


@app.get("/health")
def health_check():
    return {"status": "healthy"}


# --- Mount Static Dashboard ---
# Pointing to the compiled dashboard-perso/dist output
app.mount(
    "/dashboard",
    StaticFiles(directory=str(BASE_DIR / "dashboard-perso" / "dist"), html=True),
    name="dashboard",
)

if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=8000)