"""Unit tests for order total recalculation."""
import pytest
from decimal import Decimal
from app.services.orders import recalculate_order, PRODUCT_CATALOG
from app.schemas import OrderItemIn


def make_item(product_id: str, offer_id: str, quantity: int = 1) -> OrderItemIn:
    product = PRODUCT_CATALOG[product_id]
    offer = product["offers"][offer_id]
    return OrderItemIn(
        product_id=product_id,
        product_name_ar=product["name_ar"],
        offer_id=offer_id,
        quantity=quantity,
        unit_count=offer["quantity"],
        price_mad=offer["price_mad"],
        source="pdp",
    )


def test_single_item_one_piece():
    items = [make_item("lutein-eye-glow-gummies", "one")]
    validated, total = recalculate_order(items)
    assert total == Decimal("199")


def test_single_item_three_pieces():
    items = [make_item("lutein-eye-glow-gummies", "three")]
    validated, total = recalculate_order(items)
    assert total == Decimal("349")


def test_upsell_item():
    items = [
        make_item("lutein-eye-glow-gummies", "three"),
        make_item("collagen-glow-gummies", "upsell"),
    ]
    validated, total = recalculate_order(items)
    assert total == Decimal("448")


def test_multi_product():
    items = [
        make_item("collagen-glow-gummies", "two"),
        make_item("chlorophyll-gummies", "one"),
    ]
    validated, total = recalculate_order(items)
    assert total == Decimal("478")


def test_unknown_product_raises():
    items = [
        OrderItemIn(
            product_id="unknown-product",
            product_name_ar="مجهول",
            offer_id="one",
            quantity=1,
            unit_count=1,
            price_mad=Decimal("199"),
            source="pdp",
        )
    ]
    with pytest.raises(ValueError, match="منتج غير معروف"):
        recalculate_order(items)


def test_server_ignores_frontend_price():
    """Server must always recalculate, ignoring frontend price."""
    items = [
        OrderItemIn(
            product_id="collagen-glow-gummies",
            product_name_ar="علكات الكولاجين",
            offer_id="three",
            quantity=1,
            unit_count=3,
            price_mad=Decimal("1"),
            source="pdp",
        )
    ]
    validated, total = recalculate_order(items)
    assert total == Decimal("349")
