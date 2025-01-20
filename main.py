from fastapi import FastAPI, Query, HTTPException, Depends, Body
from typing import Optional
from pymongo import MongoClient
from pymongo.database import Database
from dotenv import load_dotenv
from bson import ObjectId
from models import CompanyUpdate, LocationUpdate, IndustryUpdate
from datetime import datetime, timezone

import os
from database import DatabaseHandler


load_dotenv()
app = FastAPI()
# MongoDB setup
MONGO_URI = os.getenv("MONGO_URI", "mongodb://localhost:27017")
DB_NAME = os.getenv("DB_NAME")

client: MongoClient = None
data_handler = DatabaseHandler(MONGO_URI, DB_NAME)

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

@app.get("/", tags=["Extra"])
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
        # "limit": limit,
        # "total_count": total_count,
        "total_pages": (total_count + limit - 1) // limit,  # Ceiling division for total pages
    }

#TODO: implement pagination for all /search endpoints

#Handle all events in the Comapanies collection
@app.post("/company/add", tags=["Company"], description=" This endpoint is incharge of adding new companies. They are added as a list(array) of dictionaries")
async def add_company(data: list = Body([{}]), db: Database = Depends(get_database)):
    """
    Add a single or multiple company documents to the database.
    """
    try:
        # Validate input
        if not isinstance(data, list):  # Ensure data is always a list
            data = [data]

        companies = []
        company_required_fields = ("name", "industry", "location","revenue","size")
        location_required_fields = ("country", "state", "city", "latitude", "longitude")
        errored_documents = []

        for idx, company in enumerate(data):
            for field in company_required_fields:
                if field not in company:
                    errored_document = {
                        "error": f"This document is missing `{field}`, required fields are {company_required_fields}",
                        "data": company
                    }
                    errored_documents.append(errored_document)
                    poped_company = data.pop(idx)
                    continue
                    
            name = company.get("name")
            industry_data = company.get("industry")
            location_data = company.get("location")

            for field in location_required_fields:
                if field not in location_data:
                    errored_document = {
                        "error": f"The location of this document doesn't have `{field}`, required fields are {location_required_fields}",
                        "data": company
                    }
                    errored_documents.append(errored_document)
                    poped_data = data.pop(idx)
                    continue


            # if not name or not industry_data or not location_data:
            #     raise HTTPException(status_code=400, detail="Missing required fields: 'name', 'industry', or 'location'.")

            # Create or get the industry
            industry_id = data_handler.get_or_create("Industries", industry_data)

            # Create or get the location
            location_id = data_handler.get_or_create("Locations", location_data)
            

            # Prepare company data
            company_data = dict(company)
            company_data["industry_id"] = location_id
            company_data["industry_id"] = industry_id

            poped_data = company_data.pop("industry")
            poped_data = company_data.pop("location")

            companies.append(company_data)

        # Insert company document(s)
        result = data_handler.add_documents(db, companies, "Companies", "multiple")

        if len(errored_documents) > 0 and len(errored_documents) != len(result.inserted_ids):
            return {
                "message": "Some Companies were added successfully but others failed", 
                "failed_results": errored_documents,
                "successful_results": result.inserted_ids
                }
        elif len(errored_documents) > 0 and len(errored_documents) == len(result.inserted_ids):
            return {
                "message": "No companies were added", 
                "failed_results": errored_documents,
                "successful_results": result.inserted_ids
                }
        else:
            return {
                "message": "All Companies added successfully", 
                "failed_results": errored_documents,
                "successful_results": result.inserted_ids
            }
    
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))


@app.get("/company/search", tags=["Company"], description="Search a company by ID or name")
async def search_company(id: str = Query(None), name: str = Query(None), db: Database = Depends(get_database)):
    """
    Search for a company by ID or name.
    """
    if not id and not name:
        raise HTTPException(
            status_code=400, detail="You must provide either 'id' or 'name' to search."
        )

    if id:
        try:
            company = db["Companies"].find_one({"_id": ObjectId(id)})
            if not company:
                raise HTTPException(status_code=404, detail=f"Company with the given ID {id} not found.")
            company["_id"] = str(company["_id"])  # Convert ObjectId to string
            return {"message": "Company found by ID", "data": company}
        except Exception:
            raise HTTPException(status_code=400, detail="Invalid ID format.")

    if name:
        companies = list(db["Companies"].find({"name": {"$regex": name, "$options": "i"}}))
        if not companies:
            raise HTTPException(status_code=404, detail="No companies found with the given name.")
        for company in companies:
            company["_id"] = str(company["_id"])  # Convert ObjectId to string
        return {"message": "Companies found by name", "data": companies}


@app.delete("/company/delete", tags=["Company"], description="Removes 1 or multiple Companies and their associated documents. The list(array) takes a string of ids")
async def remove_company(ids: list = Body(...), db: Database = Depends(get_database)):
    try:

        if not isinstance(ids, list):  # Ensure data is always a list
            ids = [ids]

        if len(ids) == 1:
            # Find the company document by IDs
            company = db["Companies"].find_one({"_id": ObjectId(ids)})
            if not company:
                raise HTTPException(status_code=404, detail="Company not found")

            # Extract location_id from the company document
            location_id = company.get("location_id")
            if location_id:
                # Delete the associated location document
                location_result = data_handler.delete_documents(db, location_id, "Locations", "single")
                if location_result.deleted_count == 0:
                    # raise HTTPException(status_code=404, detail="Associated location not found")
                    pass

            # Delete the company document
            company_result = data_handler.delete_documents(db, ids, "Companies", "single")
            if company_result.deleted_count == 0:
                raise HTTPException(status_code=404, detail="Company not found")

            return {
                "message": f"Company with ID {ids} and associated location with ID {location_id} have been deleted"
            }
        elif len(ids) > 1:
            errored_documents, ok_documents = [], []
            for id in ids:
                company = db["Companies"].find_one({"_id": ObjectId(id)})
                if not company:
                    errored_document = {
                        "error": f"Company not found",
                        "data": id
                    }
                    errored_documents.append(errored_document)
                else:
                    location_id = company.get("location_id")
                    if location_id:
                        # Delete the associated location document
                        location_result = data_handler.delete_documents(db, location_id, "Locations", "single")                  
                    ok_documents.append(id)
            if len(errored_documents) == len(ids):
                return {
                    "message": "No documents were deleted.",
                    "failed_results": errored_document,
                    "failed_count": len(errored_documents),
                    "successful_count": 0
                }
            else:
                company_results = data_handler.delete_documents(db, ok_documents, "Companies", "multiple")
                failed_count = len(ids) - company_results.deleted_count
                return {
                    "message": "Documents were deleted.",
                    "failed_results": errored_document,
                    "failed_count": failed_count,
                    "successful_count": company_results.deleted_count
                }
        
        else:
            raise HTTPException(status_code=400, detail="No ids were passed")


    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))
    

@app.put("/company/update", tags=["Company"], description="Update a company and related documents")
async def update_company(
    id: str = Query(..., description="ID of the company to update"),
    update_data: CompanyUpdate = None,
    db: Database = Depends(get_database)
):
    try:
        # Find the existing company document
        company = db["Companies"].find_one({"_id": ObjectId(id)})
        if not company:
            raise HTTPException(status_code=404, detail="Company not found")

        # Prepare the update payload for the company document
        company_update = {}
        if update_data.name:
            company_update["name"] = update_data.name
        if update_data.other_fields:
            company_update.update(update_data.other_fields)

        # Handle location updates
        if update_data.location:

            if "location_id" in company:
                # Validate required fields for location
                location_required_fields = ["country", "state", "city", "latitude", "longitude"]
                missing_fields = [field for field in location_required_fields if field not in update_data.location or not update_data.location[field]]
                if missing_fields:
                    raise HTTPException(
                        status_code=422,
                        detail=f"Missing required fields in location: {', '.join(missing_fields)}"
                    )

                # Update existing location document
                location_result = db["Locations"].update_one(
                    {"_id": ObjectId(company["location_id"])},
                    {"$set": update_data.location},
                )
                if location_result.matched_count == 0:
                    raise HTTPException(status_code=404, detail="Associated location not found")
            else:
                # Insert a new location document
                location_id = db["Locations"].insert_one(update_data.location).inserted_id
                company_update["location_id"] = str(location_id)

        # Handle industry updates
        if update_data.industry:
            if "industry_id" in company:
                # Update existing industry document
                industry_result = db["Industries"].update_one(
                    {"_id": ObjectId(company["industry_id"])},
                    {"$set": update_data.industry},
                )
                if industry_result.matched_count == 0:
                    raise HTTPException(status_code=404, detail="Associated industry not found")
            else:
                # Insert a new industry document
                industry_id = db["Industries"].insert_one(update_data.industry).inserted_id
                company_update["industry_id"] = str(industry_id)

        # Update the company document
        if "created_at" in company_update:
            company_update.pop("created_at")

        if company_update:
            company_result = db["Companies"].update_one(
                {"_id": ObjectId(id)},
                {"$set": company_update},
            )
            if company_result.matched_count == 0:
                raise HTTPException(status_code=404, detail="Company not found")

        return {"message": f"Company with ID {id} has been updated", "updated_fields": company_update}

    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))
    



#Handle all events in the Locations collection
@app.get("/location/search", tags=["Location"], description="Search a location by ID, country, state, city")
async def search_location(
    id: str = Query(None), 
    country: str = Query(None), 
    state: str = Query(None),
    city: str = Query(None),
    db: Database = Depends(get_database)):
    """
    Search for a location by ID or name.
    """
    if not id and not country and not state and not city:
        raise HTTPException(
            status_code=400, detail="You must provide either 'id', 'country', 'state' or 'city' to search."
        )

    if id:
        try:
            location = db["Locations"].find_one({"_id": ObjectId(id)})
            if not location:
                raise HTTPException(status_code=404, detail=f"Lcoation with the given ID {id} not found.")
            location["_id"] = str(location["_id"])  # Convert ObjectId to string
            return {"message": "Location found by ID", "data": location}
        except Exception:
            raise HTTPException(status_code=400, detail="Invalid ID format.")

    if country:
        locations = list(db["Locations"].find({"country": {"$regex": country, "$options": "i"}}))
        if not locations:
            raise HTTPException(status_code=404, detail="No locations found with the given country.")
        for location in locations:
            location["_id"] = str(location["_id"])  # Convert ObjectId to string
        return {"message": "Locations found by country", "data": locations}
    if state:
        locations = list(db["Locations"].find({"state": {"$regex": state, "$options": "i"}}))
        if not locations:
            raise HTTPException(status_code=404, detail="No locations found with the given state.")
        for location in locations:
            location["_id"] = str(location["_id"])  # Convert ObjectId to string
        return {"message": "Locations found by state", "data": locations}
    
    if city:
        locations = list(db["Locations"].find({"city": {"$regex": city, "$options": "i"}}))
        if not locations:
            raise HTTPException(status_code=404, detail="No locations found with the given city.")
        for location in locations:
            location["_id"] = str(location["_id"])  # Convert ObjectId to string
        return {"message": "Locations found by city", "data": locations}


@app.put("/location/update", tags=["Location"], description="Update a location and related documents")
async def update_location(
    id: str = Query(..., description="ID of the location to update"),
    update_data: LocationUpdate = None,
    db: Database = Depends(get_database)
):
    try:
        # Find the existing location document
        location = db["Locations"].find_one({"_id": ObjectId(id)})
        if not location:
            raise HTTPException(status_code=404, detail="Location not found")

        # Update the location document
        if "created_at" in update_data:
            update_data.pop("created_at")
        
        # Update existing location document
        location_result = db["Locations"].update_one(
            {"_id": ObjectId(id)},
            {"$set": update_data},
        )
        if location_result.matched_count == 0:
            raise HTTPException(status_code=404, detail="Location not found")
        
        return {"message": f"Location with ID {id} has been updated", "updated_fields": update_data}

    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))
    


#Handle all events in the Industries collection
@app.post("/industry/add", tags=["Industry"], description="This endpoint is incharge of adding new idustries. They are added as a list(array) of json")
async def add_industry(data: list = Body([{}]), db: Database = Depends(get_database)):
    """
    Add a single or multiple industry documents to the database.
    """

    try:
        # Validate input
        if not isinstance(data, list):  # Ensure data is always a list
            data = [data]

        industries = []
        industry_required_fields = ("name")
        errored_documents = []

        for idx, industry in enumerate(data):
            for field in industry_required_fields:
                if field not in industry:
                    errored_document = {
                        "error": f"This document is missing `{field}`, required fields are {industry_required_fields}",
                        "data": industry
                    }
                    errored_documents.append(errored_document)
                    # poped_industry = data.pop(idx)
                    # continue
                else:
                    industries.append(industry)
        result = data_handler.add_documents(db, industries, "Industries", "multiple")

        if len(errored_documents) > 0 and len(errored_documents) != len(result.inserted_ids):
            return {
                "message": "Some Industries were added successfully but others failed", 
                "failed_results": errored_documents,
                "successful_results": result.inserted_ids
                }
        
        elif len(errored_documents) > 0 and len(errored_documents) == len(result.inserted_ids):
            return {
                "message": "No industries were added", 
                "failed_results": errored_documents,
                "successful_results": result.inserted_ids
                }
        else:
            return {
                "message": "All Industries added successfully", 
                "failed_results": errored_documents,
                "successful_results": result.inserted_ids
            }
    
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))



@app.get("/industry/search", tags=["Industry"], description="Search an industry by ID or name")
async def search_industry(id: str = Query(None), name: str = Query(None), db: Database = Depends(get_database)):
    """
    Search for a industry by ID or name.
    """
    if not id and not name:
        raise HTTPException(
            status_code=400, detail="You must provide either 'id' or 'name' to search."
        )

    if id:
        try:
            indsutry = db["Industries"].find_one({"_id": ObjectId(id)})
            if not indsutry:
                raise HTTPException(status_code=404, detail=f"Industry with the given ID {id} not found.")
            indsutry["_id"] = str(indsutry["_id"])  # Convert ObjectId to string
            return {"message": "Industry found by ID", "data": indsutry}
        except Exception:
            raise HTTPException(status_code=400, detail="Invalid ID format.")

    if name:
        industries = list(db["Industries"].find({"name": {"$regex": name, "$options": "i"}}))
        if not industries:
            raise HTTPException(status_code=404, detail="No industries found with the given name.")
        for industry in industries:
            industry["_id"] = str(industry["_id"])  # Convert ObjectId to string
        return {"message": "Industries found by name", "data": industries}



@app.delete("/industry/delete", tags=["Industry"], description="Removes 1 or multiple industries. The list(array) takes a string of ids")
async def remove_industry(ids: list = Body(...), db: Database = Depends(get_database)):
    try:

        if not isinstance(ids, list):  # Ensure data is always a list
            ids = [ids]

        if len(ids) == 1:
            # Find the industry document by IDs
            industry = db["Industries"].find_one({"_id": ObjectId(ids)})
            if not industry:
                raise HTTPException(status_code=404, detail="Industry not found")

            # Delete the industry document
            industry_result = data_handler.delete_documents(db, ids, "Industries", "single")
            if industry_result.deleted_count == 0:
                raise HTTPException(status_code=404, detail="Industry not found")

            return {
                "message": f"Industry with ID {ids} has been deleted"
            }
        elif len(ids) > 1:
            errored_documents, ok_documents = [], []
            for id in ids:
                industry = db["Industries"].find_one({"_id": ObjectId(id)})
                if not industry:
                    errored_document = {
                        "error": f"Industry not found",
                        "data": id
                    }
                    errored_documents.append(errored_document)       
                else:          
                    ok_documents.append(id)

            if len(errored_documents) == len(ids):
                return {
                    "message": "No documents were deleted.",
                    "failed_results": errored_document,
                    "failed_count": len(errored_documents),
                    "successful_count": 0
                }
            else:
                industry_results = data_handler.delete_documents(db, ok_documents, "Industries", "multiple")
                failed_count = len(ids) - industry_results.deleted_count
                return {
                    "message": "Documents were deleted.",
                    "failed_results": errored_document,
                    "failed_count": failed_count,
                    "successful_count": industry_results.deleted_count
                }
        else:
            raise HTTPException(status_code=400, detail="No ids were passed")


    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))
    


@app.put("/industry/update", tags=["Industry"], description="Update an industry")
async def update_industry(
    id: str = Query(..., description="ID of the industry to update"),
    update_data: IndustryUpdate = None,
    db: Database = Depends(get_database)
):
    try:
        # Find the existing industry document
        industry = db["Industries"].find_one({"_id": ObjectId(id)})
        if not industry:
            raise HTTPException(status_code=404, detail="industry not found")

        # Update the industry document
        if "created_at" in update_data:
            update_data.pop("created_at")
        
        # Update existing industry document
        industry_result = db["Industries"].update_one(
            {"_id": ObjectId(id)},
            {"$set": update_data},
        )
        if industry_result.matched_count == 0:
            raise HTTPException(status_code=404, detail="Industry not found")
        
        return {"message": f"Industry with ID {id} has been updated", "updated_fields": update_data}

    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))
    

#Handle votes
#collection can be either company, employee
@app.get("/vote/details", tags=["Votes"], description="Get number of votes for a particular employee or company")
async def get_votes(
    id: str = Query(...),
    collection: str = Query("Companies", description="The collection to query. Can be either `Companies` or `Employees`"),
    db: Database = Depends(get_database),
):
    try:
        collection = collection.capitalize()
        if collection == "Companies":

            company_col = db[collection]
            company_doc = company_col.find_one({"_id": ObjectId(id)})
            location_doc = db["Locations"].find_one({"_id": ObjectId(company_doc["location_id"])})
            contact_doc = db["Contacts"].find_one({"_id": ObjectId(company_doc["contact_id"])})
            industry_doc = db["Industries"].find_one({"_id": ObjectId(company_doc["industry_id"])})

            data = {
                "contact_votes": {
                    "upvotes": contact_doc["upvotes"] if "upvotes" in contact_doc else 0,
                    "downvotes": contact_doc["downvotes"] if "downvotes" in contact_doc else 0,
                    "issues": contact_doc["issues"] if "issues" in contact_doc else {}
                },
                "company_info_votes": {
                    "upvotes": company_doc["upvotes"] if "upvotes" in company_doc else 0,
                    "downvotes": company_doc["downvotes"] if "downvotes" in company_doc else 0,
                    "issues": company_doc["issues"] if "issues" in company_doc else {}
                },
                "location_votes": {
                    "upvotes": location_doc["upvotes"] if "upvotes" in location_doc else 0,
                    "downvotes": location_doc["downvotes"] if "downvotes" in location_doc else 0,
                    "issues": location_doc["issues"] if "issues" in location_doc else {}
                },
                "industry_votes": {
                    "upvotes": industry_doc["upvotes"] if "upvotes" in industry_doc else 0,
                    "downvotes": industry_doc["downvotes"] if "downvotes" in industry_doc else 0,
                    "issues": industry_doc["issues"] if "issues" in industry_doc else {}
                }
            }

        elif collection == "Employees":
            employee_col = db[collection]
            employee_doc = employee_col.find_one({"_id": ObjectId(id)})
            contact_doc = db["Contacts"].find_one({"_id": ObjectId(employee_doc["contact_id"])})

            data = {
                "contact_votes": {
                    "upvotes": contact_doc["upvotes"] if "upvotes" in contact_doc else 0,
                    "downvotes": contact_doc["downvotes"] if "downvotes" in contact_doc else 0,
                    "issues": contact_doc["issues"] if "issues" in contact_doc else {}
                },
                "employee_info_votes": {
                    "upvotes": employee_doc["upvotes"] if "upvotes" in employee_doc else 0,
                    "downvotes": employee_doc["downvotes"] if "downvotes" in employee_doc else 0,
                    "issues": employee_doc["issues"] if "issues" in employee_doc else {}
                }
            }

        else:
            raise HTTPException(status_code=400, detail="Invalid collection entered. Collection should eiher be `Companies` or `Employees` ")

        return data
    
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/vote/add", tags=["Votes"], description="Collection can be either company, employee")
async def vote_entity(
    id: str = Query(...),
    vote: str = Query(...),  # "upvote" or "downvote"
    collection: str = Query("Companies", description="The collection to query. Can be either `Companies` or `Employees`"),
    issue: Optional[dict] = Body({}, description="The issues reported by a user when down voting"),
    db: Database = Depends(get_database),
):
    try:
        collection = collection.capitalize()
        if collection not in ["Companies", "Employees"]:
            raise HTTPException(status_code=400, detail="Invalid collection name")
        
        if (vote.lower() == "downvote" and not isinstance(issue, dict)):
            raise HTTPException(status_code=400, detail="Invalid datatype for issue. It has to be in a json format")
        elif (vote.lower() == "downvote" and len(issue) == 0):
            raise HTTPException(status_code=400, detail="Issue can not be empty")


        # Validate issue
        if "field" not in issue or "reason" not in issue or "suggestion" not in issue:
            raise HTTPException(status_code=400, detail="Invalid issue format")
        issue["created_at"] = datetime.now(timezone.utc)

        contact_fields = ["phone", "email"]
        location_fields = ["country", "state", "city", "latitude", "longitude"]

        if collection == "Companies":
            company_col = db["Companies"]
            if str(issue["field"]).lower() in  contact_fields:
                company_doc = company_col.find_one({"_id": ObjectId(id)})
                # str(company_doc["_id"])
                result = data_handler.perform_vote(db, company_doc["contact_id"], vote, "Contacts", issue)
                
            elif str(issue["field"]).lower() in  location_fields:

                company_doc = company_col.find_one({"_id": ObjectId(id)})
                # str(company_doc["_id"])
                result = data_handler.perform_vote(db, company_doc["location_id"], vote, "Locations", issue)
            
            elif str(issue["field"]).lower() ==  "industry":

                company_doc = company_col.find_one({"_id": ObjectId(id)})
                result = data_handler.perform_vote(db, company_doc["industry_id"], vote, "Industries", issue)

            else:
                result = data_handler.perform_vote(db, id, vote, "Companies", issue)
                      
            if result.matched_count == 0:
                raise HTTPException(status_code=404, detail="Document not found")
        elif collection == "Employees":
            employee_col = db["Employees"]

            if str(issue["field"]).lower() in  contact_fields:
                employee_doc = employee_col.find_one({"_id": ObjectId(id)})
                result = data_handler.perform_vote(db, employee_doc["contact_id"], vote, "Contacts", issue)
            else:
                result = data_handler.perform_vote(db, id, vote, "Employees", issue)
                
            if result.matched_count == 0:
                raise HTTPException(status_code=404, detail="Document not found")

        return {"message": f"{vote.capitalize()} successful for document with id {id}"}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


