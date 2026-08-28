import os

BASE_DIR = os.path.abspath(os.path.dirname(__file__))

# Use a writable database location on the cloud server
DATABASE_PATH = os.path.join("/tmp", "attendance.db")

class Config:
    SQLALCHEMY_DATABASE_URI = "sqlite:///" + DATABASE_PATH
    SQLALCHEMY_TRACK_MODIFICATIONS = False
