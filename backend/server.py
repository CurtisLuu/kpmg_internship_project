
# server.py
import os
import json
import uuid
from dotenv import load_dotenv
from flask import Flask, request, jsonify
from flask_cors import CORS
from openai import AzureOpenAI
from azure.storage.queue import QueueClient

# Load env
load_dotenv()

# --- Safety: do not print secrets. Only confirm presence. ---
print("AZURE_OPENAI_API_KEY set:", bool(os.getenv("AZURE_OPENAI_API_KEY")))
print("AZURE_OPENAI_ENDPOINT:", os.getenv("AZURE_OPENAI_ENDPOINT"))
print("AZURE_OPENAI_API_VERSION:", os.getenv("AZURE_OPENAI_API_VERSION"))
print("AZURE_OPENAI_DEPLOYMENT:", os.getenv("AZURE_OPENAI_DEPLOYMENT"))

app = Flask(__name__)
# For dev: allow all; for prod, restrict to your frontend origin(s).
CORS(app, resources={r"/api/*": {"origins": "*"}})

# --- Azure OpenAI client ---
client = AzureOpenAI(
    api_version=os.getenv("AZURE_OPENAI_API_VERSION"),
    azure_endpoint=os.getenv("AZURE_OPENAI_ENDPOINT"),
    api_key=os.getenv("AZURE_OPENAI_API_KEY"),
)

# --- Initialize QueueClient once (reused across requests) ---
QUEUE_CONN_STR = os.getenv("AZURE_STORAGE_CONNECTION_STRING")
QUEUE_NAME = os.getenv("AZURE_STORAGE_QUEUE_NAME", "myqueue-items")

queue_client = None
if QUEUE_CONN_STR:
    try:
        queue_client = QueueClient.from_connection_string(
            conn_str=QUEUE_CONN_STR, queue_name=QUEUE_NAME
        )
        # Ensure queue exists (idempotent)
        queue_client.create_queue()
        print(f"[Queue] Ready. Using queue: {QUEUE_NAME}")
    except Exception as e:
        print(f"[Queue Init] Warning: {e}")
else:
    print("[Queue Init] No AZURE_STORAGE_CONNECTION_STRING found.")

# ---------------------------
# Routes
# ---------------------------

@app.route("/api/chat", methods=["POST"])
def chat():
    try:
        data = request.get_json(force=True) or {}
        message = data.get("message")
        history = data.get("conversationHistory", [])

        if not message:
            return jsonify({"error": "Missing 'message'"}), 400

        messages = (
            [{"role": "system", "content": "You are a helpful assistant."}]
            + history
            + [{"role": "user", "content": message}]
        )

        completion = client.chat.completions.create(
            model=os.getenv("AZURE_OPENAI_DEPLOYMENT"),
            messages=messages,
            max_completion_tokens=512,
            temperature=0.7,
        )

        text = completion.choices[0].message.content if completion.choices else ""
        return jsonify({"message": text}), 200

    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/api/ingest", methods=["POST"])
def ingest():
    if not queue_client:
        return jsonify({"error": "Queue client not configured"}), 500

    try:
        payload = request.get_json(force=True) or {}
        # Expected shape:
        # {
        #   "action": "upsert" | "delete",
        #   "version": "v1",
        #   "data": { "id": "doc-123", "title": "...", "content": "...", ... }
        # }

        message_id = (
            payload.get("id")
            or payload.get("data", {}).get("id")
            or str(uuid.uuid4())
        )
        action = payload.get("action", "upsert")
        version = payload.get("version", "latest")
        data = payload.get("data", {})

        if action not in ("upsert", "delete"):
            return jsonify({"error": "Invalid action. Use 'upsert' or 'delete'."}), 400

        if action == "delete" and not (payload.get("id") or data.get("id")):
            return jsonify({"error": "Delete requires 'id' or data.id"}), 400

        message = {
            "id": message_id,
            "action": action,
            "version": version,
            "data": data,
        }

        queue_client.send_message(json.dumps(message))
        return jsonify({"status": "queued", "messageId": message_id}), 202

    except Exception as e:
        return jsonify({"error": str(e)}), 500


# Entry point
if __name__ == "__main__":
    # Optional: read port from env for cloud hosting compatibility
    port = int(os.getenv("PORT", "5000"))
    app.run(host="0.0.0.0", port=port)
