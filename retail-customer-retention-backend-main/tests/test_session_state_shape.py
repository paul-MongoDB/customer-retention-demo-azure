#!/usr/bin/env python3
"""Contract test: generator's session_state shape must match asp1 output.

Run from the backend root: python -m tests.test_session_state_shape
Or directly: python tests/test_session_state_shape.py

Validates that build_session_state() produces a document whose field shape
and types match what asp1_session_state_builder writes. If asp1 logic
changes, update REFERENCE_SHAPE below (captured from a real asp1-produced
doc) and this test will catch generator drift.
"""

import os
import sys
from datetime import datetime, timedelta

# Make the backend root importable when this file is run directly.
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from generate_demo_data import build_session_state


# Captured from a live asp1-produced session_state document. Each leaf holds
# the expected Python type (or a tuple of acceptable types). Dicts nest.
# Lists hold exactly one element: the expected shape of each list item.
REFERENCE_SHAPE = {
    "userId": str,
    "sessionId": str,
    "firstSeen": datetime,
    "lastSeen": datetime,
    "lastEvent": {
        "event": str,
        "ts": datetime,
    },
    "last10s": {
        "intent": {
            "products": [{
                "productId": str,
                "searchCount": int,
                "viewCount": int,
                "addToCartCount": int,
                "weight": int,
                "focus": (int, float),
            }],
            "articleTypes": [{
                "articleType": str,
                "searchCount": int,
                "viewCount": int,
                "addToCartCount": int,
                "weight": int,
                "focus": (int, float),
            }],
            "subCategories": [{
                "subCategory": str,
                "searchCount": int,
                "viewCount": int,
                "addToCartCount": int,
                "weight": int,
                "focus": (int, float),
            }],
            "dimensionTotals": {
                "productWeightTotal": int,
                "articleTypeWeightTotal": int,
                "subCategoryWeightTotal": int,
            },
        },
        "lastEvent": {
            "event": str,
            "ts": datetime,
        },
        "window": {
            "start": datetime,
            "end": datetime,
        },
    },
    "searchHistory": [str],
    "sessionTotals": {
        "eventCounts": {
            "heartbeat": int,
            "search": int,
            "view-product": int,
            "add-to-cart": int,
            "exit-risk": int,
        },
        "windowCount": int,
    },
    "_demo_source": str,
}


def _fmt(path):
    return ".".join(path) if path else "<root>"


def validate(doc, shape, path=None):
    """Recursively validate doc against shape. Returns list of error messages."""
    path = path or []
    errors = []

    if isinstance(shape, dict):
        if not isinstance(doc, dict):
            errors.append(f"{_fmt(path)}: expected dict, got {type(doc).__name__}")
            return errors
        for key, sub_shape in shape.items():
            if key not in doc:
                errors.append(f"{_fmt(path + [key])}: missing field")
                continue
            errors.extend(validate(doc[key], sub_shape, path + [key]))
        extra = set(doc.keys()) - set(shape.keys())
        for key in sorted(extra):
            errors.append(f"{_fmt(path + [key])}: unexpected field not in reference shape")
        return errors

    if isinstance(shape, list):
        if not isinstance(doc, list):
            errors.append(f"{_fmt(path)}: expected list, got {type(doc).__name__}")
            return errors
        item_shape = shape[0]
        for i, item in enumerate(doc):
            errors.extend(validate(item, item_shape, path + [f"[{i}]"]))
        return errors

    # Leaf: shape is a type or tuple of types
    if not isinstance(doc, shape):
        expected = shape.__name__ if isinstance(shape, type) else "/".join(t.__name__ for t in shape)
        errors.append(f"{_fmt(path)}: expected {expected}, got {type(doc).__name__}")
    return errors


def build_sample_events():
    """Build a realistic event sequence spanning multiple 10s windows."""
    base = datetime(2026, 4, 21, 12, 0, 0)
    uid, sid = "user-1", "sess-1"

    def ev(name, t_offset, metadata=None):
        return {
            "tags": {"userId": uid, "sessionId": sid, "event": name},
            "timestamp": base + timedelta(seconds=t_offset),
            "metadata": metadata or {},
        }

    # Spread across 3 distinct 10s windows to exercise windowCount > 1.
    return [
        ev("heartbeat", 0),
        ev("search", 3, {
            "query": "running shoes",
            "productId": "p1", "articleType": "Shoes", "subCategory": "Footwear",
        }),
        ev("view-product", 8, {
            "productId": "p1", "articleType": "Shoes", "subCategory": "Footwear",
        }),
        ev("heartbeat", 12),
        ev("view-product", 15, {
            "productId": "p2", "articleType": "Shoes", "subCategory": "Footwear",
        }),
        ev("add-to-cart", 22, {
            "productId": "p1", "articleType": "Shoes", "subCategory": "Footwear",
        }),
        ev("exit-risk", 28, {"exitMethod": "logout-hover"}),
    ]


def main():
    events = build_sample_events()
    doc = build_session_state("user-1", "sess-1", events, "test")

    if doc is None:
        print("FAIL: build_session_state returned None")
        sys.exit(1)

    errors = validate(doc, REFERENCE_SHAPE)

    # Spot-check values that would catch logic drift.
    value_errors = []
    totals = doc["sessionTotals"]["eventCounts"]
    if totals["heartbeat"] != 2: value_errors.append(f"heartbeat count: {totals['heartbeat']} != 2")
    if totals["search"] != 1: value_errors.append(f"search count: {totals['search']} != 1")
    if totals["view-product"] != 2: value_errors.append(f"view-product count: {totals['view-product']} != 2")
    if totals["add-to-cart"] != 1: value_errors.append(f"add-to-cart count: {totals['add-to-cart']} != 1")
    if totals["exit-risk"] != 1: value_errors.append(f"exit-risk count: {totals['exit-risk']} != 1")
    if doc["sessionTotals"]["windowCount"] != 3:
        value_errors.append(f"windowCount: {doc['sessionTotals']['windowCount']} != 3 (events span 3 windows)")
    # Priority fix: exit-risk must win as lastEvent of its 10s window (20-30s), not heartbeat.
    if doc["last10s"]["lastEvent"]["event"] != "exit-risk":
        value_errors.append(f"last10s.lastEvent should be exit-risk (priority fix), got {doc['last10s']['lastEvent']['event']}")

    if errors or value_errors:
        print("FAIL: session_state shape/value contract broken")
        for e in errors: print(f"  SHAPE: {e}")
        for e in value_errors: print(f"  VALUE: {e}")
        sys.exit(1)

    print("PASS: session_state shape and value contract satisfied")
    print(f"  {len(doc)} top-level fields, {doc['sessionTotals']['windowCount']} windows, {sum(totals.values())} events counted")


if __name__ == "__main__":
    main()
