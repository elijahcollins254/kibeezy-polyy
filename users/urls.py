from django.urls import path
from .views import (signup_view, login_view, token_view, check_auth, logout_view, update_profile_view, 
                    leaderboard_view, admin_list_users, admin_toggle_support_staff, google_auth_view, add_phone_number_view, lock_phone_after_deposit_view,
                    admin_get_user_portfolio, admin_get_user_activity)
from .kyc_views import start_kyc_verification, verify_kyc_otp, get_kyc_status
from .migration_views import migrate_phone_numbers

urlpatterns = [
    path('signup/', signup_view, name='signup'),
    path('login/', login_view, name='login'),
    path('token/', token_view, name='token'),
    path('logout/', logout_view, name='logout'),
    path('check/', check_auth, name='check_auth'),
    path('google/', google_auth_view, name='google_auth'),
    path('add-phone/', add_phone_number_view, name='add_phone'),
    path('lock-phone/', lock_phone_after_deposit_view, name='lock_phone'),
    path('update-profile/', update_profile_view, name='update_profile'),
    path('leaderboard/', leaderboard_view, name='leaderboard'),
    path('kyc/start/', start_kyc_verification, name='start_kyc'),
    path('kyc/verify/', verify_kyc_otp, name='verify_kyc'),
    path('kyc/status/', get_kyc_status, name='kyc_status'),
    # Admin endpoints
    path('admin/users/', admin_list_users, name='admin_list_users'),
    path('admin/users/<int:user_id>/toggle-support-staff/', admin_toggle_support_staff, name='admin_toggle_support_staff'),
    path('admin/users/<int:user_id>/portfolio/', admin_get_user_portfolio, name='admin_get_user_portfolio'),
    path('admin/users/<int:user_id>/activity/', admin_get_user_activity, name='admin_get_user_activity'),
    
    # Temporary migration endpoints (for one-time fixes)
    path('migrate/normalize-phones/', migrate_phone_numbers, name='migrate_normalize_phones'),
]
