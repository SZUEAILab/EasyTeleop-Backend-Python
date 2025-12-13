import base64
import hashlib
import os
import tempfile
from typing import Dict, List, Tuple

import cv2
import h5py
import numpy as np
from fastapi import APIRouter, File, Form, HTTPException, UploadFile
from pydantic import BaseModel
from starlette.concurrency import run_in_threadpool

HDF5_ROOT = os.environ.get("HDF5_ROOT", "databases")
os.makedirs(HDF5_ROOT, exist_ok=True)

router = APIRouter(prefix="/api", tags=["hdf5"])

# Track chunked uploads by file_md5
upload_chunks: Dict[str, Dict[str, object]] = {}


class ProcessRequest(BaseModel):
    folder: str
    filename: str


def _safe_join(folder: str, filename: str) -> str:
    """Return absolute file path under HDF5_ROOT and guard path traversal."""
    base = os.path.abspath(HDF5_ROOT)
    target = os.path.abspath(os.path.join(base, folder, filename))
    if not target.startswith(base):
        raise HTTPException(status_code=400, detail="Invalid path")
    return target


def _count_hdf5_files(directory_path: str) -> int:
    count = 0
    for file in os.listdir(directory_path):
        if file.endswith(".hdf5"):
            count += 1
    return count


@router.get("/hdf5/folders")
def list_folders() -> List[Dict[str, object]]:
    """List child folders under HDF5_ROOT and their hdf5 counts."""
    folders: List[Dict[str, object]] = []
    if not os.path.exists(HDF5_ROOT):
        return folders

    for item in os.listdir(HDF5_ROOT):
        item_path = os.path.join(HDF5_ROOT, item)
        if os.path.isdir(item_path):
            folders.append(
                {
                    "name": item,
                    "hdf5_count": _count_hdf5_files(item_path),
                }
            )
    return folders


@router.get("/hdf5/files/{folder_name}")
def list_files(folder_name: str) -> List[Dict[str, object]]:
    """List hdf5 files inside a folder."""
    folder_path = os.path.join(HDF5_ROOT, folder_name)
    if not os.path.isdir(folder_path):
        raise HTTPException(status_code=404, detail="Folder not found")

    files: List[Dict[str, object]] = []
    for file in os.listdir(folder_path):
        if file.endswith(".hdf5"):
            file_path = os.path.join(folder_path, file)
            try:
                file_size = os.path.getsize(file_path)
            except OSError:
                file_size = 0
            files.append(
                {
                    "name": file,
                    "size": f"{file_size / 1024 / 1024:.2f} MB",
                    "folder": folder_name,
                }
            )
    return files


def _extract_images(file_path: str) -> Tuple[Dict[str, List[Dict[str, object]]], int]:
    """Extract images grouped by camera from HDF5 and return base64 strings."""
    camera_images: Dict[str, List[Dict[str, object]]] = {}
    total_frames = 0

    with h5py.File(file_path, "r") as f:
        def handle_group(image_group):
            nonlocal total_frames
            for cam_name in image_group.keys():
                camera_images[cam_name] = []
                img_data = image_group[cam_name][:]

                if total_frames == 0:
                    total_frames = len(img_data)

                for i, img_bytes in enumerate(img_data):
                    if isinstance(img_bytes, np.bytes_):
                        img_bytes = img_bytes.item()

                    nparr = np.frombuffer(img_bytes, np.uint8)
                    img = cv2.imdecode(nparr, cv2.IMREAD_COLOR)
                    if img is None:
                        continue
                    success, encoded = cv2.imencode(".jpg", img, [int(cv2.IMWRITE_JPEG_QUALITY), 85])
                    if not success:
                        continue
                    img_base64 = base64.b64encode(encoded.tobytes()).decode()
                    camera_images[cam_name].append(
                        {
                            "index": i,
                            "data": f"data:image/jpeg;base64,{img_base64}",
                        }
                    )

        if "observations" in f and "images" in f["observations"]:
            handle_group(f["observations"]["images"])
        elif "images" in f:
            handle_group(f["images"])

    return camera_images, total_frames


@router.post("/hdf5/process")
async def process_hdf5(payload: ProcessRequest):
    """Read an hdf5 file and return camera frames in base64."""
    try:
        file_path = _safe_join(payload.folder, payload.filename)
    except HTTPException:
        raise

    if not os.path.exists(file_path):
        raise HTTPException(status_code=404, detail="File not found")

    camera_images, total_frames = await run_in_threadpool(_extract_images, file_path)
    return {
        "success": True,
        "camera_images": camera_images,
        "total_frames": total_frames,
        "camera_names": list(camera_images.keys()),
    }


async def _upload_chunk_impl(
    chunk: UploadFile = File(...),
    file_md5: str = Form(...),
    filename: str = Form(...),
    chunk_index: int = Form(...),
    total_chunks: int = Form(...),
):
    """Receive one chunk of an HDF5 file."""
    temp_dir = os.path.join(tempfile.gettempdir(), "hdf5_uploads", file_md5)
    os.makedirs(temp_dir, exist_ok=True)

    chunk_path = os.path.join(temp_dir, f"chunk_{chunk_index}")
    with open(chunk_path, "wb") as f:
        f.write(await chunk.read())

    if file_md5 not in upload_chunks:
        upload_chunks[file_md5] = {
            "filename": filename,
            "total_chunks": total_chunks,
            "uploaded_chunks": set(),
            "temp_dir": temp_dir,
        }

    upload_chunks[file_md5]["uploaded_chunks"].add(chunk_index)

    return {
        "success": True,
        "message": f"chunk {chunk_index} uploaded",
        "uploaded_chunks": len(upload_chunks[file_md5]["uploaded_chunks"]),
        "total_chunks": total_chunks,
    }


@router.post("/hdf5/upload_chunk")
async def upload_chunk(
    chunk: UploadFile = File(...),
    file_md5: str = Form(...),
    filename: str = Form(...),
    chunk_index: int = Form(...),
    total_chunks: int = Form(...),
):
    """Compatibility endpoint for node uploads (scoped under /api/hdf5)."""
    return await _upload_chunk_impl(chunk, file_md5, filename, chunk_index, total_chunks)


@router.post("/upload_chunk")
async def upload_chunk_legacy(
    chunk: UploadFile = File(...),
    file_md5: str = Form(...),
    filename: str = Form(...),
    chunk_index: int = Form(...),
    total_chunks: int = Form(...),
):
    """Legacy path for existing node clients."""
    return await _upload_chunk_impl(chunk, file_md5, filename, chunk_index, total_chunks)


def _merge_chunks_impl(payload: Dict[str, object]):
    """Merge all uploaded chunks into a single HDF5 file."""
    file_md5 = str(payload.get("file_md5", ""))
    filename = str(payload.get("filename", ""))
    total_chunks = int(payload.get("total_chunks", 0))

    if not file_md5 or file_md5 not in upload_chunks:
        raise HTTPException(status_code=404, detail="file not found or expired")

    chunk_info = upload_chunks[file_md5]
    uploaded_chunks = chunk_info["uploaded_chunks"]

    if len(uploaded_chunks) != total_chunks:
        raise HTTPException(
            status_code=400,
            detail=f"incomplete chunks ({len(uploaded_chunks)}/{total_chunks})",
        )

    temp_dir = chunk_info["temp_dir"]
    final_filename = f"{hashlib.md5(filename.encode()).hexdigest()}_{filename}"
    final_path = os.path.join(HDF5_ROOT, "uploaded_from_api", final_filename)
    os.makedirs(os.path.dirname(final_path), exist_ok=True)

    with open(final_path, "wb") as output_file:
        for i in range(total_chunks):
            chunk_path = os.path.join(temp_dir, f"chunk_{i}")
            with open(chunk_path, "rb") as chunk_file:
                output_file.write(chunk_file.read())
            os.remove(chunk_path)

    try:
        os.rmdir(temp_dir)
    except OSError:
        pass
    upload_chunks.pop(file_md5, None)

    return {
        "success": True,
        "message": "file merged successfully",
        "filename": final_filename,
        "file_path": final_path,
    }


@router.post("/hdf5/merge_chunks")
def merge_chunks(payload: Dict[str, object]):
    """Compatibility endpoint for merge (scoped under /api/hdf5)."""
    return _merge_chunks_impl(payload)


@router.post("/merge_chunks")
def merge_chunks_legacy(payload: Dict[str, object]):
    """Legacy path for existing node clients."""
    return _merge_chunks_impl(payload)
