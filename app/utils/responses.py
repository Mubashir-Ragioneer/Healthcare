# app/utils/responses.py

def format_response(success: bool, data=None, message: str = ""):
    return {
        "success": success,
        "data": data,
        "message": message,
    }

def format_error_response(exc, status_code=500):
    return {
        "success": False,
        "error": {
            "type": exc.__class__.__name__,
            "detail": str(exc),
            "status_code": status_code
        }
    }
