"""
products_router.py — 套餐 SKU 列表接口

路由：
  GET /api/v1/products  — 列出 active 产品（游客可访问）
"""

import os
import json
import sqlite3
from typing import Optional

from fastapi import APIRouter, HTTPException, Request

router = APIRouter(tags=["Products"])

_THIS_DIR = os.path.dirname(os.path.abspath(__file__))
DB_PATH = os.environ.get("DB_PATH", os.path.join(_THIS_DIR, "football_uk.db"))


def _get_conn() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH, timeout=10)
    conn.row_factory = sqlite3.Row
    return conn


@router.get("/products")
async def list_products(type: Optional[str] = None):
    """
    列出所有 is_active=1 的产品 SKU。
    可选 type 过滤：single_match | package
    """
    conn = _get_conn()
    try:
        if type is not None:
            rows = conn.execute(
                "SELECT * FROM products WHERE is_active=1 AND type=? ORDER BY id",
                (type,)
            ).fetchall()
        else:
            rows = conn.execute(
                "SELECT * FROM products WHERE is_active=1 ORDER BY id"
            ).fetchall()
    finally:
        conn.close()

    products = []
    for r in rows:
        try:
            meta = json.loads(r["metadata"] or "{}")
        except (json.JSONDecodeError, TypeError):
            meta = {}
        products.append({
            "id":          r["id"],
            "sku":         r["sku"],
            "name":        r["name"],
            "type":        r["type"],
            "price_cents": r["price_cents"],
            "price_yuan":  round(r["price_cents"] / 100, 2),
            "currency":    r["currency"],
            "metadata":    meta,
        })

    return {"products": products}
