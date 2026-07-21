import logging
import os
import threading
from dotenv import load_dotenv
load_dotenv()

# Configure logging before other imports so all loggers pick up the handlers
LOG_FILE = "app.log"
root_logger = logging.getLogger()
root_logger.setLevel(logging.INFO)
formatter = logging.Formatter('%(asctime)s - %(name)s - %(levelname)s - %(message)s')
stream_handler = logging.StreamHandler()
stream_handler.setFormatter(formatter)
file_handler = logging.FileHandler(LOG_FILE)
file_handler.setFormatter(formatter)
root_logger.addHandler(stream_handler)
root_logger.addHandler(file_handler)

import secrets
from threading import Thread
from fastapi import Depends, FastAPI, Header, HTTPException
import uvicorn
from foundry_agents import (
    initialize as init_agents,
    shutdown as shutdown_agents,
    process_signal,
    set_enrichment,
    get_enrichment,
)
from change_stream import watch_customer_behavior
from mongo import get_db
from config import ADMIN_API_KEY, CHURN_RISK_SCORES_COLLECTION

logger = logging.getLogger(__name__)


def require_admin(x_admin_key: str | None = Header(default=None)):
    """Gate operational endpoints behind ADMIN_API_KEY when it is set.

    With no key configured (fresh clone, local dev) the endpoints stay open.
    On a deployed instance, set ADMIN_API_KEY and send X-Admin-Key with requests.
    """
    if not ADMIN_API_KEY:
        return
    if not (x_admin_key and secrets.compare_digest(x_admin_key, ADMIN_API_KEY)):
        raise HTTPException(status_code=401, detail="missing or invalid X-Admin-Key")

# Keep a reference to the change stream thread for status checks
_state = {"cs_thread": None}

# Create FastAPI app for HTTP endpoints
app = FastAPI(title="Retail Customer Retention Backend")

@app.get("/")
def health_check():
    """Health check endpoint for container liveness"""
    return {"status": "healthy", "service": "retail-customer-retention-backend"}

@app.get("/health")
def health():
    """Additional health endpoint"""
    return {"status": "ok"}

@app.get("/debug", dependencies=[Depends(require_admin)])
def debug_status():
    """Debug endpoint showing thread status and system health."""
    threads = [{"name": t.name, "alive": t.is_alive(), "daemon": t.daemon} for t in threading.enumerate()]
    cs_alive = _state["cs_thread"].is_alive() if _state["cs_thread"] else False
    return {
        "change_stream_thread_alive": cs_alive,
        "threads": threads,
    }

@app.post("/test-signal", dependencies=[Depends(require_admin)])
def test_signal():
    """Dev-only: fire a test exit-risk signal through the agent pipeline (no DB
    insert). Not the demo trigger -- the demo uses real exit intent from the UI."""
    test_doc = {
        "signal": "exit-risk",
        "uid": "test-http",
        "sid": "test-http-session",
        "severity": "high",
        "evidence": "HTTP test: mouse moved to close tab",
        "productId": "",
    }
    result = process_signal(test_doc)
    return result

@app.post("/test-signal/{signal_type}", dependencies=[Depends(require_admin)])
def test_signal_type(signal_type: str):
    """Fire a test signal of given type (exit-risk, high-intent, search-friction)."""
    test_doc = {
        "signal": signal_type,
        "uid": "test-http",
        "sid": "test-http-session",
        "severity": "medium",
        "evidence": f"HTTP test: {signal_type}",
        "productId": "",
    }
    result = process_signal(test_doc)
    return result


@app.get("/enrichment")
def enrichment_status():
    """Report whether exit-risk currently uses the Fabric-enriched agent."""
    return {"fabric_enrichment_enabled": get_enrichment()}


@app.post("/enrichment/{state}", dependencies=[Depends(require_admin)])
def set_enrichment_state(state: str):
    """Turn Fabric enrichment on or off at runtime (no restart). Lets a presenter
    run the exit-risk scenario with enrichment off, then on."""
    normalized = state.strip().lower()
    if normalized not in ("on", "off"):
        raise HTTPException(status_code=400, detail="state must be 'on' or 'off'")
    set_enrichment(normalized == "on")
    return {"fabric_enrichment_enabled": get_enrichment()}


@app.delete("/churn-score/{uid}", dependencies=[Depends(require_admin)])
def clear_churn_score(uid: str):
    """Delete a user's cached churn score so the enriched agent calls the model
    live again. Useful between demo runs for the high-risk persona."""
    result = get_db()[CHURN_RISK_SCORES_COLLECTION].delete_many({"uid": uid})
    return {"uid": uid, "deleted": result.deleted_count}


if __name__ == "__main__":
    logger.info("Starting retail customer retention backend...")

    try:
        # Initialize Foundry AI client (OpenAI SDK + MCP tools)
        logger.info("Initializing Foundry agents (direct OpenAI SDK + MCP)...")
        init_agents()
        logger.info("Agents initialized. Ready to process signals.")

        # Start the change stream watcher in a separate thread
        logger.info("Starting change stream watcher thread...")
        _state["cs_thread"] = Thread(target=watch_customer_behavior, daemon=True, name="change-stream")
        _state["cs_thread"].start()
        logger.info("Change stream thread started successfully")

        # Start the FastAPI server. Defaults to 8080 (what Azure Container Apps
        # expects); set PORT to run on a different port locally, e.g. PORT=8000
        # to avoid clashing with the storefront (which uses 8080).
        port = int(os.environ.get("PORT", "8080"))
        logger.info(f"Starting FastAPI server on port {port}...")
        uvicorn.run(app, host="0.0.0.0", port=port)

    except Exception as e:
        logger.error(f"Failed to start application: {str(e)}", exc_info=True)
        raise
    finally:
        shutdown_agents()
