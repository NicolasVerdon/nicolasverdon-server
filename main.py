import os
from contextlib import asynccontextmanager

import asyncpg
import uvicorn
from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from pydantic import BaseModel

# Database pool reference
db_pool: asyncpg.Pool | None = None


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
            await conn.execute("""
                CREATE TABLE IF NOT EXISTS todos (
                    id BIGINT PRIMARY KEY,
                    text TEXT NOT NULL,
                    completed BOOLEAN DEFAULT FALSE,
                    due_date TIMESTAMP WITH TIME ZONE,
                    notified BOOLEAN DEFAULT FALSE
                );
            """)
            await conn.execute("""
                CREATE TABLE IF NOT EXISTS cities (
                    id BIGINT PRIMARY KEY,
                    name VARCHAR(100) NOT NULL,
                    lat DOUBLE PRECISION NOT NULL,
                    lon DOUBLE PRECISION NOT NULL
                );
            """)

            count = await conn.fetchval("SELECT COUNT(*) FROM cities")
            if count == 0:
                await conn.execute("""
                    INSERT INTO cities (id, name, lat, lon) VALUES 
                    (1, 'Paris', 48.8534, 2.3488),
                    (2, 'Lyon', 45.7485, 4.8467)
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


# --- HTMX / Homepage Routes ---
@app.get("/", response_class=HTMLResponse)
async def read_home(request: Request):
    return templates.TemplateResponse(request, "index.html")


@app.get("/api/hello", response_class=HTMLResponse)
async def get_hello_fragment():
    return "<p>Hello! This content was loaded via HTMX without refreshing the page.</p>"


# --- TODOS API ---
@app.get("/api/todos")
async def get_todos():
    async with db_pool.acquire() as conn:
        rows = await conn.fetch("SELECT * FROM todos ORDER BY id ASC")
        return [dict(row) for row in rows]


@app.post("/api/todos", status_code=201)
async def create_todo(todo: TodoCreate):
    async with db_pool.acquire() as conn:
        row = await conn.fetchrow(
            """
            INSERT INTO todos (id, text, completed, due_date, notified)
            VALUES ($1, $2, $3, $4, $5)
            RETURNING *
            """,
            todo.id,
            todo.text,
            todo.completed,
            todo.dueDate,
            todo.notified,
        )
        return dict(row)


@app.put("/api/todos/{todo_id}")
async def update_todo(todo_id: int, todo: TodoUpdate):
    async with db_pool.acquire() as conn:
        row = await conn.fetchrow(
            """
            UPDATE todos 
            SET text = COALESCE($1, text),
                completed = COALESCE($2, completed), 
                notified = COALESCE($3, notified) 
            WHERE id = $4 
            RETURNING *
            """,
            todo.text,
            todo.completed,
            todo.notified,
            todo_id,
        )
        if not row:
            raise HTTPException(status_code=404, detail="Tâche non trouvée")
        return dict(row)


@app.delete("/api/todos/{todo_id}")
async def delete_todo(todo_id: int):
    async with db_pool.acquire() as conn:
        row = await conn.fetchrow(
            "DELETE FROM todos WHERE id = $1 RETURNING *", todo_id
        )
        if not row:
            raise HTTPException(status_code=404, detail="Tâche non trouvée")
        return {"message": "Tâche supprimée avec succès"}


# --- CITIES API ---
@app.get("/api/cities")
async def get_cities():
    async with db_pool.acquire() as conn:
        rows = await conn.fetch("SELECT * FROM cities ORDER BY id ASC")
        return [dict(row) for row in rows]


@app.post("/api/cities", status_code=201)
async def create_city(city: CityCreate):
    async with db_pool.acquire() as conn:
        row = await conn.fetchrow(
            """
            INSERT INTO cities (id, name, lat, lon) 
            VALUES ($1, $2, $3, $4) 
            RETURNING *
            """,
            city.id,
            city.name,
            city.lat,
            city.lon,
        )
        return dict(row)


@app.delete("/api/cities/{city_id}")
async def delete_city(city_id: int):
    async with db_pool.acquire() as conn:
        row = await conn.fetchrow(
            "DELETE FROM cities WHERE id = $1 RETURNING *", city_id
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
    StaticFiles(directory="../dashboard-perso/dist", html=True),
    name="dashboard",
)

if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=8000)