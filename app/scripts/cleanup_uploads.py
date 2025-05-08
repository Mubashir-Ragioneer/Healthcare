from app.services.cleanup import delete_old_files

if __name__ == "__main__":
    deleted = delete_old_files()
    for f in deleted:
        print(f"🗑️ Deleted: {f}")
