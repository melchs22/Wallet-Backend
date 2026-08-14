from rest_framework.views import exception_handler
from rest_framework.response import Response
from rest_framework import status
import logging

logger = logging.getLogger(__name__)


def custom_exception_handler(exc, context):
    """
    Custom exception handler that standardizes error responses.
    Returns { code: "error_code", message: "error message" } format.
    """
    # Call REST framework's default exception handler first
    response = exception_handler(exc, context)

    if response is not None:
        # Map common status codes to error codes
        error_code_mapping = {
            status.HTTP_400_BAD_REQUEST: 'validation_error',
            status.HTTP_401_UNAUTHORIZED: 'authentication_failed',
            status.HTTP_403_FORBIDDEN: 'permission_denied',
            status.HTTP_404_NOT_FOUND: 'not_found',
            status.HTTP_429_TOO_MANY_REQUESTS: 'rate_limit_exceeded',
            status.HTTP_500_INTERNAL_SERVER_ERROR: 'server_error',
        }

        # Get the error code
        error_code = error_code_mapping.get(response.status_code, 'unknown_error')

        # Customize error messages based on the exception
        custom_message = None
        if hasattr(exc, 'detail'):
            if isinstance(exc.detail, dict):
                # Handle validation errors
                errors = exc.detail
                if 'non_field_errors' in errors:
                    custom_message = str(errors['non_field_errors'][0])
                elif '__all__' in errors:
                    custom_message = str(errors['__all__'][0])
                else:
                    # Get first field error
                    first_field = next(iter(errors.keys()))
                    custom_message = f"{first_field}: {str(errors[first_field][0])}"
            else:
                custom_message = str(exc.detail)

        # Build standardized error response
        standardized_response = {
            'code': error_code,
            'message': custom_message or str(exc),
        }

        # Add Retry-After header for rate limiting
        if response.status_code == status.HTTP_429_TOO_MANY_REQUESTS:
            if hasattr(response, 'headers') and 'Retry-After' in response.headers:
                standardized_response['retry_after'] = response.headers['Retry-After']

        response.data = standardized_response

        # Log the error
        logger.error(
            f"API Error: {error_code} - {custom_message or str(exc)} - "
            f"Status: {response.status_code} - Path: {context['request'].path}"
        )

    return response