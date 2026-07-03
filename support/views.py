from rest_framework.decorators import api_view, permission_classes
from rest_framework.response import Response
from rest_framework import status
from rest_framework.permissions import IsAuthenticated
from django.views.decorators.csrf import ensure_csrf_cookie
from .models import SupportMessage, SupportTicket
from .serializers import SupportMessageSerializer, SupportTicketSerializer, SupportTicketListSerializer
from users.models import CustomUser
from api.validators import normalize_phone_number

# ============ USER SUPPORT ENDPOINTS ============

@api_view(['GET'])
def get_my_tickets(request):
    """Get all support tickets for the authenticated user"""
    try:
        # Get user from phone number in header or from authenticated user
        phone_number = request.headers.get('X-User-Phone-Number')
        
        if phone_number:
            try:
                # Normalize phone number
                phone_number = normalize_phone_number(phone_number)
                user = CustomUser.objects.get(phone_number=phone_number)
            except CustomUser.DoesNotExist:
                return Response(
                    {'error': 'User not found'},
                    status=status.HTTP_404_NOT_FOUND
                )
        else:
            if not request.user.is_authenticated:
                return Response(
                    {'error': 'User not authenticated'},
                    status=status.HTTP_401_UNAUTHORIZED
                )
            user = request.user

        tickets = SupportTicket.objects.filter(user=user).prefetch_related('messages')
        serializer = SupportTicketListSerializer(tickets, many=True)
        
        return Response(serializer.data, status=status.HTTP_200_OK)
    
    except Exception as e:
        return Response(
            {'error': str(e)},
            status=status.HTTP_500_INTERNAL_SERVER_ERROR
        )


@api_view(['GET'])
def get_ticket_detail(request, ticket_id):
    """Get a specific support ticket with all messages"""
    try:
        phone_number = request.headers.get('X-User-Phone-Number')
        
        if phone_number:
            try:
                # Normalize phone number
                phone_number = normalize_phone_number(phone_number)
                user = CustomUser.objects.get(phone_number=phone_number)
            except CustomUser.DoesNotExist:
                return Response(
                    {'error': 'User not found'},
                    status=status.HTTP_404_NOT_FOUND
                )
        else:
            if not request.user.is_authenticated:
                return Response(
                    {'error': 'User not authenticated'},
                    status=status.HTTP_401_UNAUTHORIZED
                )
            user = request.user

        try:
            ticket = SupportTicket.objects.prefetch_related('messages').get(ticket_id=ticket_id, user=user)
        except SupportTicket.DoesNotExist:
            return Response(
                {'error': 'Ticket not found'},
                status=status.HTTP_404_NOT_FOUND
            )
        
        serializer = SupportTicketSerializer(ticket)
        return Response(serializer.data, status=status.HTTP_200_OK)
    
    except Exception as e:
        return Response(
            {'error': str(e)},
            status=status.HTTP_500_INTERNAL_SERVER_ERROR
        )


@ensure_csrf_cookie
@api_view(['POST'])
def create_support_ticket(request):
    """Create a new support ticket"""
    try:
        phone_number = request.headers.get('X-User-Phone-Number')
        
        if phone_number:
            try:
                # Normalize phone number
                phone_number = normalize_phone_number(phone_number)
                user = CustomUser.objects.get(phone_number=phone_number)
            except CustomUser.DoesNotExist:
                return Response(
                    {'error': 'User not found'},
                    status=status.HTTP_404_NOT_FOUND
                )
        else:
            if not request.user.is_authenticated:
                return Response(
                    {'error': 'User not authenticated'},
                    status=status.HTTP_401_UNAUTHORIZED
                )
            user = request.user

        subject = request.data.get('subject', '').strip()
        category = request.data.get('category', 'GENERAL').strip().upper()
        message_text = request.data.get('message', '').strip()
        
        if not subject:
            return Response(
                {'error': 'Subject cannot be empty'},
                status=status.HTTP_400_BAD_REQUEST
            )
        
        if not message_text:
            return Response(
                {'error': 'Message cannot be empty'},
                status=status.HTTP_400_BAD_REQUEST
            )

        if category not in dict(SupportTicket.CATEGORY_CHOICES):
            return Response(
                {'error': 'Invalid ticket category'},
                status=status.HTTP_400_BAD_REQUEST
            )

        # Create the ticket
        ticket = SupportTicket.objects.create(
            user=user,
            subject=subject,
            category=category,
        )
        
        # Add initial message
        SupportMessage.objects.create(
            ticket=ticket,
            sender=user,
            message=message_text,
            is_from_user=True
        )

        serializer = SupportTicketSerializer(ticket)
        
        return Response(
            serializer.data,
            status=status.HTTP_201_CREATED
        )
    
    except Exception as e:
        return Response(
            {'error': str(e)},
            status=status.HTTP_500_INTERNAL_SERVER_ERROR
        )


@api_view(['POST'])
def add_message_to_ticket(request, ticket_id):
    """Add a message to an existing ticket"""
    try:
        phone_number = request.headers.get('X-User-Phone-Number')
        
        if phone_number:
            try:
                # Normalize phone number
                phone_number = normalize_phone_number(phone_number)
                user = CustomUser.objects.get(phone_number=phone_number)
            except CustomUser.DoesNotExist:
                return Response(
                    {'error': 'User not found'},
                    status=status.HTTP_404_NOT_FOUND
                )
        else:
            if not request.user.is_authenticated:
                return Response(
                    {'error': 'User not authenticated'},
                    status=status.HTTP_401_UNAUTHORIZED
                )
            user = request.user

        try:
            ticket = SupportTicket.objects.get(ticket_id=ticket_id, user=user)
        except SupportTicket.DoesNotExist:
            return Response(
                {'error': 'Ticket not found'},
                status=status.HTTP_404_NOT_FOUND
            )

        message_text = request.data.get('message', '').strip()
        
        if not message_text:
            return Response(
                {'error': 'Message cannot be empty'},
                status=status.HTTP_400_BAD_REQUEST
            )

        # Create the message
        message = SupportMessage.objects.create(
            ticket=ticket,
            sender=user,
            message=message_text,
            is_from_user=True
        )

        serializer = SupportMessageSerializer(message)
        
        return Response(
            {'message': serializer.data},
            status=status.HTTP_201_CREATED
        )
    
    except Exception as e:
        return Response(
            {'error': str(e)},
            status=status.HTTP_500_INTERNAL_SERVER_ERROR
        )


# ============ SUPPORT STAFF ENDPOINTS ============

@api_view(['GET'])
def support_dashboard_tickets(request):
    """Get all tickets for support staff dashboard"""
    try:
        # Check if user is support staff
        if not request.user.is_authenticated or not request.user.is_support_staff:
            return Response(
                {'error': 'Only support staff can access this endpoint'},
                status=status.HTTP_403_FORBIDDEN
            )
        
        # Get filter parameters
        status_filter = request.query_params.get('status')
        assigned_filter = request.query_params.get('assigned')  # 'me', 'unassigned', 'all'
        
        tickets = SupportTicket.objects.all().prefetch_related('messages')
        
        if status_filter:
            tickets = tickets.filter(status=status_filter)
        
        if assigned_filter == 'me':
            tickets = tickets.filter(assigned_to=request.user)
        elif assigned_filter == 'unassigned':
            tickets = tickets.filter(assigned_to__isnull=True)
        
        serializer = SupportTicketListSerializer(tickets, many=True)
        return Response(serializer.data, status=status.HTTP_200_OK)
    
    except Exception as e:
        return Response(
            {'error': str(e)},
            status=status.HTTP_500_INTERNAL_SERVER_ERROR
        )


@api_view(['GET'])
def support_dashboard_ticket_detail(request, ticket_id):
    """Get detailed ticket for support staff"""
    try:
        if not request.user.is_authenticated or not request.user.is_support_staff:
            return Response(
                {'error': 'Only support staff can access this endpoint'},
                status=status.HTTP_403_FORBIDDEN
            )
        
        try:
            ticket = SupportTicket.objects.prefetch_related('messages').get(ticket_id=ticket_id)
        except SupportTicket.DoesNotExist:
            return Response(
                {'error': 'Ticket not found'},
                status=status.HTTP_404_NOT_FOUND
            )
        
        serializer = SupportTicketSerializer(ticket)
        return Response(serializer.data, status=status.HTTP_200_OK)
    
    except Exception as e:
        return Response(
            {'error': str(e)},
            status=status.HTTP_500_INTERNAL_SERVER_ERROR
        )


@api_view(['PATCH'])
def update_ticket(request, ticket_id):
    """Update ticket status or assignment"""
    try:
        if not request.user.is_authenticated or not request.user.is_support_staff:
            return Response(
                {'error': 'Only support staff can access this endpoint'},
                status=status.HTTP_403_FORBIDDEN
            )
        
        try:
            ticket = SupportTicket.objects.get(ticket_id=ticket_id)
        except SupportTicket.DoesNotExist:
            return Response(
                {'error': 'Ticket not found'},
                status=status.HTTP_404_NOT_FOUND
            )
        
        # Update status if provided
        new_status = request.data.get('status')
        if new_status and new_status in [choice[0] for choice in SupportTicket.STATUS_CHOICES]:
            ticket.status = new_status
        
        # Update assignment if provided
        assigned_to_id = request.data.get('assigned_to')
        if assigned_to_id is not None:
            if assigned_to_id == 'null' or assigned_to_id is None:
                ticket.assigned_to = None
            else:
                try:
                    assigned_user = CustomUser.objects.get(id=assigned_to_id, is_support_staff=True)
                    ticket.assigned_to = assigned_user
                except CustomUser.DoesNotExist:
                    return Response(
                        {'error': 'Support staff member not found'},
                        status=status.HTTP_404_NOT_FOUND
                    )
        
        ticket.save()
        serializer = SupportTicketSerializer(ticket)
        
        return Response(serializer.data, status=status.HTTP_200_OK)
    
    except Exception as e:
        return Response(
            {'error': str(e)},
            status=status.HTTP_500_INTERNAL_SERVER_ERROR
        )


@api_view(['POST'])
def support_reply(request, ticket_id):
    """Support staff reply to a ticket"""
    try:
        if not request.user.is_authenticated or not request.user.is_support_staff:
            return Response(
                {'error': 'Only support staff can access this endpoint'},
                status=status.HTTP_403_FORBIDDEN
            )
        
        try:
            ticket = SupportTicket.objects.get(ticket_id=ticket_id)
        except SupportTicket.DoesNotExist:
            return Response(
                {'error': 'Ticket not found'},
                status=status.HTTP_404_NOT_FOUND
            )

        message_text = request.data.get('message', '').strip()
        
        if not message_text:
            return Response(
                {'error': 'Message cannot be empty'},
                status=status.HTTP_400_BAD_REQUEST
            )

        # Create the message from support staff
        message = SupportMessage.objects.create(
            ticket=ticket,
            sender=request.user,
            message=message_text,
            is_from_user=False
        )

        serializer = SupportMessageSerializer(message)
        
        return Response(
            {'message': serializer.data},
            status=status.HTTP_201_CREATED
        )
    
    except Exception as e:
        return Response(
            {'error': str(e)},
            status=status.HTTP_500_INTERNAL_SERVER_ERROR
        )


@api_view(['GET'])
def support_staff_list(request):
    """Get list of all support staff members"""
    try:
        if not request.user.is_authenticated:
            return Response(
                {'error': 'User not authenticated'},
                status=status.HTTP_401_UNAUTHORIZED
            )
        
        staff = CustomUser.objects.filter(is_support_staff=True).values('id', 'full_name', 'phone_number')
        return Response(staff, status=status.HTTP_200_OK)
    
    except Exception as e:
        return Response(
            {'error': str(e)},
            status=status.HTTP_500_INTERNAL_SERVER_ERROR
        )
