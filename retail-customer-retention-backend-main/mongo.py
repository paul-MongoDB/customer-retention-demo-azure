from pymongo import MongoClient
from config import MONGODB_URI, DB_NAME

_client = None

def get_db():
    global _client
    if _client is None:
        _client = MongoClient(MONGODB_URI, tls=True, tlsAllowInvalidCertificates=True)
    return _client[DB_NAME]
