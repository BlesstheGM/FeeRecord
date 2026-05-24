import os

DAYCARE_NAME = "Little Stars Day Care"
DATABASE = os.path.join(os.path.dirname(__file__), "daycare.db")
UPLOAD_FOLDER = os.path.join(os.path.dirname(__file__), "uploads")
SECRET_KEY = os.environ.get("SECRET_KEY", "change-this-in-production-abc123")
