import logging

from django.contrib.auth.backends import ModelBackend
from .models import CustomUser
from api.validators import normalize_phone_number

logger = logging.getLogger(__name__)


class PhoneNumberBackend(ModelBackend):
    """
    Authenticate using phone_number instead of username
    Allows superusers to login to admin without requiring is_staff flag
    """
    def authenticate(self, request, phone_number=None, password=None, **kwargs):
        if phone_number:
            phone_number = normalize_phone_number(phone_number)

        users = CustomUser.objects.filter(phone_number=phone_number).order_by('-is_active', '-is_superuser', 'id')
        user = users.first()

        if users.count() > 1:
            logger.warning(
                "Multiple CustomUser records found for phone_number=%s. Using first active match id=%s.",
                phone_number,
                user.id if user else None,
            )

        if not user:
            return None

        if user.check_password(password) and self.user_can_authenticate(user):
            return user
        return None

    def get_user(self, user_id):
        try:
            return CustomUser.objects.get(pk=user_id)
        except CustomUser.DoesNotExist:
            return None

    def user_can_authenticate(self, user):
        """
        Allow superusers and active users to authenticate
        Django admin requires is_active=True, but we allow superusers regardless of is_staff
        """
        is_active = getattr(user, 'is_active', None)
        return is_active or is_active is None


class AdminPhoneBackend(ModelBackend):
    """
    Custom backend for Django admin that allows superusers without is_staff
    """
    def authenticate(self, request, username=None, password=None, **kwargs):
        if username:
            username = normalize_phone_number(username)

        users = CustomUser.objects.filter(phone_number=username).order_by('-is_active', '-is_superuser', 'id')
        user = users.first()

        if users.count() > 1:
            logger.warning(
                "Multiple CustomUser records found for admin username=%s. Using first active match id=%s.",
                username,
                user.id if user else None,
            )

        if not user:
            return None

        if user.check_password(password):
            if user.is_active and (user.is_staff or user.is_superuser):
                return user
        return None

    def get_user(self, user_id):
        try:
            return CustomUser.objects.get(pk=user_id)
        except CustomUser.DoesNotExist:
            return None
