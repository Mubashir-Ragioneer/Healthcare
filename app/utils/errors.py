# app/utils/errors.py

from fastapi import HTTPException

class BadRequestError(HTTPException):
    def __init__(self, detail: str):
        super().__init__(status_code=400, detail=detail)

class UnauthorizedRequestError(HTTPException):
    def __init__(self, detail: str):
        super().__init__(status_code=401, detail=detail)

class ForbiddenError(HTTPException):
    def __init__(self, detail: str):
        super().__init__(status_code=403, detail=detail)

class NotFoundError(HTTPException):
    def __init__(self, detail: str):
        super().__init__(status_code=404, detail=detail)

class ConflictError(HTTPException):
    def __init__(self, detail: str):
        super().__init__(status_code=409, detail=detail)

class UnprocessableEntityError(HTTPException):
    def __init__(self, detail: str):
        super().__init__(status_code=422, detail=detail)

class TooManyRequestsError(HTTPException):
    def __init__(self, detail: str):
        super().__init__(status_code=429, detail=detail)

class InternalServerError(HTTPException):
    def __init__(self, detail: str):
        super().__init__(status_code=500, detail=detail)

class NotImplementedError(HTTPException):
    def __init__(self, detail: str):
        super().__init__(status_code=501, detail=detail)

class BadGatewayError(HTTPException):
    def __init__(self, detail: str):
        super().__init__(status_code=502, detail=detail)

class ServiceUnavailableError(HTTPException):
    def __init__(self, detail: str):
        super().__init__(status_code=503, detail=detail)

class GatewayTimeoutError(HTTPException):
    def __init__(self, detail: str):
        super().__init__(status_code=504, detail=detail)
