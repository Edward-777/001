"""inventory.service — product master (M3). Stock/inbound/outbound in M7."""
from __future__ import annotations

from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.orm import Session

from .models import Product, ProductCategory, ProductType


def create_category(
    session: Session, *, name: str, parent_id: int | None = None
) -> ProductCategory:
    cat = ProductCategory(name=name, parent_id=parent_id)
    session.add(cat)
    session.flush()
    return cat


def create_product(
    session: Session,
    *,
    sku: str,
    name: str,
    type: ProductType = ProductType.INVENTORY,
    model_name: str | None = None,
    track_serial: bool = False,
    unit: str = "ea",
    category_id: int | None = None,
    standard_cost: Decimal | float | None = None,
) -> Product:
    p = Product(
        sku=sku,
        name=name,
        type=str(type),
        model_name=model_name,
        track_serial=track_serial,
        unit=unit,
        category_id=category_id,
        standard_cost=Decimal(str(standard_cost)) if standard_cost is not None else None,
    )
    session.add(p)
    session.flush()
    return p


def get_product(session: Session, product_id: int) -> Product | None:
    return session.get(Product, product_id)


def get_product_by_sku(session: Session, sku: str) -> Product | None:
    return session.scalar(select(Product).where(Product.sku == sku))
