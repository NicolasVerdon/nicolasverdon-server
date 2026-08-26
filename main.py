from fastapi import FastAPI
import uvicorn

app = FastAPI(title="nicolasverdon")

@app.get("/")
def read_root():
    return {"message": "nicolasverdon API"}

@app.get("/health")
def health_check():
    return {"status": "healthy"}


if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=8000)
