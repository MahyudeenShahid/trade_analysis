"""Chart direction analysis route."""

import os
import tempfile

from fastapi import APIRouter, File, UploadFile, HTTPException

router = APIRouter(prefix="/chart", tags=["chart"])

# Lazy import so the server starts even if opencv is missing
_detector = None

def _get_detector():
    global _detector
    if _detector is None:
        from chart_line_detector import ChartDirectionDetector
        _detector = ChartDirectionDetector()
    return _detector


@router.post("/direction")
async def analyze_chart_direction(file: UploadFile = File(...)):
    """
    Upload a chart screenshot and receive its trend direction.

    Returns
    -------
    JSON: { "direction": "UP" | "DOWN" | "NONE", "filename": str }
    """
    if not file.filename.lower().endswith((".png", ".jpg", ".jpeg", ".bmp")):
        raise HTTPException(status_code=400, detail="Unsupported file format. Use PNG, JPG, JPEG or BMP.")

    contents = await file.read()
    if not contents:
        raise HTTPException(status_code=400, detail="Empty file.")

    # Write to a temp file (cv2 needs a real path)
    suffix = os.path.splitext(file.filename)[-1] or ".png"
    with tempfile.NamedTemporaryFile(delete=False, suffix=suffix) as tmp:
        tmp.write(contents)
        tmp_path = tmp.name

    try:
        detector = _get_detector()
        result = detector.analyze_with_details(tmp_path)
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Detection failed: {exc}")
    finally:
        try:
            os.remove(tmp_path)
        except OSError:
            pass

    if not result["success"]:
        raise HTTPException(status_code=422, detail=result["error"])

    return {
        "direction": result["direction"],
        "filename": file.filename,
    }
