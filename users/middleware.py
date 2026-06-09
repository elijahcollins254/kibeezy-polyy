from urllib.parse import parse_qs
import logging

from django.contrib.auth.models import AnonymousUser

from .jwt_auth import get_user_from_jwt

logger = logging.getLogger(__name__)


class TokenAuthMiddleware:
    """ASGI middleware that looks for a JWT in the querystring or Authorization header
    and, if present and valid, populates `scope['user']` with the corresponding user.

    Usage: wrap your URLRouter with TokenAuthMiddleware in `api/asgi.py`.
    """

    def __init__(self, inner):
        self.inner = inner

    def __call__(self, scope):
        return TokenAuthMiddlewareInstance(scope, self.inner)


class TokenAuthMiddlewareInstance:
    def __init__(self, scope, inner):
        self.scope = dict(scope)
        self.inner = inner

    async def __call__(self, receive, send):
        scope = self.scope

        # Default to AnonymousUser
        scope['user'] = AnonymousUser()

        # Try querystring: ?token=...
        try:
            qs = parse_qs(scope.get('query_string', b'').decode())
            token = qs.get('token', [None])[0]
        except Exception:
            token = None

        # If not in querystring, try Authorization header: 'Authorization: Bearer <token>'
        if not token:
            headers = dict((k.decode().lower(), v.decode()) for k, v in scope.get('headers', []))
            auth = headers.get('authorization')
            if auth and auth.lower().startswith('bearer '):
                token = auth.split(' ', 1)[1]

        if token:
            try:
                user = get_user_from_jwt(token)
                if user:
                    scope['user'] = user
                    logger.debug(f"Authenticated websocket user from JWT: {user.id}")
            except Exception as e:
                logger.warning(f"JWT auth failed: {e}")

        inner = self.inner(scope)
        return await inner(receive, send)


def TokenAuthMiddlewareStack(inner):
    """Convenience wrapper to mirror channels' middleware stack API."""
    return TokenAuthMiddleware(inner)
