import os

from dotenv import load_dotenv
from loguru import logger
from pymongo import MongoClient

load_dotenv()


def get_db_altas():
    mongo_uri = os.getenv("MONGO_ALTAS_URI")
    db_name = os.getenv("MONGO_DB_NAME")

    if not all([mongo_uri, db_name]):
        logger.error("請確認 .env 已設定 MONGO_ALTAS_URI / MONGO_DB_NAME")
        raise EnvironmentError("請確認 .env 已設定 MONGO_ALTAS_URI / MONGO_DB_NAME")

    client = MongoClient(mongo_uri)
    return client[db_name]
