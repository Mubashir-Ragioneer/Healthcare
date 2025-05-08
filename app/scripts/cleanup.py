# app/services/cleanup.py
import os
import time

UPLOAD_DIR = os.path.abspath("app/uploads")
MAX_AGE_DAYS = 2

def delete_old_files() -> list:
    deleted = []
    now = time.time()
    cutoff = now - (MAX_AGE_DAYS * 86400)

    if not os.path.exists(UPLOAD_DIR):
        return deleted

    for filename in os.listdir(UPLOAD_DIR):
        file_path = os.path.join(UPLOAD_DIR, filename)
        if os.path.isfile(file_path):
            if os.path.getmtime(file_path) < cutoff:
                os.remove(file_path)
                deleted.append(filename)

    return deleted
