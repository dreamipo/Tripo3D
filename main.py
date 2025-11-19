import os
import shutil
from typing import List
from fastapi import FastAPI, UploadFile, File, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from starlette.responses import FileResponse
from utils.tripo_sdk_client import generate_3d_from_images
from utils.supabase_client import upload_to_supabase
import time

# Create FastAPI app
app = FastAPI(
    title="Tripo3D Backend",
    description="Generate 3D models from single or multiple images",
    version="1.1.0"
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Directories for uploads and output
UPLOAD_DIR = "./uploads"
OUTPUT_DIR = "./output"
os.makedirs(UPLOAD_DIR, exist_ok=True)
os.makedirs(OUTPUT_DIR, exist_ok=True)

# Serve output directory as static files
app.mount("/output", StaticFiles(directory=OUTPUT_DIR), name="output")

# Optional: define a public base URL (e.g., your ngrok URL)
PUBLIC_BASE_URL = os.getenv("PUBLIC_BASE_URL", "").rstrip("/")


@app.post("/generate-3d-model")
@app.post("/generate-3d-model")
async def generate_3d_model(request: Request, files: List[UploadFile] = File(...)):
    saved_files = []
    for f in files:
        save_path = os.path.join(UPLOAD_DIR, f.filename)
        with open(save_path, "wb") as buffer:
            shutil.copyfileobj(f.file, buffer)
        saved_files.append(save_path)

    print(f"📸 Received {len(saved_files)} image(s). Starting Tripo3D processing...")

    result = await generate_3d_from_images(saved_files)

    if result.get("status") == "success":

        bucket = os.getenv("SUPABASE_BUCKET")

        supabase_urls = []

        # Loop through Tripo3D output files
        for key, value in result.get("files", {}).items():
            if isinstance(value, str) and value.endswith(".glb"):

                filename = os.path.basename(value)
                dest = f"models/{int(time.time())}_{filename}"   # unique storage path

                # Upload to supabase
                file_url = upload_to_supabase(value, dest, bucket)
                supabase_urls.append(file_url)

        print("✅ Uploaded to Supabase:")
        print(supabase_urls)

        return {
            "status": "success",
            "message": "3D model generated successfully.",
            "file_urls": supabase_urls
        }

    return {"status": "error", "message": "3D model generation failed"}


# ✅ Optional: direct file serving with correct MIME type
@app.get("/output/{filename}")
async def serve_model(filename: str):
    file_path = os.path.join(OUTPUT_DIR, filename)
    if not os.path.exists(file_path):
        return {"error": "File not found"}
    return FileResponse(file_path, media_type="model/gltf-binary")
