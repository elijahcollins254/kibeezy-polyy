from django.db import models
from django.contrib.auth.models import AbstractBaseUser, BaseUserManager, PermissionsMixin
from django.core.validators import RegexValidator, MinLengthValidator, MaxLengthValidator
import re

class CustomUserManager(BaseUserManager):
    def create_user(self, phone_number=None, full_name=None, password=None, **extra_fields):
        # For Google OAuth users: phone_number and password are optional
        # For phone-based auth: phone_number and password are required
        
        google_id = extra_fields.get('google_id')
        email = extra_fields.get('email')
        
        # If not a Google OAuth user, require phone_number
        if not google_id and not phone_number:
            raise ValueError('The Phone Number must be set for non-OAuth users')
        
        # Require full_name for all users
        if not full_name:
            raise ValueError('Full name must be set')
        
        # Generate username from full_name if not provided
        username = extra_fields.pop('username', None)
        if not username:
            username = self._generate_unique_username(full_name)
        
        user = self.model(
            phone_number=phone_number, 
            full_name=full_name, 
            username=username,
            **extra_fields
        )
        if password:
            user.set_password(password)
        user.save(using=self._db)
        return user

    def _generate_unique_username(self, full_name: str) -> str:
        """Generate a unique username from full_name"""
        # Convert to lowercase and remove special characters
        base_username = re.sub(r'[^a-z0-9_-]', '', full_name.lower().replace(' ', '_'))
        
        # Ensure it's 3-30 characters
        if len(base_username) < 3:
            base_username = base_username.ljust(3, '_')
        elif len(base_username) > 30:
            base_username = base_username[:30]
        
        # Check if username is available
        username = base_username
        counter = 1
        while self.model.objects.filter(username=username).exists():
            # Append number to make it unique
            suffix = str(counter)
            username = (base_username[:30 - len(suffix)] + suffix)
            counter += 1
        
        return username

    def create_superuser(self, phone_number, full_name, password=None, **extra_fields):
        extra_fields.setdefault('is_staff', True)
        extra_fields.setdefault('is_superuser', True)
        return self.create_user(phone_number, full_name, password, **extra_fields)

class CustomUser(AbstractBaseUser, PermissionsMixin):
    phone_regex = RegexValidator(regex=r'^\+?1?\d{9,15}$', message="Phone number must be entered in the format: '0718693484'.")
    username_regex = RegexValidator(
        regex=r'^[a-zA-Z0-9_-]{3,30}$',
        message="Username must be 3-30 characters and contain only letters, numbers, underscores, or hyphens."
    )
    
    phone_number = models.CharField(validators=[phone_regex], max_length=17, unique=True, null=True, blank=True)
    username = models.CharField(
        max_length=30, 
        unique=True, 
        validators=[username_regex],
        null=True,
        blank=True,
        help_text="Unique username displayed as @username throughout the platform"
    )
    phone_locked = models.BooleanField(default=False, help_text="Locked after first confirmed deposit to prevent fraud")
    full_name = models.CharField(max_length=255)
    email = models.EmailField(unique=True, null=True, blank=True)
    google_id = models.CharField(max_length=255, unique=True, null=True, blank=True)
    picture = models.URLField(null=True, blank=True)
    balance = models.DecimalField(max_digits=12, decimal_places=2, default=0.00)
    kyc_verified = models.BooleanField(default=False)
    kyc_verified_at = models.DateTimeField(null=True, blank=True)
    is_active = models.BooleanField(default=True)
    is_staff = models.BooleanField(default=False)
    is_support_staff = models.BooleanField(default=False, help_text="User can view and respond to support tickets")
    date_joined = models.DateTimeField(auto_now_add=True)

    objects = CustomUserManager()

    USERNAME_FIELD = 'phone_number'
    REQUIRED_FIELDS = ['full_name']

    def __str__(self):
        # Return phone number if available, otherwise email, otherwise full name
        if self.phone_number:
            return self.phone_number
        elif self.email:
            return self.email
        else:
            return self.full_name
    
    def get_user_statistics(self):
        """Get user statistics: total wagered, wins, losses"""
        from brokerage.models import Position
        positions = Position.objects.filter(user=self)
        total_wagered = sum(float(position.average_price * position.quantity) for position in positions)
        won_bets = positions.filter(realized_pnl__gt=0).count()
        lost_bets = positions.filter(realized_pnl__lt=0).count()
        win_rate = (won_bets / (won_bets + lost_bets) * 100) if (won_bets + lost_bets) > 0 else 0
        return {
            'total_wagered': total_wagered,
            'wins': won_bets,
            'losses': lost_bets,
            'win_rate': round(win_rate, 2)
        }
