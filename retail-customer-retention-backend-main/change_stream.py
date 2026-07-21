import logging
import time
from mongo import get_db
from config import SESSION_SIGNALS_COLLECTION
from agent import handle_signal

RESTART_DELAY_SECONDS = 5

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

def watch_customer_behavior():
    """
    Watch the session_signals collection for new inserts and route each
    document through the Foundry NBA agents.

    Runs in its own daemon thread. Agent calls use asyncio.run() internally
    to bridge the sync change stream to async Agent Framework workflows.
    """
    logger.info("Starting customer behavior change stream watcher...")

    while True:
        try:
            db = get_db()
            logger.info(f"Successfully connected to database: {db.name}")

            collection = db[SESSION_SIGNALS_COLLECTION]
            logger.info(f"Watching collection: {SESSION_SIGNALS_COLLECTION}")

            pipeline = [{"$match": {"operationType": "insert"}}]

            with collection.watch(pipeline) as stream:
                logger.info("Change stream opened, waiting for changes...")

                for change in stream:
                    try:
                        if "fullDocument" in change:
                            document = change["fullDocument"]
                            logger.info(
                                f"Processing document _id: {document.get('_id', 'unknown')}"
                            )
                            handle_signal(document)
                            logger.info("Document processed")
                        else:
                            logger.warning("Change missing 'fullDocument'")

                    except Exception as e:
                        logger.error(
                            f"Error processing change: {str(e)}", exc_info=True
                        )
                        continue

        except Exception as e:
            logger.error(
                f"Change stream watcher died: {str(e)}. Restarting in {RESTART_DELAY_SECONDS}s.",
                exc_info=True,
            )
            time.sleep(RESTART_DELAY_SECONDS)
