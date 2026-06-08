import json
import re
import uuid
from decimal import Decimal
from typing import Any

from sqlalchemy.orm import Session

from app.models import LandingPage

SLUG_RE = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")


def normalize_slug(raw: str) -> str:
    slug = raw.strip().lower()
    slug = re.sub(r"[^a-z0-9-]+", "-", slug)
    slug = re.sub(r"-{2,}", "-", slug).strip("-")
    if not slug or not SLUG_RE.match(slug):
        raise ValueError("الرابط يجب أن يحتوي على حروف إنجليزية صغيرة وأرقام وشرطات فقط")
    return slug


def parse_gallery_images(raw: str | list[str] | None) -> list[str]:
    if raw is None:
        return []
    if isinstance(raw, list):
        return [str(u).strip() for u in raw if str(u).strip()]
    text = raw.strip()
    if not text:
        return []
    if text.startswith("["):
        data = json.loads(text)
        if not isinstance(data, list):
            raise ValueError("صور المعرض يجب أن تكون قائمة")
        return [str(u).strip() for u in data if str(u).strip()]
    return [line.strip() for line in text.splitlines() if line.strip()]


def dump_gallery_images(images: list[str]) -> str:
    return json.dumps(images, ensure_ascii=False)


def _load_products_list(raw: str | list[dict] | None) -> list[dict]:
    if raw is None:
        return []
    if isinstance(raw, list):
        items = raw
    else:
        text = (raw or "").strip()
        if not text:
            return []
        items = json.loads(text)
    if not isinstance(items, list):
        raise ValueError("المنتجات يجب أن تكون قائمة")
    return items


def parse_lp_products(raw: str | list[dict] | None, *, require_one: bool = True) -> list[dict]:
    items = _load_products_list(raw)
    if require_one and not items:
        raise ValueError("أضيفي منتجاً واحداً على الأقل")

    parsed = []
    seen_ids: set[str] = set()
    seen_skus: set[str] = set()
    for i, item in enumerate(items):
        if not isinstance(item, dict):
            raise ValueError("صيغة المنتج غير صالحة")
        name_ar = str(item.get("name_ar", "")).strip()
        sku = str(item.get("sku", "")).strip().upper()
        image = str(item.get("image", "")).strip()
        offer_id = str(item.get("id", "")).strip() or f"p{i + 1}"
        try:
            price_mad = Decimal(str(item.get("price_mad", 0)))
        except Exception as exc:
            raise ValueError("السعر غير صالح") from exc
        compare_raw = item.get("compare_at_price_mad")
        compare_at = None
        if compare_raw not in (None, "", 0, "0"):
            try:
                compare_at = Decimal(str(compare_raw))
            except Exception as exc:
                raise ValueError("سعر المقارنة غير صالح") from exc

        if not name_ar:
            raise ValueError("اسم المنتج مطلوب")
        if not sku:
            raise ValueError("SKU مطلوب")
        if not image:
            raise ValueError("صورة المنتج مطلوبة")
        if price_mad <= 0:
            raise ValueError("السعر يجب أن يكون أكبر من صفر")
        if offer_id in seen_ids:
            raise ValueError(f"معرّف مكرر: {offer_id}")
        if sku in seen_skus:
            raise ValueError(f"SKU مكرر: {sku}")
        seen_ids.add(offer_id)
        seen_skus.add(sku)

        parsed.append(
            {
                "id": offer_id,
                "name_ar": name_ar,
                "price_mad": float(price_mad),
                "compare_at_price_mad": float(compare_at) if compare_at else None,
                "image": image,
                "sku": sku,
            }
        )
    return parsed


def dump_lp_products(products: list[dict]) -> str:
    return json.dumps(products, ensure_ascii=False)


def serialize_landing_page(lp: Any, *, include_admin: bool = False) -> dict:
    gallery = parse_gallery_images(lp.gallery_images_json)
    products = parse_lp_products(getattr(lp, "offers_json", None) or "[]", require_one=False)

    data = {
        "slug": lp.slug,
        "title_ar": lp.title_ar,
        "hero_image": lp.hero_image,
        "rating": float(lp.rating),
        "review_count": int(lp.review_count),
        "gallery_images": gallery,
        "products": products,
    }
    if include_admin:
        data.update(
            {
                "id": str(lp.id),
                "is_active": bool(lp.is_active),
                "url_path": f"/lp/{lp.slug}",
                "created_at": lp.created_at.isoformat(),
                "updated_at": lp.updated_at.isoformat(),
            }
        )
    return data


def resolve_lp_cart_item(item: Any, db: Session) -> dict:
    source = (item.source or "").strip()
    parts = source.split(":")
    if len(parts) < 2 or parts[0] != "lp":
        raise ValueError("مصدر LP غير صالح")

    slug = parts[1]
    offer_id = parts[2] if len(parts) > 2 else str(item.offer_id)

    lp = (
        db.query(LandingPage)
        .filter(LandingPage.slug == slug, LandingPage.is_active.is_(True))
        .first()
    )
    if not lp:
        raise ValueError("صفحة الهبوط غير موجودة أو غير نشطة")

    products = parse_lp_products(lp.offers_json)
    offer = next((p for p in products if p["id"] == offer_id), None)
    if not offer:
        raise ValueError("المنتج غير موجود في صفحة الهبوط")

    line_price = Decimal(str(offer["price_mad"])) * item.quantity
    return {
        "product_id": f"lp-{offer['sku']}",
        "product_name_ar": offer["name_ar"],
        "sku": offer["sku"],
        "offer_id": offer_id,
        "quantity": item.quantity,
        "unit_count": item.quantity,
        "price_mad": line_price,
        "source": source,
    }


def new_product_id() -> str:
    return f"p{uuid.uuid4().hex[:8]}"
