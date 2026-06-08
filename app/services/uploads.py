import uuid
from pathlib import Path

from fastapi import HTTPException, UploadFile

from app.config import settings

ALLOWED_IMAGE_TYPES = {
    "image/jpeg": ".jpg",
    "image/png": ".png",
    "image/webp": ".webp",
    "image/gif": ".gif",
}


def upload_dir() -> Path:
    path = Path(settings.UPLOAD_DIR)
    path.mkdir(parents=True, exist_ok=True)
    return path


async def save_admin_image(file: UploadFile) -> str:
    content_type = (file.content_type or "").lower()
    if content_type not in ALLOWED_IMAGE_TYPES:
        raise HTTPException(
            status_code=422,
            detail="نوع الصورة غير مدعوم. استخدم JPG أو PNG أو WebP",
        )

    content = await file.read()
    max_bytes = settings.UPLOAD_MAX_MB * 1024 * 1024
    if len(content) > max_bytes:
        raise HTTPException(
            status_code=422,
            detail=f"الصورة كبيرة جداً (الحد الأقصى {settings.UPLOAD_MAX_MB}MB)",
        )

    ext = ALLOWED_IMAGE_TYPES[content_type]
    filename = f"{uuid.uuid4().hex}{ext}"
    dest = upload_dir() / filename
    dest.write_bytes(content)

    base = settings.PUBLIC_API_URL.rstrip("/")
    return f"{base}/uploads/{filename}"
