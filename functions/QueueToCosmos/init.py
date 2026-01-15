
import json
import logging
import os
import azure.functions as func
from azure.cosmos import CosmosClient

COSMOS_ENDPOINT = os.environ["COSMOS_ENDPOINT"]
COSMOS_KEY = os.environ["COSMOS_KEY"]
DB_NAME = os.environ["COSMOS_DB_NAME"]
CONTAINER_NAME = os.environ["COSMOS_CONTAINER_NAME"]

def main(myQueueItem: str) -> None:
    logging.info("Queue item received: %s", myQueueItem)
    msg = json.loads(myQueueItem)

    action = msg.get("action", "upsert")
    version = msg.get("version", "latest")
    data = msg.get("data") or {}
    doc_id = msg.get("id") or data.get("id")

    if not doc_id:
        raise ValueError("Message must include 'id' or data.id")

    client = CosmosClient(COSMOS_ENDPOINT, COSMOS_KEY)
    db = client.get_database_client(DB_NAME)
    container = db.get_container_client(CONTAINER_NAME)

    if action == "delete":
        # Adjust partition key if your container uses a different one
        container.delete_item(item=doc_id, partition_key=doc_id)
        logging.info("Deleted document: %s", doc_id)
    else:
        document = {"id": doc_id, "version": version, **data}
        container.upsert_item(document)
        logging.info("Upserted document: %s", doc_id)
