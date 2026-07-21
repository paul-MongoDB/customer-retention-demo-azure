import logging
from typing import Dict, Any
from foundry_agents import process_signal

logger = logging.getLogger(__name__)


def handle_signal(doc: Dict[str, Any]) -> Dict[str, Any]:
    """
    Main signal processing entry-point.

    Delegates to the Foundry-native NBA agents which use MCPTool
    to access MongoDB and VoyageAI-powered vector search.
    """
    logger.info(f"Processing signal from document: {doc.get('_id', 'unknown')}")

    try:
        signal = doc.get("signal")

        if not signal:
            logger.warning("Document missing 'signal' field")
            return {"status": "error", "message": "Missing signal field"}

        logger.info(f"Signal type: {signal}")

        result = process_signal(doc)

        logger.info(f"Completed processing signal: {signal}")
        return result

    except Exception as e:
        logger.error(f"Error processing signal: {str(e)}", exc_info=True)
        return {"status": "error", "message": str(e)}
