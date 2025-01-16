from fastapi import FastAPI, Query, HTTPException, Depends
from typing import Optional
from pymongo import MongoClient
from pymongo.database import Database
from pydantic import BaseModel
from dotenv import load_dotenv
from bson import ObjectId
import os


load_dotenv()
app = FastAPI()

# MongoDB setup
MONGO_URI = os.getenv("MONGO_URI", "mongodb://localhost:27017")
DB_NAME = os.getenv("DB_NAME")

client: MongoClient = None

def get_database() -> Database:
    return client[DB_NAME]

@app.on_event("startup")
async def startup_db_client():
    global client
    client = MongoClient(MONGO_URI)
    print("MongoDB client initialized")

# Shutdown event: Close MongoDB connection
@app.on_event("shutdown")
async def shutdown_db_client():
    global client
    if client:
        client.close()
        print("MongoDB client closed")



# Helper function to serialize BSON ObjectId
def serialize_doc(doc):
    if "_id" in doc:
        doc["_id"] = str(doc["_id"])
    return doc

@app.get("/")
async def get_data(
    collection: Optional[str] = Query("companies", description="The collection to query"),
    page: int = Query(1, ge=1, description="Page number (starts at 1)"),
    limit: int = Query(10, ge=1, le=100, description="Number of documents per page"),
    db: Database = Depends(get_database),
):
    """
    Retrieve data from a MongoDB collection with pagination. If the collection is 'companies',
    populate the 'location' and 'industry' fields with their respective data.
    """
    collection = str(collection).capitalize()
    if collection not in db.list_collection_names():
        raise HTTPException(status_code=404, detail="Collection not found")

    # Retrieve data with pagination
    skip = (page - 1) * limit
    cursor = db[collection].find().skip(skip).limit(limit)
    documents = [serialize_doc(doc) for doc in cursor]

    # Populate data for the 'companies' collection
    try:
        if collection == "Companies":
            for doc in documents:
                if "location_id" in doc:
                    location = db["Locations"].find_one({"_id": ObjectId(doc["location_id"])})
                    doc_location = serialize_doc(location) if location else None
                    doc_location.pop("_id", None)
                    doc_location.pop("created_at", None)
                    doc["location"] = doc_location
                    doc.pop("location_id", None)

                if "industry_id" in doc:
                    industry = db["Industries"].find_one({"_id": ObjectId(doc["industry_id"])})
                    doc_industry = serialize_doc(industry) if industry else None
                    doc["industry"] = doc_industry["name"]
                    doc.pop("industry_id", None)
    except Exception as e:
        print(e)
        pass

    # Total document count for pagination metadata
    total_count = db[collection].count_documents({})

    return {
        "data": documents,
        "page": page,
        "limit": limit,
        # "total_count": total_count,
        "total_pages": (total_count + limit - 1) // limit,  # Ceiling division for total pages
    }
