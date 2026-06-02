import base64
import json

import functions_framework
from google.cloud import secretmanager
from pymongo import MongoClient
from pymongo.errors import BulkWriteError


# Triggered from a message on a Cloud Pub/Sub topic.
@functions_framework.cloud_event
def write_to_mongodb(cloud_event):
    data = base64.b64decode(cloud_event.data["message"]["data"])
    decoded_data = json.loads(data.decode('utf-8'))
    print(f"--debug:: Data received from pubsub: {decoded_data}")
    secret_name = f"projects/266686822828/secrets/mongosh_de_uri/versions/latest"
    connection_uri_de = get_secret(secret_name)
    de_client = MongoClient(connection_uri_de)
    ingestion_db = de_client['ingestion-data']
    raw_headline_ingestion_collection = ingestion_db['raw_headlines_ingestion_data']
    if len(decoded_data) > 0:
        try:
            ins_cur = raw_headline_ingestion_collection.insert_many(decoded_data, ordered=False)
            print(f"--debug:: {len(decoded_data)} recs inserted successfully")
        except BulkWriteError as bwe:
            num_inserted = bwe.details['nInserted']
            # num_skipped = len(total) - num_inserted
            print(f"{num_inserted} documents inserted!")
            # print(f"{num_skipped} documents were duplicates and skipped.")
    else:
        print("No recs received!")
    de_client.close()
    return {'result': 'success'}


def get_secret(secret_name):
    client = secretmanager.SecretManagerServiceClient()
    response = client.access_secret_version(request={"name": secret_name})
    payload = response.payload.data.decode("UTF-8")
    return payload