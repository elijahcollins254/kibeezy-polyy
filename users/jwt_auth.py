"""
JWT Authentication utilities for Channels WebSocket connections.

Provides JWT token generation and validation for WebSocket clients.
Designed to work with NextAuth and Django session auth as fallback.
"""

import jwt
import logging
from datetime import datetime, timedelta
from django.conf import settings
from django.contrib.auth import get_user_model

logger = logging.getLogger(__name__)

User = get_user_model()


class JWTAuthError(Exception):
    """Raised when JWT authentication fails."""
    pass


def generate_jwt_token(user, expires_in_hours=24):
    """
    Generate a JWT token for a user.
    
    Args:
        user: Django User instance (CustomUser)
        expires_in_hours: Token expiration time in hours (default: 24)
    
    Returns:
        JWT token string
    
    Raises:
        JWTAuthError: If token generation fails
    """
    try:
        payload = {
            'user_id': user.id,
            'phone_number': user.phone_number,
            'iat': datetime.utcnow(),
            'exp': datetime.utcnow() + timedelta(hours=expires_in_hours),
        }
        
        token = jwt.encode(
            payload,
            settings.SECRET_KEY,
            algorithm='HS256'
        )
        
        logger.info(f"JWT token generated for user {user.id}")
        return token
    except Exception as e:
        logger.error(f"Failed to generate JWT token: {str(e)}")
        raise JWTAuthError(f"Token generation failed: {str(e)}")


def verify_jwt_token(token):
    """
    Verify and decode a JWT token.
    
    Args:
        token: JWT token string
    
    Returns:
        Decoded token payload dictionary
    
    Raises:
        JWTAuthError: If token is invalid or expired
    """
    try:
        payload = jwt.decode(
            token,
            settings.SECRET_KEY,
            algorithms=['HS256']
        )
        logger.debug(f"JWT token verified for user {payload.get('user_id')}")
        return payload
    except jwt.ExpiredSignatureError:
        logger.warning(f"JWT token expired")
        raise JWTAuthError("Token has expired")
    except jwt.InvalidTokenError as e:
        logger.warning(f"Invalid JWT token: {str(e)}")
        raise JWTAuthError(f"Invalid token: {str(e)}")
    except Exception as e:
        logger.error(f"JWT verification error: {str(e)}")
        raise JWTAuthError(f"Token verification failed: {str(e)}")


def get_user_from_jwt(token):
    """
    Extract and return user instance from JWT token.
    
    Args:
        token: JWT token string
    
    Returns:
        User instance if valid, None otherwise
    """
    try:
        payload = verify_jwt_token(token)
        user_id = payload.get('user_id')
        
        if not user_id:
            logger.warning("JWT token missing user_id")
            return None
        
        user = User.objects.get(id=user_id)
        logger.debug(f"User retrieved from JWT: {user.id}")
        return user
        
    except JWTAuthError:
        return None
    except User.DoesNotExist:
        logger.warning(f"User not found for JWT user_id: {payload.get('user_id')}")
        return None
    except Exception as e:
        logger.error(f"Error retrieving user from JWT: {str(e)}")
        return None
