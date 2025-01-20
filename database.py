from pymongo.database import Database
from fastapi import Depends, HTTPException
import os
from dotenv import load_dotenv
from pymongo import MongoClient
from bson import ObjectId
from datetime import datetime, timezone

#TODO: put try-except clause

class DatabaseHandler:
    def __init__(self, MONGO_URI, DB_NAME):
        self.MONGO_URI = MONGO_URI
        self.DB_NAME = DB_NAME


    # Helper function to insert or get existing document
    def get_or_create(collection_name, data, db: Database):
        if collection_name not in db.list_collection_names():
            db.create_collection(collection_name)

        collection = db[collection_name]
        existing = collection.find_one(data)
        if existing:
            return existing["_id"]  # Return existing document's ID
        result = collection.insert_one(data)
        return result.inserted_id  # Return new document's ID
    
    def add_documents(db: Database, documents, collection_name, qty_type="single"):
        if collection_name not in db.list_collection_names():
            db.create_collection(collection_name)

        if str(qty_type).lower() == "single":
            documents["created_at"] = datetime.now(timezone.utc)
            result = db[collection_name].insert_one(documents)
        elif str(qty_type).lower() == "multiple":
            for document in documents:
                document["created_at"] = datetime.now(timezone.utc)
            result = db[collection_name].insert_many(documents)
        else:
            raise Exception("Value of Qty type has to be either `single` or `multiple`")
        
        return result
    
    def delete_documents(db: Database, document_ids, collection_name, qty_type="single"):
        if collection_name not in db.list_collection_names():
            db.create_collection(collection_name)
        if str(qty_type).lower() == "single":
            result = db[collection_name].delete_one({"_id": ObjectId(document_ids)})
        elif str(qty_type).lower() == "multiple":
            object_ids = [ObjectId(id) for id in document_ids]
            filter = {"_id": {"$in": object_ids}}
            result = db[collection_name].delete_many(filter)
        else:
            raise Exception("Value of Qty type has to be either `single` or `multiple`")
        
        return result
    
    def perform_vote(db: Database, doc_id, vote, collection, issue=None):
        col = db[collection]
        if not isinstance(doc_id, str):  # Ensure doc_id is always a bson object
            doc_id = ObjectId(doc_id)

        if vote.lower() == "upvote":
            result = col.update_one({"_id": doc_id}, {"$inc": {"upvotes": 1}})
        elif vote.lower() == "downvote":
            result = col.update_one({"_id": doc_id}, {"$inc": {"downvotes": 1}})
            result = col.update_one({"_id": doc_id}, {"$push": {"issues": issue}})
        else:
            raise HTTPException(status_code=400, detail="Invalid vote type")
        
        return result