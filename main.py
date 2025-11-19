# import os
# import shutil
# from typing import List
# from fastapi import FastAPI, UploadFile, File, Request
# from fastapi.middleware.cors import CORSMiddleware
# from fastapi.staticfiles import StaticFiles
# from starlette.responses import FileResponse
# from utils.tripo_sdk_client import generate_3d_from_images
# from utils.supabase_client import upload_to_supabase
# import time

# # Create FastAPI app
# app = FastAPI(
#     title="Tripo3D Backend",
#     description="Generate 3D models from single or multiple images",
#     version="1.1.0"
# )

# app.add_middleware(
#     CORSMiddleware,
#     allow_origins=["*"],
#     allow_credentials=True,
#     allow_methods=["*"],
#     allow_headers=["*"],
# )

# # Directories for uploads and output
# UPLOAD_DIR = "./uploads"
# OUTPUT_DIR = "./output"
# os.makedirs(UPLOAD_DIR, exist_ok=True)
# os.makedirs(OUTPUT_DIR, exist_ok=True)

# # Serve output directory as static files
# app.mount("/output", StaticFiles(directory=OUTPUT_DIR), name="output")

# # Optional: define a public base URL (e.g., your ngrok URL)
# PUBLIC_BASE_URL = os.getenv("PUBLIC_BASE_URL", "").rstrip("/")


# @app.post("/generate-3d-model")
# @app.post("/generate-3d-model")
# async def generate_3d_model(request: Request, files: List[UploadFile] = File(...)):
#     saved_files = []
#     for f in files:
#         save_path = os.path.join(UPLOAD_DIR, f.filename)
#         with open(save_path, "wb") as buffer:
#             shutil.copyfileobj(f.file, buffer)
#         saved_files.append(save_path)

#     print(f"📸 Received {len(saved_files)} image(s). Starting Tripo3D processing...")

#     result = await generate_3d_from_images(saved_files)

#     if result.get("status") == "success":

#         bucket = os.getenv("SUPABASE_BUCKET")

#         supabase_urls = []

#         # Loop through Tripo3D output files
#         for key, value in result.get("files", {}).items():
#             if isinstance(value, str) and value.endswith(".glb"):

#                 filename = os.path.basename(value)
#                 dest = f"models/{int(time.time())}_{filename}"   # unique storage path

#                 # Upload to supabase
#                 file_url = upload_to_supabase(value, dest, bucket)
#                 supabase_urls.append(file_url)

#         print("✅ Uploaded to Supabase:")
#         print(supabase_urls)

#         return {
#             "status": "success",
#             "message": "3D model generated successfully.",
#             "file_urls": supabase_urls
#         }

#     return {"status": "error", "message": "3D model generation failed"}


# # ✅ Optional: direct file serving with correct MIME type
# @app.get("/output/{filename}")
# async def serve_model(filename: str):
#     file_path = os.path.join(OUTPUT_DIR, filename)
#     if not os.path.exists(file_path):
#         return {"error": "File not found"}
#     return FileResponse(file_path, media_type="model/gltf-binary")



import os
import shutil
import uuid
from typing import List
from fastapi import FastAPI, UploadFile, File, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse, StreamingResponse
from utils.tripo_sdk_client import generate_3d_from_images
from utils.supabase_client import upload_to_supabase
import time
import asyncio
import json

# =========================================================
#                FASTAPI INITIAL SETUP
# =========================================================

app = FastAPI(
    title="Tripo3D Backend",
    description="Generate 3D models from single or multiple images",
    version="2.0.0"
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

UPLOAD_DIR = "./uploads"
OUTPUT_DIR = "./output"

os.makedirs(UPLOAD_DIR, exist_ok=True)
os.makedirs(OUTPUT_DIR, exist_ok=True)

app.mount("/output", StaticFiles(directory=OUTPUT_DIR), name="output")

# Stores uploaded image paths temporarily
UPLOAD_SESSIONS = {}

# =========================================================
#               SSE EVENT HELPER
# =========================================================

def sse_event(event: str, data: dict):
    """Format Server-Sent Event message."""
    return f"event: {event}\ndata: {json.dumps(data)}\n\n"


# =========================================================
#           1) UPLOAD IMAGES (returns TOKEN)
# =========================================================

@app.post("/upload-images")
async def upload_images(files: List[UploadFile] = File(...)):
    token = str(uuid.uuid4())
    session_folder = os.path.join(UPLOAD_DIR, token)
    os.makedirs(session_folder, exist_ok=True)

    saved_files = []

    for f in files:
        path = os.path.join(session_folder, f.filename)
        with open(path, "wb") as buffer:
            shutil.copyfileobj(f.file, buffer)
        saved_files.append(path)

    UPLOAD_SESSIONS[token] = saved_files

    return {
        "status": "success",
        "token": token,
        "count": len(saved_files),
        "message": "Images uploaded successfully."
    }


# =========================================================
#       2) STREAM MODEL GENERATION WITH LIVE PROGRESS
# =========================================================

@app.get("/generate-3d-model-stream")
async def generate_model_stream(token: str):

    async def event_stream():
        images = UPLOAD_SESSIONS.get(token)

        if not images:
            yield sse_event("error", {"message": "Invalid or expired token"})
            return

        # -------- Step Status #1 --------
        yield sse_event("progress", {
            "percent": 10,
            "message": f"{len(images)} images received"
        })
        await asyncio.sleep(1)

        # -------- Step Status #2 --------
        yield sse_event("progress", {
            "percent": 30,
            "message": "Starting 3D model generation..."
        })

        # Call your real Tripo SDK
        result = await generate_3d_from_images(images)

        if result.get("status") != "success":
            yield sse_event("error", {"message": "Model generation failed"})
            return

        await asyncio.sleep(1)

        # -------- Step Status #3 --------
        yield sse_event("progress", {
            "percent": 70,
            "message": "Optimizing final model..."
        })
        await asyncio.sleep(1)

        # Upload generated model(s) to Supabase
        supabase_urls = []
        bucket = os.getenv("SUPABASE_BUCKET")

        for key, value in result.get("files", {}).items():
            if isinstance(value, str) and value.endswith(".glb"):
                filename = os.path.basename(value)
                dest = f"models/{int(time.time())}_{filename}"
                supabase_urls.append(upload_to_supabase(value, dest, bucket))

        # -------- Step Status #4 --------
        yield sse_event("progress", {
            "percent": 100,
            "message": "Model completed!"
        })

        await asyncio.sleep(0.5)

        # -------- Final Event --------
        yield sse_event("complete", {
            "modelUrl": supabase_urls[0]
        })

    return StreamingResponse(event_stream(), media_type="text/event-stream")


# =========================================================
#         DIRECT FILE SERVING (OPTIONAL)
# =========================================================

@app.get("/output/{filename}")
async def serve_model(filename: str):
    file_path = os.path.join(OUTPUT_DIR, filename)
    if not os.path.exists(file_path):
        return {"error": "File not found"}
    return FileResponse(file_path, media_type="model/gltf-binary")
