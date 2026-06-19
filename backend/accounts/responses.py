from rest_framework import status as http_status_codes
from rest_framework.response import Response
from rest_framework.views import exception_handler


def success_response(data=None, message="", http_status=http_status_codes.HTTP_200_OK):
    return Response(
        {"status": "success", "data": data, "message": message, "errors": None},
        status=http_status,
    )


def error_response(message="", errors=None, http_status=http_status_codes.HTTP_400_BAD_REQUEST):
    return Response(
        {"status": "error", "data": None, "message": message, "errors": errors},
        status=http_status,
    )


def envelope_exception_handler(exc, context):
    response = exception_handler(exc, context)
    if response is None:
        return response

    detail = response.data
    message = "Request failed."
    errors = detail

    if isinstance(detail, dict) and set(detail.keys()) == {"detail"}:
        message = str(detail["detail"])
        errors = None

    response.data = {
        "status": "error",
        "data": None,
        "message": message,
        "errors": errors,
    }
    return response
