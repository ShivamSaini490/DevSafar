from fastapi import FastAPI

app = FastAPI(title="Travel Planner API", version="0.1.0")


@app.get("/api/v1/health")
def health():
    return {"status": "ok"}