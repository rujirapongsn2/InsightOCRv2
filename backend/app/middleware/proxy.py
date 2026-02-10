"""
Proxy Header Middleware

This middleware extracts proxy headers (X-Forwarded-*) set by Nginx reverse proxy
and updates the request scope with the correct client information.
"""

import logging
from typing import Callable

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response

logger = logging.getLogger(__name__)


class ProxyHeaderMiddleware(BaseHTTPMiddleware):
    """
    Middleware to handle X-Forwarded-* headers from reverse proxy.

    This middleware extracts the following headers:
    - X-Forwarded-For: Client IP address
    - X-Forwarded-Proto: Original protocol (http/https)
    - X-Forwarded-Host: Original host
    - X-Forwarded-Port: Original port
    """

    async def dispatch(self, request: Request, call_next: Callable) -> Response:
        """Process the request and extract proxy headers."""

        # Extract X-Forwarded-For header (client IP)
        forwarded_for = request.headers.get("X-Forwarded-For")
        if forwarded_for:
            # X-Forwarded-For can contain multiple IPs (client, proxy1, proxy2, ...)
            # The first IP is the original client
            client_ip = forwarded_for.split(",")[0].strip()

            # Update the client host in the request scope
            request.scope["client"] = (client_ip, request.scope["client"][1])

            if logger.isEnabledFor(logging.DEBUG):
                logger.debug(f"X-Forwarded-For: {forwarded_for}, Client IP: {client_ip}")

        # Extract X-Forwarded-Proto header (original protocol)
        forwarded_proto = request.headers.get("X-Forwarded-Proto")
        if forwarded_proto:
            request.scope["scheme"] = forwarded_proto

            if logger.isEnabledFor(logging.DEBUG):
                logger.debug(f"X-Forwarded-Proto: {forwarded_proto}")

        # Extract X-Forwarded-Host header (original host)
        forwarded_host = request.headers.get("X-Forwarded-Host")
        if forwarded_host:
            # Store original host for reference
            request.scope["forwarded_host"] = forwarded_host

            if logger.isEnabledFor(logging.DEBUG):
                logger.debug(f"X-Forwarded-Host: {forwarded_host}")

        # Extract X-Forwarded-Port header (original port)
        forwarded_port = request.headers.get("X-Forwarded-Port")
        if forwarded_port:
            # Store original port for reference
            request.scope["forwarded_port"] = forwarded_port

            if logger.isEnabledFor(logging.DEBUG):
                logger.debug(f"X-Forwarded-Port: {forwarded_port}")

        # Log all proxy information in debug mode
        if logger.isEnabledFor(logging.DEBUG):
            logger.debug(
                f"Proxy Request - "
                f"Client: {request.scope.get('client')}, "
                f"Scheme: {request.scope.get('scheme')}, "
                f"Forwarded Host: {request.scope.get('forwarded_host')}, "
                f"Forwarded Port: {request.scope.get('forwarded_port')}"
            )

        # Process the request
        response = await call_next(request)

        return response
