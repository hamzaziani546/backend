from pydantic import BaseModel, field_validator
from typing import Optional
from decimal import Decimal
import re


class CustomerIn(BaseModel):
    name: str
    phone: str
    city: str = ""
    address: str = ""

    @field_validator("name")
    @classmethod
    def validate_name(cls, v: str) -> str:
        v = v.strip()
        if len(v) < 3:
            raise ValueError("الاسم قصير جداً")
        return v

    @field_validator("city")
    @classmethod
    def validate_city(cls, v: str) -> str:
        v = v.strip()
        if len(v) < 2:
            raise ValueError("اختاري المدينة")
        return v

    @field_validator("address")
    @classmethod
    def validate_address(cls, v: str) -> str:
        v = v.strip()
        if len(v) < 5:
            raise ValueError("اكتبي العنوان الكامل للتوصيل")
        return v

    @field_validator("phone")
    @classmethod
    def validate_phone_format(cls, v: str) -> str:
        v = v.strip()
        if not v:
            raise ValueError("رقم الجوال مطلوب")
        return v


class OrderItemIn(BaseModel):
    product_id: str
    product_name_ar: str
    offer_id: str
    quantity: int = 1
    unit_count: int = 1
    price_mad: Decimal
    source: str = "pdp"


class AttributionIn(BaseModel):
    landing_page: Optional[str] = None
    utm_source: Optional[str] = None
    utm_medium: Optional[str] = None
    utm_campaign: Optional[str] = None
    utm_content: Optional[str] = None
    utm_term: Optional[str] = None
    fbp: Optional[str] = None
    fbc: Optional[str] = None
    ttp: Optional[str] = None
    ttclid: Optional[str] = None
    sc_click_id: Optional[str] = None
    sc_cookie1: Optional[str] = None  # value of _scid cookie → sc_cookie1 in Snap CAPI


class OrderCreateRequest(BaseModel):
    customer: CustomerIn
    items: list[OrderItemIn]
    attribution: Optional[AttributionIn] = None


class OrderCreateResponse(BaseModel):
    order_id: str
    order_number: str
    event_id: str
    total_mad: Decimal
    currency: str


class OrderItemOut(BaseModel):
    product_id: str
    product_name_ar: str
    offer_id: str
    quantity: int
    unit_count: int
    price_mad: Decimal
    source: str

    model_config = {"from_attributes": True}


class OrderOut(BaseModel):
    order_id: str
    order_number: str
    status: str
    customer_name: str
    total_mad: Decimal
    currency: str
    payment_method: str
    items: list[OrderItemOut]
    created_at: str

    model_config = {"from_attributes": True}
