#!/usr/bin/env python3
"""
Demo data generator for the Leafy customer retention demo.

Two modes:
  --mode baseline   ~200 users, timestamps spread over past 7 days
  --mode burst      ~20-30 new users, timestamps in the last 1-5 minutes

Writes to: events_ingest, session_signals, next_best_actions, session_state
Reads from: products (to reference real product IDs)

Usage:
  python generate_demo_data.py --mode baseline
  python generate_demo_data.py --mode burst
  python generate_demo_data.py --mode baseline --clear  # clear existing demo data first
"""

import argparse
import os
import random
import uuid
from datetime import datetime, timedelta

from bson import ObjectId
from dotenv import load_dotenv
from pymongo import MongoClient

load_dotenv()

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

MONGODB_URI = os.environ["MONGODB_URI"]
DB_NAME = os.environ.get("DATABASE_NAME", "leafy_popup_store")

SESSION_SIGNALS_COLLECTION = "session_signals"
NEXT_BEST_ACTION_COLLECTION = "next_best_actions"
SESSION_STATE_COLLECTION = "session_state"
EVENTS_INGEST_COLLECTION = "events_ingest"
PRODUCTS_COLLECTION = "products"
CHURN_RISK_SCORES_COLLECTION = "churn_risk_scores"
CARTS_COLLECTION = "carts"

BASELINE_USER_COUNT = 200
BURST_USER_COUNT = 25

# ---------------------------------------------------------------------------
# User archetypes
# ---------------------------------------------------------------------------

ARCHETYPES = {
    "loyal_shopper": {
        "weight": 0.25,
        "signals": {"high-intent": 0.60, "search-friction": 0.10, "exit-risk": 0.30},
        "signal_count": (8, 20),
        "redeem_rate": (0.60, 0.80),
        "sessions": (2, 5),
    },
    "window_shopper": {
        "weight": 0.20,
        "signals": {"high-intent": 0.20, "search-friction": 0.50, "exit-risk": 0.30},
        "signal_count": (5, 15),
        "redeem_rate": (0.10, 0.20),
        "sessions": (1, 3),
    },
    "bouncing_visitor": {
        "weight": 0.20,
        "signals": {"high-intent": 0.10, "search-friction": 0.10, "exit-risk": 0.80},
        "signal_count": (3, 8),
        "redeem_rate": (0.00, 0.10),
        "sessions": (1, 2),
    },
    "discount_hunter": {
        "weight": 0.15,
        "signals": {"high-intent": 0.15, "search-friction": 0.35, "exit-risk": 0.50},
        "signal_count": (6, 16),
        "redeem_rate": (0.40, 0.60),
        "sessions": (2, 4),
    },
    "engaged_browser": {
        "weight": 0.20,
        "signals": {"high-intent": 0.40, "search-friction": 0.35, "exit-risk": 0.25},
        "signal_count": (6, 18),
        "redeem_rate": (0.30, 0.50),
        "sessions": (2, 5),
    },
}

# ---------------------------------------------------------------------------
# Evidence templates
# ---------------------------------------------------------------------------

HIGH_INTENT_EVIDENCE = [
    "Customer viewed {product} {n} times in the last {m} minutes and added it to their wishlist",
    "Repeated views on {product} with prolonged engagement, suggesting strong purchase intent",
    "User showed focused attention on {product}, spending over {m} minutes on the product page",
    "Customer returned to {product} across {n} page visits, indicating high purchase likelihood",
    "Strong engagement signals: {n} views of {product} with image zoom and size selection",
    "User compared {product} with similar items {n} times, showing active decision-making",
    "Customer spent {m} minutes examining {product} details and reading reviews",
]

SEARCH_FRICTION_EVIDENCE = [
    "User searched for '{query}' with no clear results, browsing {n} products without convergence",
    "Multiple searches for '{query}' variants with scattered attention across categories",
    "Customer explored {n} products after searching '{query}' but showed no add-to-cart intent",
    "Repeated search refinements around '{query}' suggest difficulty finding the right product",
    "User browsed {n} items across multiple categories after searching '{query}', no clear direction",
    "Search pattern indicates frustration: '{query}' followed by {n} rapid page changes",
    "Low-confidence browsing after '{query}' search, no product engagement beyond initial view",
]

EXIT_RISK_EVIDENCE = [
    "Customer idle for {n} seconds after viewing {m} products, cursor moved toward browser close",
    "Tab switch detected after {m} minutes of browsing, engagement dropping rapidly",
    "User scrolled to page bottom and stopped interacting for {n} seconds",
    "Rapid page navigation without product interaction, {m} pages in {n} seconds",
    "Cart abandoned after {n} seconds of inactivity, no further product views",
    "User showed decreasing engagement over {m} minutes with no add-to-cart actions",
    "Mouse movement toward exit zone detected after {n} seconds of idle browsing",
]

# ---------------------------------------------------------------------------
# Search queries for search-friction signals
# ---------------------------------------------------------------------------

SEARCH_QUERIES = [
    "running shoes", "summer dress", "leather jacket", "cotton t-shirt",
    "winter coat", "hiking boots", "yoga pants", "denim jeans",
    "silk blouse", "casual sneakers", "formal shirt", "rain jacket",
    "workout shorts", "linen pants", "wool sweater", "canvas bag",
    "sandals", "polo shirt", "down vest", "baseball cap",
    "bath towels", "shower curtain", "bed sheets", "kitchen organizer",
    "desk lamp", "storage bins", "hangers", "bathroom accessories",
]

TOPIC_DIMENSIONS = [
    {"dimension": "articleType", "values": ["Shoes", "Dress", "Shirt", "Jacket", "Pants"]},
    {"dimension": "color", "values": ["Black", "Blue", "Red", "White", "Green", "Beige"]},
    {"dimension": "subCategory", "values": ["Bath", "Hardware", "Nursery", "Home Furnishing", "Accessories"]},
]

# ---------------------------------------------------------------------------
# Exit method types for exit-risk events
# ---------------------------------------------------------------------------

EXIT_METHODS = ["logout-hover", "tab-switch", "idle-timeout", "back-button", "close-button"]

# ---------------------------------------------------------------------------
# NBA message templates
# ---------------------------------------------------------------------------

SOCIAL_PROOF_TITLES = ["Popular Right Now", "Trending Pick", "Good Choice", "Hot Item", "Customers Love This"]
SOCIAL_PROOF_MESSAGES = [
    "{n} customers purchased {category} recently.",
    "This {category} item is trending with {n} purchases this week.",
    "{n} shoppers added {category} items to their cart today.",
    "Popular choice! {n} customers bought from {category} recently.",
    "Trending: {n} purchases in {category} in the last hour.",
]

SOCIAL_PROOF_EMBED_MESSAGES = [
    "This item is trending",
    "High demand item",
    "Popular with shoppers",
    "Selling fast",
    "Customer favorite",
]

DISCOUNT_TITLES = ["Special Offer", "Just For You", "Personalized Deal", "Smart Match", "We Found Something"]
DISCOUNT_MESSAGES = [
    "Based on your interests, get 10% off {product} today!",
    "We think you'll love {product}. Enjoy 15% off!",
    "Personalized pick: {product} at 20% off for a limited time.",
    "Your browsing led us here: {product} with a special discount.",
    "Found what you need? Get {product} at a special price today!",
]

SHIPPING_DISCOUNT_CONFIG = {
    "low": {
        "titles": ["Before you go", "Wait a moment"],
        "messages": [
            "Get 5% off your shipping if you complete your purchase today.",
            "Save 5% on shipping costs when you finish your order.",
        ],
    },
    "medium": {
        "titles": ["Don't miss out", "Limited time offer"],
        "messages": [
            "Complete your order now and get 15% off shipping.",
            "Finish your purchase today and save 15% on shipping costs.",
        ],
    },
    "high": {
        "titles": ["Wait! Special offer", "Exclusive deal"],
        "messages": [
            "Complete your order now and get 50% off shipping!",
            "Huge savings: 50% off shipping if you complete your purchase now.",
        ],
    },
    "urgent": {
        "titles": ["Last chance", "Final offer"],
        "messages": [
            "Complete your order now and get FREE shipping!",
            "Don't wait - finish your purchase and enjoy FREE shipping!",
        ],
    },
}

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def random_uid():
    return str(ObjectId())


def random_sid():
    return str(uuid.uuid4())


def pick_severity(signal_type):
    """Pick severity with realistic distribution per signal type."""
    if signal_type == "exit-risk":
        return random.choices(
            ["low", "medium", "high", "urgent"],
            weights=[0.20, 0.30, 0.30, 0.20],
        )[0]
    elif signal_type == "search-friction":
        return random.choices(
            ["low", "medium", "high", "urgent"],
            weights=[0.25, 0.35, 0.30, 0.10],
        )[0]
    else:  # high-intent
        return random.choices(
            ["low", "medium", "high", "urgent"],
            weights=[0.15, 0.30, 0.40, 0.15],
        )[0]


def generate_timestamp(mode, session_offset_minutes=0):
    """Generate a timestamp appropriate for the mode."""
    now = datetime.utcnow()
    if mode == "burst":
        # Last 1-5 minutes
        offset = random.uniform(60, 300) - session_offset_minutes * 60
        return now - timedelta(seconds=max(offset, 10))
    else:
        # Past 7 days with business-hour weighting
        days_ago = random.uniform(0, 7)
        base = now - timedelta(days=days_ago)
        # Bias toward business hours (9am-6pm)
        hour = random.gauss(13, 3)
        hour = max(6, min(23, int(hour)))
        return base.replace(hour=hour, minute=random.randint(0, 59), second=random.randint(0, 59))


def generate_evidence(signal_type, product_name=None, query=None):
    """Generate realistic evidence text for a signal."""
    n = random.randint(2, 12)
    m = random.randint(2, 15)

    if signal_type == "high-intent":
        template = random.choice(HIGH_INTENT_EVIDENCE)
        return template.format(product=product_name or "a product", n=n, m=m)
    elif signal_type == "search-friction":
        template = random.choice(SEARCH_FRICTION_EVIDENCE)
        return template.format(query=query or "items", n=n)
    else:  # exit-risk
        template = random.choice(EXIT_RISK_EVIDENCE)
        return template.format(n=n * 5, m=m)


def generate_raw_events(signal_type, uid, sid, product, query, ts, products, mode):
    """Generate realistic raw events_ingest documents leading up to a signal.

    The real app streams these via the UI. Each signal is preceded by a
    sequence of browsing events that would realistically trigger it.

    Event schema matches frontend generateTimeSeriesEvent():
    {
      tags: { userId, sessionId, event },
      timestamp: Date,
      metadata: { ... per event type }
    }
    """
    events = []

    def make_event(event_name, metadata, event_ts):
        return {
            "tags": {
                "userId": uid,
                "sessionId": sid,
                "event": event_name,
            },
            "timestamp": event_ts,
            "metadata": metadata,
            "_demo_source": mode,
        }

    # Always generate a few heartbeats before the signal
    num_heartbeats = random.randint(2, 6)
    for i in range(num_heartbeats):
        heartbeat_ts = ts - timedelta(seconds=(num_heartbeats - i) * 10)
        events.append(make_event("heartbeat", {}, heartbeat_ts))

    if signal_type == "high-intent":
        # Multiple product views, possibly an add-to-cart
        num_views = random.randint(3, 8)
        for i in range(num_views):
            view_product = product if product else random.choice(products) if products else None
            if view_product:
                view_ts = ts - timedelta(seconds=(num_views - i) * random.randint(8, 30))
                events.append(make_event("view-product", {
                    "productId": str(view_product["_id"]),
                    "subCategory": view_product.get("subCategory", ""),
                    "articleType": view_product.get("articleType", ""),
                    "brand": view_product.get("brand", ""),
                }, view_ts))

        # Some high-intent users also add to cart
        if product and random.random() < 0.4:
            cart_ts = ts - timedelta(seconds=random.randint(2, 10))
            events.append(make_event("add-to-cart", {
                "productId": str(product["_id"]),
                "subCategory": product.get("subCategory", ""),
                "articleType": product.get("articleType", ""),
                "brand": product.get("brand", ""),
            }, cart_ts))

    elif signal_type == "search-friction":
        # Multiple searches with product views scattered between
        num_searches = random.randint(2, 5)
        search_queries = random.sample(SEARCH_QUERIES, min(num_searches, len(SEARCH_QUERIES)))
        for i, sq in enumerate(search_queries):
            search_ts = ts - timedelta(seconds=(num_searches - i) * random.randint(15, 45))
            search_product = random.choice(products) if products else None
            events.append(make_event("search", {
                "query": sq,
                "productId": str(search_product["_id"]) if search_product else None,
                "subCategory": search_product.get("subCategory", "") if search_product else None,
                "articleType": search_product.get("articleType", "") if search_product else None,
                "brand": search_product.get("brand", "") if search_product else None,
            }, search_ts))

            # A couple of product views after each search
            for j in range(random.randint(1, 3)):
                view_product = random.choice(products) if products else None
                if view_product:
                    view_ts = search_ts + timedelta(seconds=random.randint(3, 12))
                    events.append(make_event("view-product", {
                        "productId": str(view_product["_id"]),
                        "subCategory": view_product.get("subCategory", ""),
                        "articleType": view_product.get("articleType", ""),
                        "brand": view_product.get("brand", ""),
                    }, view_ts))

    elif signal_type == "exit-risk":
        # A few product views followed by inactivity / exit method
        num_views = random.randint(1, 4)
        for i in range(num_views):
            view_product = random.choice(products) if products else None
            if view_product:
                view_ts = ts - timedelta(seconds=(num_views - i) * random.randint(10, 25))
                events.append(make_event("view-product", {
                    "productId": str(view_product["_id"]),
                    "subCategory": view_product.get("subCategory", ""),
                    "articleType": view_product.get("articleType", ""),
                    "brand": view_product.get("brand", ""),
                }, view_ts))

        # The exit-risk event itself
        exit_ts = ts - timedelta(seconds=random.randint(1, 5))
        events.append(make_event("exit-risk", {
            "exitMethod": random.choice(EXIT_METHODS),
        }, exit_ts))

    # Sort by timestamp
    events.sort(key=lambda e: e["timestamp"])
    return events


def pick_archetype():
    """Randomly select an archetype based on weights."""
    names = list(ARCHETYPES.keys())
    weights = [ARCHETYPES[n]["weight"] for n in names]
    return random.choices(names, weights=weights)[0]


# ---------------------------------------------------------------------------
# session_state builder -- mirrors asp1_session_state_builder output
# ---------------------------------------------------------------------------

# Weight table matches the $switch in asp1 ($addFields stage).
EVENT_WEIGHTS = {"search": 1, "view-product": 3, "add-to-cart": 7}

# Events that asp1 counts toward sessionTotals.eventCounts.
COUNTED_EVENTS = ("heartbeat", "search", "view-product", "add-to-cart", "exit-risk")


def _event_priority(event_name):
    # Mirrors the _eventPriority field in asp1: exit-risk wins as lastEvent in its window.
    return 1 if event_name == "exit-risk" else 0


def compute_intent(window_events):
    """Mirrors the $function body in asp1's tumbling window pipeline.

    Aggregates per-product, per-articleType, and per-subCategory stats for the
    events in a single 10-second window, then computes focus = weight / total.
    """
    products_by_id = {}
    articles_by_type = {}
    subcats_by_name = {}
    product_weight_total = 0
    article_type_weight_total = 0
    subcategory_weight_total = 0

    for e in window_events:
        event = e["tags"]["event"]
        w = EVENT_WEIGHTS.get(event, 0)
        if w <= 0:
            continue

        meta = e.get("metadata") or {}
        pid = meta.get("productId")
        at = meta.get("articleType")
        sc = meta.get("subCategory")

        if pid:
            r = products_by_id.setdefault(pid, {
                "productId": pid,
                "searchCount": 0, "viewCount": 0, "addToCartCount": 0, "weight": 0,
            })
            if event == "search": r["searchCount"] += 1
            elif event == "view-product": r["viewCount"] += 1
            elif event == "add-to-cart": r["addToCartCount"] += 1
            r["weight"] += w
            product_weight_total += w

        if at:
            r = articles_by_type.setdefault(at, {
                "articleType": at,
                "searchCount": 0, "viewCount": 0, "addToCartCount": 0, "weight": 0,
            })
            if event == "search": r["searchCount"] += 1
            elif event == "view-product": r["viewCount"] += 1
            elif event == "add-to-cart": r["addToCartCount"] += 1
            r["weight"] += w
            article_type_weight_total += w

        if sc:
            r = subcats_by_name.setdefault(sc, {
                "subCategory": sc,
                "searchCount": 0, "viewCount": 0, "addToCartCount": 0, "weight": 0,
            })
            if event == "search": r["searchCount"] += 1
            elif event == "view-product": r["viewCount"] += 1
            elif event == "add-to-cart": r["addToCartCount"] += 1
            r["weight"] += w
            subcategory_weight_total += w

    def finalize(buckets, total):
        out = list(buckets.values())
        for r in out:
            r["focus"] = (r["weight"] / total) if total > 0 else 0
        return out

    return {
        "products": finalize(products_by_id, product_weight_total),
        "articleTypes": finalize(articles_by_type, article_type_weight_total),
        "subCategories": finalize(subcats_by_name, subcategory_weight_total),
        "dimensionTotals": {
            "productWeightTotal": product_weight_total,
            "articleTypeWeightTotal": article_type_weight_total,
            "subCategoryWeightTotal": subcategory_weight_total,
        },
    }


def build_session_state(uid, sid, events, mode):
    """Build a full-shape session_state document equivalent to what asp1 writes.

    The live pipeline groups events into 10s tumbling windows and merges the
    per-window aggregates into session_state. This function replays that
    grouping in Python so seed docs match production shape exactly.
    """
    if not events:
        return None

    events_sorted = sorted(events, key=lambda e: e["timestamp"])

    # Bucket into 10s windows aligned to epoch, same as asp1 boundary=eventTime.
    windows = {}
    event_counts = {name: 0 for name in COUNTED_EVENTS}
    for e in events_sorted:
        event_name = e["tags"]["event"]
        if event_name in event_counts:
            event_counts[event_name] += 1
        window_start_epoch = (int(e["timestamp"].timestamp()) // 10) * 10
        windows.setdefault(window_start_epoch, []).append(e)

    # Last (non-empty) window produces last10s.
    last_window_start = max(windows.keys())
    last_window_events = windows[last_window_start]
    last_window_end = datetime.utcfromtimestamp(last_window_start + 10)
    last_window_start_dt = datetime.utcfromtimestamp(last_window_start)

    # lastEvent within the last window: asp1 picks via $top with sortBy
    # {_eventPriority:-1, timestamp:-1} -- exit-risk wins, then latest timestamp.
    best = max(
        last_window_events,
        key=lambda e: (_event_priority(e["tags"]["event"]), e["timestamp"]),
    )
    last_event_obj = {
        "event": best["tags"]["event"],
        "ts": best["timestamp"],
    }

    # searchHistory: all non-empty metadata.query values across the whole session.
    search_history = [
        e.get("metadata", {}).get("query")
        for e in events_sorted
        if e["tags"]["event"] == "search" and e.get("metadata", {}).get("query")
    ]

    return {
        "userId": uid,
        "sessionId": sid,
        "firstSeen": events_sorted[0]["timestamp"],
        "lastSeen": events_sorted[-1]["timestamp"],
        "lastEvent": last_event_obj,
        "last10s": {
            "intent": compute_intent(last_window_events),
            "lastEvent": last_event_obj,
            "window": {"start": last_window_start_dt, "end": last_window_end},
        },
        "searchHistory": search_history,
        "sessionTotals": {
            "eventCounts": event_counts,
            "windowCount": len(windows),
        },
        "_demo_source": mode,
    }


def generate_nba(signal_type, severity, uid, sid, product, ts, should_redeem, mode):
    """Generate a next_best_action document matching the signal type."""
    triggered_by = f"{severity}_{signal_type}"

    if signal_type == "high-intent":
        nba = {
            "uid": uid,
            "sid": sid,
            "type": "social-proof-notification",
            "actionMetadata": {
                "title": random.choice(SOCIAL_PROOF_TITLES),
                "message": random.choice(SOCIAL_PROOF_MESSAGES).format(
                    n=random.randint(3, 25),
                    category=product.get("articleType", "this category") if product else "this category",
                ),
                "triggeredBySignal": triggered_by,
            },
            "ts": ts + timedelta(seconds=random.randint(1, 5)),
            "redeemed": should_redeem,
        }
        nba["_demo_source"] = mode
        # Add embedInProduct for some social proof NBAs
        if product and random.random() < 0.7:
            nba["embedInProduct"] = {
                "productId": str(product["_id"]),
                "message": random.choice(SOCIAL_PROOF_EMBED_MESSAGES),
            }
        return nba

    elif signal_type == "search-friction":
        nba = {
            "uid": uid,
            "sid": sid,
            "type": "discount-product-recommendation",
            "actionMetadata": {
                "title": random.choice(DISCOUNT_TITLES),
                "message": random.choice(DISCOUNT_MESSAGES).format(
                    product=product.get("name", "this product") if product else "this product"
                ),
                "triggeredBySignal": triggered_by,
            },
            "ts": ts + timedelta(seconds=random.randint(2, 8)),
            "redeemed": should_redeem,
        }
        nba["_demo_source"] = mode
        # Add product recommendation
        if product:
            nba["actionMetadata"]["productRecommendation"] = {
                "productId": str(product["_id"]),
                "name": product.get("name", ""),
                "imageUrl": product.get("image", {}).get("url", ""),
            }
        return nba

    else:  # exit-risk -> shipping-discount
        config = SHIPPING_DISCOUNT_CONFIG.get(severity, SHIPPING_DISCOUNT_CONFIG["low"])
        return {
            "uid": uid,
            "sid": sid,
            "type": "shipping-discount",
            "actionMetadata": {
                "title": random.choice(config["titles"]),
                "message": random.choice(config["messages"]),
                "triggeredBySignal": triggered_by,
            },
            "ts": ts + timedelta(seconds=random.randint(1, 3)),
            "redeemed": should_redeem,
            "_demo_source": mode,
        }


# ---------------------------------------------------------------------------
# Main generation logic
# ---------------------------------------------------------------------------


def load_products(db):
    """Load a sample of products from the collection."""
    products = list(
        db[PRODUCTS_COLLECTION].find(
            {},
            {"name": 1, "image.url": 1, "masterCategory": 1, "articleType": 1, "subCategory": 1, "brand": 1},
        ).limit(100)
    )
    if not products:
        print("WARNING: No products found in collection. NBAs will have generic references.")
        return []
    print(f"Loaded {len(products)} products for reference.")
    return products


def generate_users(mode, products):
    """Generate all demo data for the specified mode."""
    user_count = BASELINE_USER_COUNT if mode == "baseline" else BURST_USER_COUNT

    all_events = []
    all_signals = []
    all_nbas = []
    all_session_states = []

    for i in range(user_count):
        uid = random_uid()
        archetype_name = pick_archetype()
        archetype = ARCHETYPES[archetype_name]

        num_sessions = random.randint(*archetype["sessions"])
        total_signals = random.randint(*archetype["signal_count"])
        redeem_rate = random.uniform(*archetype["redeem_rate"])

        # Distribute signals across sessions
        signals_per_session = max(1, total_signals // num_sessions)

        for sess_idx in range(num_sessions):
            sid = random_sid()
            session_events = []

            # How many signals in this session
            if sess_idx == num_sessions - 1:
                # Last session gets remaining signals
                n_signals = total_signals - signals_per_session * (num_sessions - 1)
            else:
                n_signals = signals_per_session
            n_signals = max(1, n_signals)

            for sig_idx in range(n_signals):
                # Pick signal type based on archetype distribution
                signal_type = random.choices(
                    list(archetype["signals"].keys()),
                    weights=list(archetype["signals"].values()),
                )[0]

                severity = pick_severity(signal_type)
                product = random.choice(products) if products else None
                query = random.choice(SEARCH_QUERIES)

                ts = generate_timestamp(mode, session_offset_minutes=sig_idx * 0.5)

                # Build signal document
                signal = {
                    "uid": uid,
                    "sid": sid,
                    "signal": signal_type,
                    "severity": severity,
                    "evidence": generate_evidence(signal_type, product.get("name") if product else None, query),
                    "ts": ts,
                    "_demo_source": mode,
                }

                if signal_type == "high-intent" and product:
                    signal["productId"] = str(product["_id"])
                elif signal_type == "search-friction":
                    topic_dim = random.choice(TOPIC_DIMENSIONS)
                    signal["topic"] = {
                        "dimension": topic_dim["dimension"],
                        "value": random.choice(topic_dim["values"]),
                    }

                all_signals.append(signal)

                # Generate raw events leading up to this signal
                raw_events = generate_raw_events(signal_type, uid, sid, product, query, ts, products, mode)
                all_events.extend(raw_events)
                session_events.extend(raw_events)

                # Generate corresponding NBA
                should_redeem = random.random() < redeem_rate
                nba = generate_nba(signal_type, severity, uid, sid, product, ts, should_redeem, mode)
                all_nbas.append(nba)

            # Every session gets a full-shape session_state, built from its events.
            session_state = build_session_state(uid, sid, session_events, mode)
            if session_state:
                all_session_states.append(session_state)

    return all_events, all_signals, all_nbas, all_session_states


def generate_persona(uid, products):
    """Build a genuinely high-risk behavioral history for a specific real user id.

    This makes a selectable storefront user reliably high-risk so the churn model
    honestly scores them High: heavy exit-risk signals across two sessions with
    zero offer engagement (exit_risk_ratio = 1.0, engagement_rate = 0.0, which is
    exactly the trained churn label). Nothing is faked -- these are real signals
    and NBAs the model reads. Tagged _demo_source="persona" for clean removal.
    """
    mode = "persona"
    events, signals, nbas, session_states = [], [], [], []

    num_sessions = 2
    signals_per_session = 4  # 8 exit-risk signals total

    for sess_idx in range(num_sessions):
        sid = random_sid()
        session_events = []
        for sig_idx in range(signals_per_session):
            severity = pick_severity("exit-risk")
            product = random.choice(products) if products else None
            ts = generate_timestamp(mode, session_offset_minutes=sig_idx * 0.5)

            signals.append({
                "uid": uid,
                "sid": sid,
                "signal": "exit-risk",
                "severity": severity,
                "evidence": generate_evidence("exit-risk", product.get("name") if product else None, None),
                "ts": ts,
                "_demo_source": mode,
            })

            raw = generate_raw_events("exit-risk", uid, sid, product, None, ts, products, mode)
            events.extend(raw)
            session_events.extend(raw)

            # Offers shown but never redeemed -> engagement_rate 0.
            nbas.append(generate_nba("exit-risk", severity, uid, sid, product, ts, should_redeem=False, mode=mode))

        ss = build_session_state(uid, sid, session_events, mode)
        if ss:
            session_states.append(ss)

    return events, signals, nbas, session_states


def seed_persona(db, uid):
    """Seed the high-risk demo persona for a specific real user id, then leave its
    churn score empty so the enriched agent scores it live during the demo."""
    print(f"Seeding high-risk persona for uid {uid}...")
    # Remove any prior persona data for this user and its cached churn score.
    db[SESSION_SIGNALS_COLLECTION].delete_many({"_demo_source": "persona", "uid": uid})
    db[NEXT_BEST_ACTION_COLLECTION].delete_many({"_demo_source": "persona", "uid": uid})
    db[EVENTS_INGEST_COLLECTION].delete_many({"_demo_source": "persona", "tags.userId": uid})
    db[SESSION_STATE_COLLECTION].delete_many({"_demo_source": "persona", "userId": uid})
    db[CHURN_RISK_SCORES_COLLECTION].delete_many({"uid": uid})

    products = load_products(db)
    events, signals, nbas, session_states = generate_persona(uid, products)
    insert_data(db, events, signals, nbas, session_states)
    print(f"  Persona {uid}: {len(signals)} exit-risk signals, {len(nbas)} unredeemed offers, "
          f"{len(session_states)} sessions. No churn score written (the model scores live).")


def clear_demo_data(db):
    """Remove all documents from demo collections by dropping and recreating.

    Uses drop() instead of delete_many() to avoid generating thousands of
    individual delete events on the Change Stream, which would slow down
    the Fabric mirroring connector.
    """
    for col_name in [EVENTS_INGEST_COLLECTION, SESSION_SIGNALS_COLLECTION, NEXT_BEST_ACTION_COLLECTION, SESSION_STATE_COLLECTION, CHURN_RISK_SCORES_COLLECTION, CARTS_COLLECTION]:
        db[col_name].drop()
        db.create_collection(col_name)
        print(f"  Dropped and recreated {col_name}")

    # ASP1's $merge stage requires a unique index on sessionId to validate join uniqueness.
    db[SESSION_STATE_COLLECTION].create_index("sessionId", unique=True, name="sessionId_unique")
    print(f"  Recreated unique index sessionId_unique on {SESSION_STATE_COLLECTION}")


def insert_data(db, events, signals, nbas, session_states):
    """Bulk insert all generated data."""
    if events:
        db[EVENTS_INGEST_COLLECTION].insert_many(events)
        print(f"  Inserted {len(events)} events_ingest")

    if signals:
        db[SESSION_SIGNALS_COLLECTION].insert_many(signals)
        print(f"  Inserted {len(signals)} session_signals")

    if nbas:
        db[NEXT_BEST_ACTION_COLLECTION].insert_many(nbas)
        print(f"  Inserted {len(nbas)} next_best_actions")

    if session_states:
        db[SESSION_STATE_COLLECTION].insert_many(session_states)
        print(f"  Inserted {len(session_states)} session_state documents")


def print_summary(events, signals, nbas):
    """Print a summary of generated data."""
    signal_counts = {}
    for s in signals:
        signal_counts[s["signal"]] = signal_counts.get(s["signal"], 0) + 1

    nba_counts = {}
    redeemed_counts = {}
    for n in nbas:
        nba_counts[n["type"]] = nba_counts.get(n["type"], 0) + 1
        if n["redeemed"]:
            redeemed_counts[n["type"]] = redeemed_counts.get(n["type"], 0) + 1

    unique_uids = len(set(s["uid"] for s in signals))
    total_redeemed = sum(1 for n in nbas if n["redeemed"])

    print("\n" + "=" * 50)
    print("GENERATION SUMMARY")
    print("=" * 50)
    print(f"Users: {unique_uids}")
    print(f"Raw events: {len(events)}")
    print(f"Signals: {len(signals)}")
    for sig, count in sorted(signal_counts.items()):
        print(f"  {sig}: {count}")
    print(f"NBAs: {len(nbas)}")
    for nba_type, count in sorted(nba_counts.items()):
        redeemed = redeemed_counts.get(nba_type, 0)
        print(f"  {nba_type}: {count} ({redeemed} redeemed)")
    print(f"Overall engagement rate: {total_redeemed / len(nbas) * 100:.1f}%")
    print("=" * 50)


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------


def clean_burst_data(db):
    """Remove only burst-generated data, preserving baseline.

    Uses the _demo_source field to identify burst documents.
    Also removes churn_risk_scores (predictions written back from Fabric).
    """
    burst_filter = {"_demo_source": "burst"}
    for col_name in [EVENTS_INGEST_COLLECTION, SESSION_SIGNALS_COLLECTION, NEXT_BEST_ACTION_COLLECTION, SESSION_STATE_COLLECTION]:
        result = db[col_name].delete_many(burst_filter)
        print(f"  Removed {result.deleted_count} burst documents from {col_name}")

    # Also clear churn_risk_scores so the UI resets to "Awaiting..."
    if CHURN_RISK_SCORES_COLLECTION in db.list_collection_names():
        result = db[CHURN_RISK_SCORES_COLLECTION].delete_many({})
        print(f"  Cleared {result.deleted_count} documents from {CHURN_RISK_SCORES_COLLECTION}")


def main():
    parser = argparse.ArgumentParser(description="Generate demo data for Leafy retention demo")
    parser.add_argument("--mode", choices=["baseline", "burst"], help="Generation mode")
    parser.add_argument("--clear", action="store_true", help="Clear all demo data before generating (drops and recreates collections)")
    parser.add_argument("--clean-burst", action="store_true", help="Remove previous burst data and churn_risk_scores (for re-running the demo)")
    parser.add_argument("--persona-uid", help="Seed a genuinely high-risk history for this real user id (the demo persona), clear its churn score, then exit")
    args = parser.parse_args()

    if not args.mode and not args.persona_uid and not args.clean_burst:
        parser.error("provide --mode, --persona-uid, or --clean-burst")

    print(f"Connecting to MongoDB...")
    client = MongoClient(MONGODB_URI, tls=True, tlsAllowInvalidCertificates=True)
    db = client[DB_NAME]

    # Verify connection
    db.command("ping")
    print(f"Connected to database: {DB_NAME}")

    if args.clean_burst:
        print("Cleaning previous burst data...")
        clean_burst_data(db)
        if args.mode != "burst":
            client.close()
            print("\nBurst data cleaned. Done!")
            return

    if args.persona_uid:
        seed_persona(db, args.persona_uid)
        client.close()
        print("\nPersona seeded. Done!")
        return

    if args.clear:
        print("Clearing all demo data...")
        clear_demo_data(db)

    # Load products for reference
    products = load_products(db)

    # Generate data
    print(f"\nGenerating {args.mode} data...")
    events, signals, nbas, session_states = generate_users(args.mode, products)

    # Insert
    print("\nInserting into MongoDB...")
    insert_data(db, events, signals, nbas, session_states)

    # Summary
    print_summary(events, signals, nbas)

    client.close()
    print("\nDone!")


if __name__ == "__main__":
    main()
