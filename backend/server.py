

# server.py
import os
import json
import uuid
import time
import logging
import pandas as pd
from dotenv import load_dotenv
from flask import Flask, request, jsonify
from flask_cors import CORS
from openai import OpenAI
from azure.cosmos import CosmosClient
from docx import Document
from PyPDF2 import PdfReader

load_dotenv()

# --- Safe startup logs (do not print secrets) ---
print("AZURE_OPENAI_API_KEY set:", bool(os.getenv("AZURE_OPENAI_API_KEY")))
print("AZURE_OPENAI_ENDPOINT:", os.getenv("AZURE_OPENAI_ENDPOINT"))
print("AZURE_OPENAI_DEPLOYMENT:", os.getenv("AZURE_OPENAI_DEPLOYMENT"))

app = Flask(__name__)
# For dev: allow all; for prod, restrict to your frontend origin(s).
CORS(app, resources={r"/api/*": {"origins": "*"}})

# Optional: limit upload size (e.g., 10 MB)
app.config["MAX_CONTENT_LENGTH"] = 10 * 1024 * 1024  # 10 MB

# --- Azure OpenAI client using OpenAI with Azure endpoint ---
endpoint = os.getenv("AZURE_OPENAI_ENDPOINT")
if endpoint and not endpoint.endswith("/openai/v1"):
    endpoint = endpoint.rstrip("/") + "/openai/v1"

client = OpenAI(
    base_url=endpoint,
    api_key=os.getenv("AZURE_OPENAI_API_KEY"),
)

# --- Initialize Cosmos DB client ---
cosmos_endpoint = os.getenv("COSMOS_ENDPOINT")
cosmos_key = os.getenv("COSMOS_KEY")
cosmos_db_name = os.getenv("COSMOS_DB_NAME")
cosmos_container_name = os.getenv("COSMOS_CONTAINER_NAME")

container = None
if cosmos_endpoint and cosmos_key:
    try:
        cosmos_client = CosmosClient(url=cosmos_endpoint, credential=cosmos_key)
        cosmos_db = cosmos_client.get_database_client(cosmos_db_name)
        container = cosmos_db.get_container_client(cosmos_container_name)
        print(f"[Cosmos] Ready. Using container: {cosmos_container_name}")
    except Exception as e:
        print(f"[Cosmos Init] Warning: {e}")
else:
    print("[Cosmos Init] Missing COSMOS_ENDPOINT or COSMOS_KEY.")

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


@app.route("/api/get-uploaded-files", methods=["GET"])
def get_uploaded_files():
    """
    Fetch existing uploaded files for a user.
    Returns both CSV data and policy documents.
    """
    if not container:
        return jsonify({"error": "Cosmos DB not configured"}), 500

    try:
        # Query for CSV data (get distinct source files).
        # Support legacy rows that may not have documentType set but have sourceFile.
        csv_query = """
        SELECT DISTINCT c.sourceFile
        FROM c
                WHERE (
            c.documentType = @csvType OR NOT IS_DEFINED(c.documentType)
          )
          AND IS_DEFINED(c.sourceFile)
        """

        csv_items = list(container.query_items(
            query=csv_query,
            parameters=[
                {"name": "@csvType", "value": "csvData"}
            ],
            enable_cross_partition_query=True
        ))

        # Query for policy documents
        policy_query = """
        SELECT DISTINCT c.fileName, c.uploadedAt
        FROM c
        WHERE c.documentType = @policyType
        """

        policy_items = list(container.query_items(
            query=policy_query,
            parameters=[
                {"name": "@policyType", "value": "policyDocument"}
            ],
            enable_cross_partition_query=True
        ))

        # Format CSV files
        csv_files = []
        for item in csv_items:
            csv_files.append({
                "name": item.get("sourceFile", "Unknown")
            })

        # Format policy files
        policy_files = []
        for item in policy_items:
            policy_files.append({
                "name": item.get("fileName", "Unknown"),
                "uploadedAt": item.get("uploadedAt")
            })

        return jsonify({
            "csvFiles": csv_files,
            "policyFiles": policy_files
        }), 200

    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/api/upload-excel-direct", methods=["POST"])
def upload_excel_direct():
    """
    Upload CSV/XLSX and write DIRECTLY to Cosmos DB (bypass queue).
    This avoids queue encoding issues.
    Deletes existing documents for the user before uploading to prevent data accumulation.
    """
    if not container:
        return jsonify({"error": "Cosmos DB not configured"}), 500

    if "file" not in request.files:
        return jsonify({"error": "No file uploaded (must be 'file')."}), 400

    file = request.files["file"]
    filename = (file.filename or "").lower()
    global_userId = request.form.get("userId") or request.args.get("userId")

    try:
        # DELETE EXISTING DOCUMENTS FOR THIS USER FIRST
        if global_userId:
            try:
                delete_query = "SELECT c.id FROM c WHERE c.userId = @userId AND c.documentType = @docType"
                existing_docs = list(container.query_items(
                    query=delete_query,
                    parameters=[
                        {"name": "@userId", "value": global_userId},
                        {"name": "@docType", "value": "csvData"}
                    ],
                    enable_cross_partition_query=True
                ))
                
                deleted_count = 0
                for doc in existing_docs:
                    container.delete_item(item=doc["id"], partition_key=global_userId)
                    deleted_count += 1
                
                print(f"Deleted {deleted_count} existing CSV documents for user {global_userId}")
            except Exception as del_err:
                print(f"Warning: Failed to delete existing documents: {del_err}")

        # Read CSV file
        if filename.endswith(".csv"):
            df = pd.read_csv(file)
        else:
            return jsonify({"error": "Only .csv files supported."}), 400

        processed_ids = []
        failed_rows = []

        for idx, row in df.iterrows():
            try:
                # Generate ID
                if "id" in df.columns and pd.notna(row.get("id")):
                    row_id = str(row["id"])
                else:
                    row_id = str(uuid.uuid4())

                # Get userId
                if "userId" in df.columns and pd.notna(row.get("userId")):
                    user_id = str(row["userId"])
                elif global_userId:
                    user_id = global_userId
                else:
                    failed_rows.append(f"Row {idx}: missing userId")
                    continue

                # Generate title
                if "title" in df.columns and pd.notna(row.get("title")):
                    title = str(row["title"])
                else:
                    title = f"Record {row_id}"

                # Generate content
                if "content" in df.columns and pd.notna(row.get("content")):
                    content = str(row["content"])
                else:
                    content = "\n".join(
                        f"{col}: {row[col]}"
                        for col in df.columns
                        if col != "userId" and pd.notna(row[col])
                    )

                # Build document (no truncation - each row stored separately)
                document = {
                    "id": row_id,
                    "userId": user_id,
                    "documentType": "csvData",
                    "title": title,
                    "content": content,
                    "version": "v1",
                    "sourceFile": filename  # Store the filename
                }

                # Write to Cosmos DB
                container.upsert_item(document)

                # Create embedding
                if content.strip():
                    try:
                        emb = client.embeddings.create(
                            model=os.getenv("AZURE_OPENAI_EMBEDDINGS_DEPLOYMENT"),
                            input=content
                        )
                        document["embedding"] = emb.data[0].embedding
                        container.upsert_item(document)
                        # Add delay to avoid rate limiting (0.1 seconds between calls)
                        time.sleep(0.1)
                    except Exception as emb_err:
                        # Log embedding errors but continue
                        print(f"[Embedding Error] Row {idx} (ID: {row_id}): {str(emb_err)}")
                        failed_rows.append(f"Row {idx}: embedding failed - {str(emb_err)}")

                processed_ids.append(row_id)

            except Exception as row_err:
                failed_rows.append(f"Row {idx}: {str(row_err)}")

        return jsonify({
            "status": "completed",
            "rowsProcessed": len(processed_ids),
            "rowsFailed": len(failed_rows),
            "ids": processed_ids,
            "errors": failed_rows if failed_rows else None
        }), 200

    except Exception as e:
        return jsonify({"error": str(e)}), 500

# POLICY DOCUMENTS UPLOAD
@app.route("/api/upload-policy-documents", methods=["POST"])
def upload_policy_documents():
    """
    Upload policy documents (PDF, DOCX, DOC, TXT) and store directly in Cosmos DB.
    Extracts text content and stores with documentType='policyDocument'.
    Deletes existing policy documents for the user before uploading new ones.
    """
    if not container:
        return jsonify({"error": "Cosmos DB not configured"}), 500

    if "files" not in request.files:
        return jsonify({"error": "No files uploaded (must be 'files')."}), 400

    files = request.files.getlist("files")
    global_userId = request.form.get("userId") or request.args.get("userId") or "default-user"

    # DELETE EXISTING POLICY DOCUMENTS FOR THIS USER FIRST
    try:
        delete_query = "SELECT c.id FROM c WHERE c.userId = @userId AND c.documentType = @docType"
        existing_docs = list(container.query_items(
            query=delete_query,
            parameters=[
                {"name": "@userId", "value": global_userId},
                {"name": "@docType", "value": "policyDocument"}
            ],
            enable_cross_partition_query=True
        ))
        
        deleted_count = 0
        for doc in existing_docs:
            container.delete_item(item=doc["id"], partition_key=global_userId)
            deleted_count += 1
        
        if deleted_count > 0:
            logging.info(f"Deleted {deleted_count} existing policy documents for user {global_userId}")
    except Exception as del_err:
        logging.warning(f"Warning: Failed to delete existing policy documents: {del_err}")

    processed_ids = []
    failed_files = []

    for file in files:
        try:
            filename = file.filename or "unknown"
            file_ext = filename.lower().split(".")[-1]

            # Extract text based on file type
            content = None
            if file_ext == "pdf":
                content = extract_text_from_pdf(file)
            elif file_ext in ("docx", "doc"):
                content = extract_text_from_docx(file)
            elif file_ext == "txt":
                content = file.read().decode("utf-8", errors="ignore")
            else:
                failed_files.append(f"{filename}: Unsupported file type. Use PDF, DOCX, DOC, or TXT.")
                continue

            if not content or not content.strip():
                failed_files.append(f"{filename}: No text content found.")
                continue

            # Create document for Cosmos DB
            doc_id = str(uuid.uuid4())
            document = {
                "id": doc_id,
                "userId": global_userId,
                "documentType": "policyDocument",
                "title": filename.rsplit(".", 1)[0],  # Remove extension
                "content": content,
                "fileName": filename,
                "uploadedAt": time.strftime("%Y-%m-%dT%H:%M:%SZ"),
                "version": "v1"
            }

            # Write to Cosmos DB
            container.upsert_item(document)

            # Create embedding
            try:
                emb = client.embeddings.create(
                    model=os.getenv("AZURE_OPENAI_EMBEDDINGS_DEPLOYMENT"),
                    input=content[:8000]  # Limit to 8000 chars for embedding
                )
                document["embedding"] = emb.data[0].embedding
                container.upsert_item(document)
                time.sleep(0.1)  # Avoid rate limiting
            except Exception as emb_err:
                logging.warning(f"Embedding failed for {filename}: {str(emb_err)}")
                # Continue anyway - document is stored without embedding

            processed_ids.append(doc_id)
            logging.info(f"Successfully processed policy document: {filename}")

        except Exception as file_err:
            failed_files.append(f"{file.filename}: {str(file_err)}")
            logging.error(f"Error processing file {file.filename}: {str(file_err)}")

    return jsonify({
        "status": "completed",
        "filesProcessed": len(processed_ids),
        "filesFailed": len(failed_files),
        "ids": processed_ids,
        "errors": failed_files if failed_files else None
    }), 200


def extract_text_from_pdf(file):
    """Extract text from PDF file."""
    try:
        file.seek(0)
        pdf_reader = PdfReader(file)
        text = ""
        for page in pdf_reader.pages:
            text += page.extract_text() + "\n"
        return text
    except Exception as e:
        logging.error(f"PDF extraction error: {str(e)}")
        raise


def extract_text_from_docx(file):
    """Extract text from DOCX/DOC file."""
    try:
        file.seek(0)
        doc = Document(file)
        text = "\n".join([para.text for para in doc.paragraphs])
        return text
    except Exception as e:
        logging.error(f"DOCX extraction error: {str(e)}")
        raise


# RAG QUERY SETUP
@app.route("/api/rag-query", methods=["POST"])
def rag_query():
    if not container:
        return jsonify({"error": "Cosmos DB container not initialized. Check your COSMOS_* environment variables."}), 500
    
    data = request.get_json()
    question = data["question"]

    # 1. Get question embedding
    qembed = client.embeddings.create(
        model=os.getenv("AZURE_OPENAI_EMBEDDINGS_DEPLOYMENT"),
        input=question
    ).data[0].embedding

    # 2. Query Cosmos DB for ALL documents with embeddings
    query = """
    SELECT c.id, c.title, c.content, c.sourceFile
    FROM c
    WHERE IS_DEFINED(c.embedding)
    """

    try:
        items = list(container.query_items(
            query=query,
            enable_cross_partition_query=True
        ))
    except Exception as e:
        return jsonify({"error": f"Cosmos DB query failed: {str(e)}"}), 500

    # If no documents with embeddings, return message
    if not items:
        return jsonify({"error": "No documents with embeddings found in Cosmos DB. Please ingest documents first."}), 400

    # 3. Combine retrieved content with source file info
    context_parts = []
    for x in items:
        source = x.get('sourceFile', x['title'])
        context_parts.append(f"[Source: {source}]\n{x['content']}")
    context = "\n\n".join(context_parts)

    # 4. Ask GPT‑4.2 with context
    answer = client.chat.completions.create(
        model=os.getenv("AZURE_OPENAI_DEPLOYMENT"),
        messages=[
            {"role": "system", "content": "You are a RAG assistant. Always cite sources by their filename when referencing information."},
            {"role": "user", "content": f"Question: {question}\n\nContext:\n{context}\n\nAnswer using ONLY the context above. When citing sources, use the [Source: filename] format shown in the context."}
        ]
    ).choices[0].message.content

    return jsonify({"answer": answer, "sources": items})


# Entry point
if __name__ == "__main__":
    # Optional: read port from env for cloud hosting compatibility
    port = int(os.getenv("PORT", "5000"))
    app.run(host="0.0.0.0", port=port)
