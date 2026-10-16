from fastapi import HTTPException


class ApiError(HTTPException):
    """Error body: {"error": {"code", "message", "details"}} (spec 6.1)."""

    def __init__(self, status_code: int, code: str, message: str, details: dict | None = None):
        super().__init__(status_code=status_code, detail={"code": code, "message": message, "details": details or {}})
        self.code = code


def not_found(what: str = "Không tìm thấy") -> ApiError:
    return ApiError(404, "NOT_FOUND", what)


def forbidden(message: str = "Bạn không có quyền thực hiện thao tác này") -> ApiError:
    return ApiError(403, "FORBIDDEN", message)


def bad_request(code: str, message: str, details: dict | None = None) -> ApiError:
    return ApiError(400, code, message, details)
