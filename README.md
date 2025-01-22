# ABM-api
This API mainly focuses on the provision and manipulation of the ABM data

# Prerequisites
Python 3.11.7.

## Environment Variables
For the project to function, you'll need to set up your .env file to have the following.
```
MONGO_URI = connection string to your mongo database
DB_NAME = your database_name
```

## Running the Code.
1. Clone the repository or downlaod the zip file from GitHub
```
 git clone https://github.com/Delmas-code/ABM-api.git
```

2. Open a Terminal window and install required libaries/Frameworks.

```
pip install -r requirements.txt
```

3. To run the application.  
```
 uvicorn main:app --reload
```