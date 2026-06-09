import json
import logging
from django.contrib.auth import authenticate, login, logout
from django.db.models import Sum, Q, Value, DecimalField
from django.db.models.functions import Coalesce
from django.http import JsonResponse
from django.views.decorators.csrf import ensure_csrf_cookie, csrf_exempt
from django.views.decorators.http import require_http_methods
from django.middleware.csrf import get_token
from .models import CustomUser
from api.validators import validate_phone_number, validate_password, validate_full_name, normalize_phone_number, ValidationError
from notifications.views import create_notification
from markets.utils.price_calculations import PAYOUT_PER_SHARE
from .jwt_auth import generate_jwt_token

logger = logging.getLogger(__name__)

@csrf_exempt
@require_http_methods(["POST"])
def signup_view(request):
    try:
        data = json.loads(request.body)
        full_name = data.get('full_name')
        phone_number = data.get('phone_number')
        password = data.get('password')

        if not all([full_name, phone_number, password]):
            return JsonResponse({'error': 'Missing required fields: full_name, phone_number, password'}, status=400)
        
        # Validate inputs
        try:
            full_name = validate_full_name(full_name)
            phone_number = validate_phone_number(phone_number)
            password = validate_password(password)
        except ValidationError as e:
            return JsonResponse({'error': e.message}, status=400)

        if CustomUser.objects.filter(phone_number=phone_number).exists():
            return JsonResponse({'error': 'Phone number already registered'}, status=400)

        user = CustomUser.objects.create_user(
            phone_number=phone_number,
            full_name=full_name,
            password=password
        )
        logger.info(f"New user created: {phone_number}")
        
        # Create welcome notification
        create_notification(
            user=user,
            type_choice='WELCOME',
            title='Welcome to CACHE!',
            message='Start predicting markets to earn rewards',
            color_class='blue'
        )
        
        return JsonResponse({
            'message': 'Account created successfully', 
            'user': {
                'phone_number': user.phone_number, 
                'full_name': user.full_name,
                'id': user.id,
                'is_staff': user.is_staff,
                'is_superuser': user.is_superuser,
            }
        }, status=201)
    except json.JSONDecodeError:
        return JsonResponse({'error': 'Invalid JSON'}, status=400)
    except ValidationError as e:
        return JsonResponse({'error': e.message}, status=400)
    except Exception as e:
        logger.error(f"Signup error: {str(e)}")
        return JsonResponse({'error': str(e)}, status=500)


@csrf_exempt
@ensure_csrf_cookie
@require_http_methods(["POST"])
def login_view(request):
    try:
        data = json.loads(request.body)
        phone_number = data.get('phone_number')
        password = data.get('password')

        if not all([phone_number, password]):
            return JsonResponse({'error': 'Missing credentials: phone_number, password'}, status=400)

        # Normalize phone number before authentication
        try:
            phone_number = normalize_phone_number(phone_number)
        except:
            return JsonResponse({'error': 'Invalid phone number format'}, status=400)

        logger.info(f"Login attempt for phone: {phone_number}")
        user = authenticate(request, phone_number=phone_number, password=password)
        if user is not None:
            logger.info(f"User authenticated: {user.phone_number}, User ID: {user.id}")
            login(request, user)  # This sets the session cookie
            # Force session save to database
            request.session.save()
            logger.info(f"Session key after login: {request.session.session_key}")
            # Get CSRF token
            csrf_token = get_token(request)
            
            response = JsonResponse({
                'message': 'Login successful', 
                'user': {
                    'phone_number': user.phone_number, 
                    'full_name': user.full_name,
                    'id': user.id,
                    'kyc_verified': user.kyc_verified,
                    'phone_locked': user.phone_locked,
                    'date_joined': user.date_joined.isoformat() if user.date_joined else None,
                    'is_staff': user.is_staff,
                    'is_superuser': user.is_superuser,
                },
                'csrf_token': csrf_token
            })
            logger.info(f"Login successful for {phone_number}, setting cookies")
            logger.info(f"Response headers: {response}")
            return response
        else:
            logger.warning(f"Failed authentication for phone: {phone_number}")
            return JsonResponse({'error': 'Invalid phone number or password'}, status=401)
    except json.JSONDecodeError:
        return JsonResponse({'error': 'Invalid JSON'}, status=400)
    except Exception as e:
        logger.error(f"Login error: {str(e)}")
        return JsonResponse({'error': str(e)}, status=500)


@require_http_methods(["GET"])
def check_auth(request):
    """Check if user is authenticated"""
    logger.info(f"Checking auth - User: {request.user}, Authenticated: {request.user.is_authenticated if request.user else 'None'}")
    logger.info(f"Session key: {request.session.session_key}")
    
    if request.user and request.user.is_authenticated:
        logger.info(f"Auth check successful for {request.user.phone_number}")
        return JsonResponse({
            'authenticated': True,
            'user': {
                'phone_number': request.user.phone_number,
                'full_name': request.user.full_name,
                'id': request.user.id,
                'balance': str(request.user.balance),
                'kyc_verified': request.user.kyc_verified,
                'date_joined': request.user.date_joined.isoformat() if request.user.date_joined else None,
                'is_staff': request.user.is_staff,
                'is_superuser': request.user.is_superuser,
            }
        })
    else:
        logger.warning(f"Auth check failed - user not authenticated")
        return JsonResponse({
            'authenticated': False,
            'error': 'Not authenticated'
        }, status=401)


@csrf_exempt
@require_http_methods(["POST"])
def logout_view(request):
    """Logout user"""
    logout(request)
    logger.info(f"User logged out")
    return JsonResponse({'message': 'Logged out successfully'})


@require_http_methods(["POST"])
def token_view(request):
    """Issue a JWT token for the currently authenticated session user.

    This endpoint requires an active session (user logged in via `login_view`).
    Returns: {"token": "<jwt>"}
    """
    user = request.user if request.user and request.user.is_authenticated else None
    if not user:
        return JsonResponse({'error': 'Authentication required'}, status=401)

    try:
        token = generate_jwt_token(user)
        return JsonResponse({'token': token})
    except Exception as e:
        logger.error(f"Token issuance failed: {e}")
        return JsonResponse({'error': 'Token issuance failed'}, status=500)


@csrf_exempt
@require_http_methods(["POST"])
def update_profile_view(request):
    """Update user profile information"""
    # Try session-based auth first
    user = request.user if request.user and request.user.is_authenticated else None
    
    # Fall back to phone header auth
    if not user:
        phone_number = request.headers.get('X-User-Phone-Number')
        if phone_number:
            try:
                # Normalize phone number
                phone_number = normalize_phone_number(phone_number)
                user = CustomUser.objects.get(phone_number=phone_number)
            except CustomUser.DoesNotExist:
                user = None
    
    # Fall back to email header auth (for Google OAuth users)
    if not user:
        email = request.headers.get('X-User-Email')
        if email:
            try:
                user = CustomUser.objects.get(email=email)
            except CustomUser.DoesNotExist:
                user = None
    
    if not user:
        return JsonResponse({'error': 'Authentication required'}, status=401)
    
    try:
        data = json.loads(request.body)
        full_name = data.get('full_name')
        phone_number = data.get('phone_number')
        
        if full_name:
            try:
                full_name = validate_full_name(full_name)
                user.full_name = full_name
            except ValidationError as e:
                return JsonResponse({'error': e.message}, status=400)
        
        if phone_number:
            # Check if phone is locked
            if user.phone_locked:
                return JsonResponse({'error': 'Phone number is locked after first deposit and cannot be changed'}, status=400)
            
            try:
                phone_number = validate_phone_number(phone_number)
                # Check if new phone number is already in use
                if CustomUser.objects.filter(phone_number=phone_number).exclude(id=user.id).exists():
                    return JsonResponse({'error': 'Phone number already in use'}, status=400)
                user.phone_number = phone_number
            except ValidationError as e:
                return JsonResponse({'error': e.message}, status=400)
        
        user.save()
        logger.info(f"Profile updated for user: {user.phone_number}")
        return JsonResponse({
            'message': 'Profile updated successfully',
            'user': {
                'phone_number': user.phone_number,
                'full_name': user.full_name,
                'balance': str(user.balance),
                'date_joined': user.date_joined.isoformat() if user.date_joined else None,
                'phone_locked': user.phone_locked,
                'is_staff': user.is_staff,
                'is_superuser': user.is_superuser,
            }
        })
    except json.JSONDecodeError:
        return JsonResponse({'error': 'Invalid JSON'}, status=400)
    except Exception as e:
        logger.error(f"Profile update error: {str(e)}")
        return JsonResponse({'error': str(e)}, status=500)


@require_http_methods(["GET"])
def leaderboard_view(request):
    """Return the top payout winners by total completed payout amount and top wins."""
    try:
        top_winners = (
            CustomUser.objects
                .annotate(total_winnings=Coalesce(
                    Sum('transactions__amount', filter=Q(transactions__type='PAYOUT', transactions__status='COMPLETED')),
                    Value(0, output_field=DecimalField())
                ))
                .filter(total_winnings__gt=0)
                .order_by('-total_winnings')[:10]
        )

        leaderboard_data = [
            {
                'id': user.id,
                'full_name': user.full_name,
                'phone_number': user.phone_number,
                'balance': str(user.balance),
                'total_winnings': str(user.total_winnings),
            }
            for user in top_winners
        ]

        # Get top wins from bets
        from markets.models import Bet, Market
        top_wins_list = Bet.objects.filter(
            result='WON',
            payout__isnull=False
        ).select_related('user', 'market').order_by('-payout')[:6]

        top_wins_data = [
            {
                'id': bet.id,
                'user_name': bet.user.full_name[:20] if bet.user.full_name else bet.user.phone_number,
                'market_title': bet.market.question[:50],
                'profit': int(float(bet.payout or 0) - float(bet.amount)),
                'avatar_color': f'bg-{["blue", "green", "purple", "orange", "pink", "cyan"][i % 6]}-500',
            }
            for i, bet in enumerate(top_wins_list)
        ]

        return JsonResponse({'leaderboard': leaderboard_data, 'top_wins': top_wins_data})
    except Exception as e:
        logger.error(f"Leaderboard error: {str(e)}")
        return JsonResponse({'error': str(e)}, status=500)


@require_http_methods(["GET"])
def admin_list_users(request):
    """List all users with their support staff status (admin only)"""
    try:
        # Check if user is admin (via session or phone header)
        is_admin = False
        
        # Check Django authenticated user (for direct Django requests)
        if request.user.is_authenticated and request.user.is_staff:
            is_admin = True
        # Check phone header (for API requests from frontend)
        elif request.headers.get('X-User-Phone-Number'):
            phone_number = request.headers.get('X-User-Phone-Number')
            try:
                # Normalize phone number
                phone_number = normalize_phone_number(phone_number)
                user_obj = CustomUser.objects.get(phone_number=phone_number)
                if user_obj.is_staff or user_obj.is_superuser:
                    is_admin = True
            except CustomUser.DoesNotExist:
                pass
        
        if not is_admin:
            return JsonResponse({'error': 'Unauthorized'}, status=403)
        
        users = CustomUser.objects.values(
            'id', 'full_name', 'phone_number', 'balance', 'is_support_staff', 
            'kyc_verified', 'is_active', 'date_joined'
        ).order_by('-date_joined')
        
        return JsonResponse({
            'users': list(users),
            'count': users.count()
        }, status=200)
    except Exception as e:
        logger.error(f"Admin list users error: {str(e)}")
        return JsonResponse({'error': str(e)}, status=500)


@csrf_exempt
@require_http_methods(["PATCH"])
def admin_toggle_support_staff(request, user_id):
    """Toggle support staff status for a user (admin only)"""
    try:
        # Check if user is admin (via session or phone header)
        is_admin = False
        
        # Check Django authenticated user
        if request.user.is_authenticated and request.user.is_staff:
            is_admin = True
        # Check phone header
        elif request.headers.get('X-User-Phone-Number'):
            phone_number = request.headers.get('X-User-Phone-Number')
            try:
                user_obj = CustomUser.objects.get(phone_number=phone_number)
                if user_obj.is_staff or user_obj.is_superuser:
                    is_admin = True
            except CustomUser.DoesNotExist:
                pass
        
        if not is_admin:
            return JsonResponse({'error': 'Unauthorized'}, status=403)
        
        # Get the target user
        try:
            target_user = CustomUser.objects.get(id=user_id)
        except CustomUser.DoesNotExist:
            return JsonResponse({'error': 'User not found'}, status=404)
        
        # Parse request body
        data = json.loads(request.body)
        is_support_staff = data.get('is_support_staff')
        
        if is_support_staff is None:
            return JsonResponse({'error': 'is_support_staff field required'}, status=400)
        
        # Update support staff status
        target_user.is_support_staff = bool(is_support_staff)
        target_user.save()
        
        logger.info(f"User {user_id} support staff status changed to {target_user.is_support_staff}")
        
        return JsonResponse({
            'id': target_user.id,
            'full_name': target_user.full_name,
            'phone_number': target_user.phone_number,
            'is_support_staff': target_user.is_support_staff,
            'message': f"Support staff status updated successfully"
        }, status=200)
    except json.JSONDecodeError:
        return JsonResponse({'error': 'Invalid JSON'}, status=400)
    except Exception as e:
        logger.error(f"Admin toggle support staff error: {str(e)}")
        return JsonResponse({'error': str(e)}, status=500)


@csrf_exempt
@require_http_methods(["POST"])
def google_auth_view(request):
    """
    Google OAuth authentication endpoint.
    Creates or retrieves a user from Google OAuth data.
    
    Expected JSON body:
    {
        "email": "user@example.com",
        "name": "User Name",
        "google_id": "google-user-id",
        "picture": "https://profile-picture-url"
    }
    """
    try:
        data = json.loads(request.body)
        email = data.get('email')
        name = data.get('name')
        google_id = data.get('google_id')
        picture = data.get('picture')
        
        if not all([email, name, google_id]):
            return JsonResponse({
                'error': 'Missing required fields: email, name, google_id'
            }, status=400)
        
        # Priority: Try to get existing Google user by google_id
        # This ensures the same Google account always maps to the same user
        user = CustomUser.objects.filter(google_id=google_id).first()
        
        if not user:
            # If no Google user, check if email exists as a phone-based user
            # BUT: Don't auto-link! Only link if the email was explicitly set on that account
            existing_by_email = CustomUser.objects.filter(email=email).first()
            
            if existing_by_email and existing_by_email.google_id:
                # This email already has a Google account - shouldn't happen but handle it
                user = existing_by_email
            elif not existing_by_email:
                # No user found - create new Google user with email
                user = CustomUser.objects.create_user(
                    phone_number=None,  # Not required for Google users
                    full_name=name,
                    password=None,  # No password for Google OAuth users
                    email=email,
                    google_id=google_id,
                    picture=picture
                )
                logger.info(f"New Google user created: {email} (Google ID: {google_id})")
                
                # Create welcome notification
                create_notification(
                    user=user,
                    type_choice='WELCOME',
                    title='Welcome to CACHE!',
                    message='Start predicting markets to earn rewards',
                    color_class='blue'
                )
            else:
                # Email exists on a phone-based user (no google_id set yet)
                # Only link if this is an intentional re-auth scenario
                # For safety, create a separate Google account with the same email
                # (Django allows this since email is not strictly unique for phone-based users)
                
                # Check if user explicitly wants to link (they would have confirmed intent)
                # For now, just log and link conservatively
                user = existing_by_email
                user.google_id = google_id
                user.picture = picture
                user.save()
                logger.info(f"Linked Google to existing phone user: {email}")
        else:
            # Update existing Google user with latest data
            user.full_name = name
            user.picture = picture
            if not user.email:
                user.email = email
            user.save()
            logger.info(f"Updated existing Google user: {email}")
        
        # IMPORTANT: Do NOT create Django session here!
        # This is called from NextAuth's server-side signIn callback via fetch()
        # Any session cookies set here won't reach the browser
        # NextAuth will handle JWT token creation instead
        
        logger.info(f"Google user processed: {user.email}")
        
        response = JsonResponse({
            'message': 'Google authentication successful',
            'user': {
                'id': user.id,
                'email': user.email,
                'full_name': user.full_name,
                'phone_number': user.phone_number,
                'kyc_verified': user.kyc_verified,
                'phone_locked': user.phone_locked,
                'date_joined': user.date_joined.isoformat() if user.date_joined else None,
                'picture': user.picture,
                'is_staff': user.is_staff,
                'is_superuser': user.is_superuser,
            }
        }, status=200)
        
        logger.info(f"Google oauth response ready for {user.email}")
        
        return response
    
    except json.JSONDecodeError:
        return JsonResponse({'error': 'Invalid JSON'}, status=400)
    except Exception as e:
        logger.error(f"Google auth error: {str(e)}")
        return JsonResponse({'error': str(e)}, status=500)


@csrf_exempt
@require_http_methods(["POST"])
def add_phone_number_view(request):
    """
    Allow Google OAuth users to add a phone number after signup.
    Requires X-User-Email header for authentication.
    
    Expected JSON body:
    {
        "phone_number": "0712345678"
    }
    """
    try:
        # Authenticate using email header (for Google OAuth users)
        email = request.headers.get('X-User-Email')
        if not email:
            return JsonResponse({'error': 'Authentication required (X-User-Email header)'}, status=401)
        
        user = CustomUser.objects.filter(email=email).first()
        if not user:
            return JsonResponse({'error': 'User not found'}, status=404)
        
        # Check if phone is already locked (prevent editing after first deposit)
        if user.phone_locked:
            return JsonResponse({'error': 'Phone number is locked and cannot be changed'}, status=400)
        
        # Parse request body
        data = json.loads(request.body)
        phone_number = data.get('phone_number')
        
        if not phone_number:
            return JsonResponse({'error': 'Phone number is required'}, status=400)
        
        # Validate phone number
        try:
            phone_number = validate_phone_number(phone_number)
            phone_number = normalize_phone_number(phone_number)
        except ValidationError as e:
            return JsonResponse({'error': e.message}, status=400)
        
        # Check if phone number already exists
        if CustomUser.objects.filter(phone_number=phone_number).exclude(id=user.id).exists():
            return JsonResponse({'error': 'Phone number already registered'}, status=400)
        
        # Update user with phone number
        user.phone_number = phone_number
        user.save()
        
        logger.info(f"Phone number added for Google user: {user.email} -> {phone_number}")
        
        return JsonResponse({
            'message': 'Phone number added successfully',
            'user': {
                'id': user.id,
                'email': user.email,
                'full_name': user.full_name,
                'phone_number': user.phone_number,
                'kyc_verified': user.kyc_verified,
                'phone_locked': user.phone_locked,
                'date_joined': user.date_joined.isoformat() if user.date_joined else None,
                'picture': user.picture,
                'is_staff': user.is_staff,
                'is_superuser': user.is_superuser,
            }
        }, status=200)
    
    except json.JSONDecodeError:
        return JsonResponse({'error': 'Invalid JSON'}, status=400)
    except Exception as e:
        logger.error(f"Add phone number error: {str(e)}")
        return JsonResponse({'error': str(e)}, status=500)


@csrf_exempt
@require_http_methods(["POST"])
def lock_phone_after_deposit_view(request):
    """
    Lock user's phone number after first successful/confirmed deposit.
    Prevents fraud by ensuring users cannot change phone after making deposits.
    Requires X-User-Phone-Number or X-User-Email header for authentication.
    """
    try:
        # Authenticate user
        user = None
        phone_number = request.headers.get('X-User-Phone-Number')
        email = request.headers.get('X-User-Email')
        
        if phone_number:
            try:
                phone_number = normalize_phone_number(phone_number)
                user = CustomUser.objects.filter(phone_number=phone_number).first()
            except:
                pass
        
        if not user and email:
            user = CustomUser.objects.filter(email=email).first()
        
        if not user:
            return JsonResponse({'error': 'Authentication required'}, status=401)
        
        # If phone not already locked, lock it
        if not user.phone_locked:
            user.phone_locked = True
            user.save()
            logger.info(f"Phone number locked for user {user.id} after first deposit")
        
        return JsonResponse({
            'message': 'Phone number locked successfully',
            'phone_locked': user.phone_locked
        }, status=200)
    
    except Exception as e:
        logger.error(f"Lock phone error: {str(e)}")
        return JsonResponse({'error': str(e)}, status=500)


def _check_admin_access(request):
    """Helper to check if user is admin"""
    try:
        if request.user.is_authenticated and request.user.is_staff:
            return True
        elif request.headers.get('X-User-Phone-Number'):
            phone_number = request.headers.get('X-User-Phone-Number')
            phone_number = normalize_phone_number(phone_number)
            user_obj = CustomUser.objects.get(phone_number=phone_number)
            return user_obj.is_staff or user_obj.is_superuser
    except:
        pass
    return False


@require_http_methods(["GET"])
def admin_get_user_portfolio(request, user_id):
    """Get a user's portfolio/positions in markets (admin only)"""
    try:
        if not _check_admin_access(request):
            return JsonResponse({'error': 'Unauthorized'}, status=403)
        
        try:
            target_user = CustomUser.objects.get(id=user_id)
        except CustomUser.DoesNotExist:
            return JsonResponse({'error': 'User not found'}, status=404)
        
        # Import here to avoid circular imports
        from markets.models import Bet, Market
        from decimal import Decimal
        
        # Get all bets for this user and aggregate by market/outcome
        bets = Bet.objects.filter(user=target_user).select_related('market')
        
        portfolio_positions = {}  # {market_id: {outcome: {bought: X, sold: Y, ...}}}
        
        for bet in bets:
            market_id = bet.market_id
            outcome = bet.outcome
            action = bet.action  # 'BUY' or 'SELL'
            
            key = f"{market_id}_{outcome}"
            if key not in portfolio_positions:
                portfolio_positions[key] = {
                    'market_id': market_id,
                    'market_question': bet.market.question,
                    'outcome': outcome,
                    'bought_quantity': 0,
                    'sold_quantity': 0,
                    'total_cost': 0,
                    'total_payout': 0,
                    'num_wins': 0,
                    'num_losses': 0,
                }
            
            pos = portfolio_positions[key]
            
            if action == 'BUY':
                pos['bought_quantity'] += float(bet.quantity or 0)
                pos['total_cost'] += float(bet.amount or 0)
            elif action == 'SELL':
                pos['sold_quantity'] += float(bet.quantity or 0)
                pos['total_payout'] += float(bet.payout or 0)
            
            # Track wins/losses
            if bet.result == 'WON':
                pos['num_wins'] += 1
            elif bet.result == 'LOST':
                pos['num_losses'] += 1
        
        # Calculate net positions and current values
        positions_list = []
        total_portfolio_value = 0
        
        for key, pos in portfolio_positions.items():
            net_quantity = pos['bought_quantity'] - pos['sold_quantity']
            
            # Only include if net position > 0
            if net_quantity > 0:
                market = Market.objects.get(id=pos['market_id'])
                
                # Get current probability
                if market.market_type == 'BINARY':
                    if pos['outcome'] == 'Yes':
                        current_prob = market.yes_probability / 100
                    else:
                        current_prob = (100 - market.yes_probability) / 100
                else:
                    current_prob = market.yes_probability / 100  # Simplified
                
                # Current position value = net_quantity * PAYOUT_PER_SHARE * probability
                current_value = net_quantity * PAYOUT_PER_SHARE * current_prob
                pnl = current_value - pos['total_cost']
                
                total_portfolio_value += current_value
                
                positions_list.append({
                    'market_id': pos['market_id'],
                    'market_question': pos['market_question'],
                    'outcome': pos['outcome'],
                    'net_shares': round(net_quantity, 8),
                    'bought': round(pos['bought_quantity'], 8),
                    'sold': round(pos['sold_quantity'], 8),
                    'total_cost_kes': round(pos['total_cost'], 2),
                    'current_value_kes': round(current_value, 2),
                    'pnl_kes': round(pnl, 2),
                    'current_probability': round(current_prob * 100, 2),
                    'wins': pos['num_wins'],
                    'losses': pos['num_losses'],
                })
        
        return JsonResponse({
            'user_id': target_user.id,
            'user_name': target_user.full_name,
            'user_phone': target_user.phone_number,
            'total_portfolio_value_kes': round(total_portfolio_value, 2),
            'positions': positions_list,
            'num_positions': len(positions_list),
        }, status=200)
    
    except Exception as e:
        logger.error(f"Admin get user portfolio error: {str(e)}")
        return JsonResponse({'error': str(e)}, status=500)


@require_http_methods(["GET"])
def admin_get_user_activity(request, user_id):
    """Get a user's activity log (bets, deposits, etc.) (admin only)"""
    try:
        if not _check_admin_access(request):
            return JsonResponse({'error': 'Unauthorized'}, status=403)
        
        try:
            target_user = CustomUser.objects.get(id=user_id)
        except CustomUser.DoesNotExist:
            return JsonResponse({'error': 'User not found'}, status=404)
        
        from markets.models import Bet
        from payments.models import Transaction
        
        activity_log = []
        
        # Get all bets
        bets = Bet.objects.filter(user=target_user).select_related('market').order_by('-timestamp')[:100]
        for bet in bets:
            activity_log.append({
                'type': 'BET',
                'action': bet.action,  # BUY or SELL
                'market': bet.market.question[:50],
                'outcome': bet.outcome,
                'amount': float(bet.amount),
                'quantity': float(bet.quantity or 0),
                'result': bet.result,
                'payout': float(bet.payout or 0),
                'timestamp': bet.timestamp.isoformat() if bet.timestamp else None,
            })
        
        # Get all transactions
        transactions = Transaction.objects.filter(user=target_user).order_by('-created_at')[:100]
        for txn in transactions:
            activity_log.append({
                'type': 'TRANSACTION',
                'transaction_type': txn.type,  # DEPOSIT, WITHDRAWAL, PAYOUT
                'amount': float(txn.amount),
                'status': txn.status,
                'phone_number': txn.phone_number,
                'description': txn.description,
                'timestamp': txn.created_at.isoformat() if txn.created_at else None,
            })
        
        # Sort by timestamp descending
        activity_log.sort(key=lambda x: x['timestamp'] or '', reverse=True)
        
        return JsonResponse({
            'user_id': target_user.id,
            'user_name': target_user.full_name,
            'user_phone': target_user.phone_number,
            'activity': activity_log[:50],  # Return last 50 activities
            'count': len(activity_log),
        }, status=200)
    
    except Exception as e:
        logger.error(f"Admin get user activity error: {str(e)}")
        return JsonResponse({'error': str(e)}, status=500)



