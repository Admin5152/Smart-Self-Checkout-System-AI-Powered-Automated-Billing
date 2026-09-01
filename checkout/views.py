from django.shortcuts import render, redirect
import time
import hmac
import hashlib
import json
import requests
import logging
from datetime import datetime, timedelta
from collections import defaultdict

from decimal import Decimal
from django.conf import settings
from django.core.mail import send_mail
from django.http import HttpResponse, StreamingHttpResponse, JsonResponse
from django.views.decorators.csrf import csrf_exempt
from rest_framework.decorators import api_view
from rest_framework.response import Response
from django.db import transaction as db_transaction
from django.core.exceptions import SuspiciousOperation
from django.views.decorators.http import require_http_methods
from django.contrib.auth.decorators import login_required
from django.http import Http404
from django.db import models as django_models
from django.db.models import Sum, Count
from .models import (
    Product, CartItem, Cart, Transaction, TransactionItem, 
    Customer, EmergencyReport, DetectionLog, PaymentMethod, 
    Payment, Receipt, Admin, Category
)
from .serializers import CartItemSerializer, ProductSerializer

logger = logging.getLogger(__name__)

CAMERA_STREAM_URL = getattr(settings, 'CAMERA_STREAM_URL', 'http://127.0.0.1:5001/video_feed')

# Store last detection in memory (simple implementation)
last_detection = {
    'class_name': None,
    'confidence': None,
    'fps': None,
    'timestamp': None,
    'last_activity_at': None,
    'added_to_cart': False,
    'product_id': None,
    'product_name': None,
    'needs_confirm': False,
}
detection_paused = False
LOW_CONFIDENCE_THRESHOLD = 70
DETECTOR_ONLINE_WINDOW_SEC = 15
DETECTION_DISPLAY_WINDOW_SEC = 3

# Admin session key
ADMIN_SESSION_KEY = 'admin_id'


def _is_fake_guest_email(email):
    email = (email or '').strip().lower()
    return (
        not email
        or email.endswith('@guest.scanandgo.local')
        or email.endswith('@scanandgo.local')
        or email == 'guest@scanandgo.local'
    )


def _mark_transaction_paid(transaction, reference=None):
    """Mark transaction paid, clear cart. Returns response payload dict."""
    if reference:
        transaction.reference = reference
    transaction.status = 'paid'
    transaction.save()

    # Clear items from active cart
    cart, created = Cart.objects.get_or_create(status='active')
    cart.cartitem_set.all().update(quantity=0)

    return {
        'status': 'ok',
        'transaction_id': transaction.transaction_id,
        'order_id': transaction.transaction_id,
        'amount': str(transaction.total_amount),
        'saved_to_history': bool(transaction.customer_id),
    }

@csrf_exempt
@api_view(['POST', 'OPTIONS'])
def detect_object(request):
    if request.method == 'OPTIONS':
        return Response({'status': 'ok'})

    if detection_paused:
        return Response({'status': 'paused', 'message': 'Detection is paused'}, status=200)

    class_name = request.data.get('class_name')
    confidence = request.data.get('confidence')
    fps = request.data.get('fps')

    if not class_name:
        return Response({'error': 'class_name is required'}, status=400)

    try:
        conf_val = float(confidence) if confidence is not None else 0.0
    except (TypeError, ValueError):
        conf_val = 0.0

    now = time.time()
    last_detection.update({
        'class_name': class_name,
        'confidence': conf_val,
        'fps': fps,
        'timestamp': now,
        'last_activity_at': now,
        'added_to_cart': False,
        'product_id': None,
        'product_name': None,
        'needs_confirm': False,
    })

    try:
        product = Product.objects.get(yolo_class_name__iexact=class_name.lower())
        was_accepted = conf_val >= LOW_CONFIDENCE_THRESHOLD
    except Product.DoesNotExist:
        product = None
        was_accepted = False

    # Log detection
    DetectionLog.objects.create(
        product=product,
        detected_class=class_name,
        confidence_score=conf_val,
        was_accepted=was_accepted
    )

    if not was_accepted or product is None:
        return Response({
            'status': 'rejected',
            'reason': 'Low confidence or unrecognised',
            'confidence': conf_val
        })

    last_detection['product_id'] = product.id
    last_detection['product_name'] = product.display_name

    # Get or create active cart
    cart, created = Cart.objects.get_or_create(status='active')
    
    # Get or create cart item
    cart_item, created = CartItem.objects.get_or_create(
        cart=cart,
        product=product,
        defaults={'quantity': 1}
    )
    if not created:
        cart_item.quantity += 1
        cart_item.save()
    
    last_detection['added_to_cart'] = True
    last_detection['needs_confirm'] = False

    return Response({
        'status': 'ok',
        'product': product.display_name,
        'product_id': product.id,
        'quantity': cart_item.quantity,
        'added': True,
    })


@csrf_exempt
@api_view(['GET', 'OPTIONS'])
def get_cart(request):
    if request.method == 'OPTIONS':
        return Response({'status': 'ok'})
    
    # Get active cart or create one
    cart, created = Cart.objects.get_or_create(status='active')
    
    # Get cart items from the active cart
    items = cart.cartitem_set.filter(quantity__gt=0)
    serializer = CartItemSerializer(items, many=True)

    total = sum((item.subtotal() for item in items), Decimal('0.00'))

    return Response({'items': serializer.data, 'total': str(total)})


@csrf_exempt
@api_view(['POST', 'OPTIONS'])
def adjust_cart(request):
    if request.method == 'OPTIONS':
        return Response({'status': 'ok'})
    product_id = request.data.get('product_id')
    delta = request.data.get('delta', 0)

    if not product_id or delta is None:
        return Response({'error': 'product_id and delta are required'}, status=400)

    try:
        product = Product.objects.get(id=product_id)
    except Product.DoesNotExist:
        return Response({'error': f'Product not found'}, status=404)

    # Get or create active cart
    cart, created = Cart.objects.get_or_create(status='active')
    
    cart_item, created = CartItem.objects.get_or_create(
        cart=cart,
        product=product,
        defaults={'quantity': 0}
    )
    cart_item.quantity += delta
    if cart_item.quantity <= 0:
        cart_item.quantity = 0
    cart_item.save()

    return Response({'status': 'ok', 'quantity': cart_item.quantity})


@csrf_exempt
@api_view(['GET', 'OPTIONS'])
def get_products(request):
    if request.method == 'OPTIONS':
        return Response({'status': 'ok'})
    products = Product.objects.all()
    serializer = ProductSerializer(products, many=True)
    return Response(serializer.data)


@csrf_exempt
@api_view(['POST', 'OPTIONS'])
def clear_cart(request):
    if request.method == 'OPTIONS':
        return Response({'status': 'ok'})
    
    # Clear items from active cart
    cart, created = Cart.objects.get_or_create(status='active')
    cart.cartitem_set.all().update(quantity=0)
    
    return Response({'status': 'cart cleared'})


@csrf_exempt
@api_view(['GET', 'OPTIONS'])
def get_last_detection(request):
    if request.method == 'OPTIONS':
        return Response({'status': 'ok'})

    current_time = time.time()
    activity_at = last_detection.get('last_activity_at')
    event_at = last_detection.get('timestamp')

    # Clear display fields when the flash window ends; keep activity for connectivity
    if event_at and (current_time - event_at) > DETECTION_DISPLAY_WINDOW_SEC:
        last_detection.update({
            'class_name': None,
            'confidence': None,
            'timestamp': None,
            'added_to_cart': False,
            'product_id': None,
            'product_name': None,
            'needs_confirm': False,
        })

    detector_online = bool(
        activity_at and (current_time - activity_at) <= DETECTOR_ONLINE_WINDOW_SEC
    )

    payload = last_detection.copy()
    payload['paused'] = detection_paused
    payload['detector_online'] = detector_online
    payload['online_window_sec'] = DETECTOR_ONLINE_WINDOW_SEC
    payload['low_confidence_threshold'] = LOW_CONFIDENCE_THRESHOLD
    if activity_at:
        payload['seconds_since_activity'] = round(current_time - activity_at, 2)
    else:
        payload['seconds_since_activity'] = None
    return Response(payload)


@csrf_exempt
@api_view(['POST', 'OPTIONS'])
def pause_detection(request):
    global detection_paused
    if request.method == 'OPTIONS':
        return Response({'status': 'ok'})
    detection_paused = True
    return Response({'status': 'ok', 'paused': True})


@csrf_exempt
@api_view(['POST', 'OPTIONS'])
def resume_detection(request):
    global detection_paused
    if request.method == 'OPTIONS':
        return Response({'status': 'ok'})
    detection_paused = False
    return Response({'status': 'ok', 'paused': False})


def checkout_page(request):
    return render(request, 'checkout/checkout.html')


def camera_page(request):
    return render(request, 'checkout/camera.html')


@csrf_exempt
def camera_stream_proxy(request):
    """
    Same-origin proxy for the YOLO MJPEG feed so the browser can display it reliably
    while yolo_detect.py serves http://127.0.0.1:5001/video_feed.
    """
    try:
        upstream = requests.get(CAMERA_STREAM_URL, stream=True, timeout=(3, 120))
    except requests.exceptions.RequestException as exc:
        logger.debug('Camera stream unavailable: %s', exc)
        return HttpResponse(
            'Camera offline — start yolo_detect.py on port 5001',
            status=502,
            content_type='text/plain',
        )

    if upstream.status_code != 200:
        return HttpResponse('Camera stream error', status=502, content_type='text/plain')

    content_type = upstream.headers.get(
        'Content-Type',
        'multipart/x-mixed-replace; boundary=frame',
    )

    def generate():
        try:
            for chunk in upstream.iter_content(chunk_size=4096):
                if chunk:
                    yield chunk
        except Exception:
            return
        finally:
            upstream.close()

    response = StreamingHttpResponse(generate(), content_type=content_type)
    response['Cache-Control'] = 'no-cache, no-store, must-revalidate'
    response['Pragma'] = 'no-cache'
    response['X-Accel-Buffering'] = 'no'
    return response


# ==================================================
# -------- Payment: Cash + Paystack --------
# ==================================================

def _cart_snapshot_and_total():
    """Builds a snapshot of the current cart and computes the cart total (no tax/discount)."""
    # Get active cart
    cart, created = Cart.objects.get_or_create(status='active')
    
    items = cart.cartitem_set.filter(quantity__gt=0)
    total = sum((item.subtotal() for item in items), Decimal('0.00'))
    snapshot = [
        {'name': i.product.display_name, 'qty': i.quantity, 'price': str(i.product.price)}
        for i in items
    ]
    return snapshot, total, Decimal('0.00'), total


def _compute_checksum_total(cart):
    """Recompute the grand total directly from CartItem rows for checksum validation."""
    return sum(
        item.quantity * item.product.price
        for item in cart.cartitem_set.select_related('product')
    )


def _resolve_customer(request_data):
    """Resolve Customer from customer_id or name/email/phone payload."""
    if request_data.get('is_guest') or request_data.get('save_history') is False:
        return None

    customer_id = request_data.get('customer_id')
    if customer_id not in (None, '', 'null'):
        try:
            return Customer.objects.get(id=int(customer_id))
        except (Customer.DoesNotExist, TypeError, ValueError):
            return None

    email = (request_data.get('customer_email') or request_data.get('email') or '').strip().lower()
    if not email or email.endswith('@guest.scanandgo.local'):
        return None
    return Customer.objects.filter(email__iexact=email).first()


def _order_customer_fields(customer, request_data=None):
    if customer:
        return {
            'customer': customer,
            'customer_name': customer.name,
            'customer_email': customer.email,
            'customer_phone': customer.phone,
        }
    # Guest / anonymous checkout — optional label only, no Customer FK (history not saved)
    if request_data and (request_data.get('is_guest') or request_data.get('save_history') is False):
        return {
            'customer': None,
            'customer_name': (request_data.get('customer_name') or 'Guest').strip() or 'Guest',
            'customer_email': None,
            'customer_phone': None,
        }
    return {}


def _serialize_customer_orders(customer):
    transactions = customer.transactions.exclude(status='pending').order_by('-timestamp')[:20]
    return [
        {
            'id': t.transaction_id,
            'date': t.timestamp.isoformat(),
            'items_snapshot': t.items_snapshot,
            'amount': str(t.total_amount),
            'payment_method': t.payment_method,
            'status': t.status,
        }
        for t in transactions
    ]


@csrf_exempt
@api_view(['POST', 'OPTIONS'])
def identify_customer(request):
    if request.method == 'OPTIONS':
        return Response({'status': 'ok'})

    name = (request.data.get('name') or '').strip()
    email = (request.data.get('email') or '').strip().lower()
    phone = (request.data.get('phone') or '').strip()

    if not name or not email or not phone:
        return Response(
            {'error': 'name, email, and phone are all required'},
            status=400,
        )

    customer = Customer.objects.filter(email__iexact=email).first()
    is_returning = False

    if customer:
        is_returning = True
        # Keep profile current without creating a duplicate (email is the unique key)
        customer.name = name
        customer.phone = phone
        customer.save(update_fields=['name', 'phone'])
    else:
        # Optional phone match for recognition when email is new
        by_phone = Customer.objects.filter(phone=phone).first()
        if by_phone:
            customer = by_phone
            is_returning = True
            customer.name = name
            email_taken = Customer.objects.filter(email__iexact=email).exclude(id=by_phone.id).exists()
            if not email_taken:
                customer.email = email
            customer.save()
        else:
            customer = Customer.objects.create(name=name, email=email, phone=phone)

    payload = {
        'customer_id': customer.id,
        'is_returning': is_returning,
        'name': customer.name,
        'email': customer.email,
        'phone': customer.phone,
        'orders': _serialize_customer_orders(customer) if is_returning else [],
    }
    return Response(payload)


@csrf_exempt
@api_view(['POST', 'OPTIONS'])
def checkout_cash(request):
    if request.method == 'OPTIONS':
        return Response({'status': 'ok'})

    snapshot, subtotal, tax, total = _cart_snapshot_and_total()
    if not snapshot:
        return Response({'error': 'Cart is empty'}, status=400)

    customer = _resolve_customer(request.data)
    is_guest = bool(request.data.get('is_guest') or request.data.get('save_history') is False)

    # Guest skip sessions: clear cart without saving a history record
    if is_guest:
        # Clear items from active cart
        cart, created = Cart.objects.get_or_create(status='active')
        cart.cartitem_set.all().update(quantity=0)
        
        label = (request.data.get('customer_name') or 'Guest').replace(' ', '')
        return Response({
            'status': 'ok',
            'transaction_id': f'GUEST-{label}',
            'amount': str(total),
            'saved_to_history': False,
        })

    # Get or create active cart for checksum validation
    cart, created = Cart.objects.get_or_create(status='active')
    
    # Checksum validation
    server_total = _compute_checksum_total(cart)
    if server_total != total:
        # Log discrepancy and use server-computed total
        logger.warning(f'Checksum mismatch: client reported {total}, server computed {server_total}')
        total = server_total

    # Create transaction with atomic transaction handling
    @db_transaction.atomic
    def create_transaction():
        transaction = Transaction.objects.create(
            payment_method='cash',
            status='paid',
            total_amount=total,
            items_snapshot=snapshot,
            cart=cart,
            **_order_customer_fields(customer, request.data),
        )
        
        # Create transaction items
        for item_data in snapshot:
            product = Product.objects.get(display_name=item_data['name'])
            line_total = item_data['qty'] * product.price
            TransactionItem.objects.create(
                transaction=transaction,
                product=product,
                quantity=item_data['qty'],
                unit_price=product.price,
                line_total=line_total
            )
        
        # Mark cart as completed
        cart.status = 'completed'
        cart.save(update_fields=['status'])
        
        return transaction

    transaction = create_transaction()
    # Clear items from active cart  
    cart, created = Cart.objects.get_or_create(status='active')
    cart.cartitem_set.all().update(quantity=0)

    return Response({
        'status': 'ok',
        'transaction_id': transaction.transaction_id,
        'amount': str(transaction.total_amount),
        'saved_to_history': True,
    })


@csrf_exempt
@api_view(['POST', 'OPTIONS'])
def checkout_paystack_init(request):
    if request.method == 'OPTIONS':
        return Response({'status': 'ok'})

    public_key = getattr(settings, 'PAYSTACK_PUBLIC_KEY', '') or ''
    secret_key = getattr(settings, 'PAYSTACK_SECRET_KEY', '') or ''
    if not public_key or not secret_key:
        return Response({
            'error': 'Paystack is not configured. Set PAYSTACK_PUBLIC_KEY and PAYSTACK_SECRET_KEY in .env'
        }, status=503)

    snapshot, subtotal, tax, total = _cart_snapshot_and_total()
    if not snapshot:
        return Response({'error': 'Cart is empty'}, status=400)

    is_guest = bool(request.data.get('is_guest') or request.data.get('save_history') is False)
    customer = _resolve_customer(request.data)
    email = (customer.email if customer else (request.data.get('customer_email') or '')).strip()

    # Live Paystack requires a real customer email — guests use Cash only
    if is_guest or _is_fake_guest_email(email) or not customer:
        return Response({
            'error': 'Card payment needs a registered email. Use Continue with your details, or pay with Cash as a guest.'
        }, status=400)

    # Get or create active cart for checksum validation
    cart, created = Cart.objects.get_or_create(status='active')
    
    # Checksum validation
    server_total = _compute_checksum_total(cart)
    if server_total != total:
        # Log discrepancy and use server-computed total
        logger.warning(f'Checksum mismatch: client reported {total}, server computed {server_total}')
        total = server_total

    order = Transaction.objects.create(
        payment_method='paystack',
        status='pending',
        total_amount=total,
        items_snapshot=snapshot,
        cart=cart,
        **_order_customer_fields(customer, request.data),
    )

    return Response({
        'transaction_id': order.transaction_id,
        'order_id': order.transaction_id,
        'amount_kobo': int(total * 100),
        'currency': 'GHS',
        'public_key': public_key,
        'email': customer.email,
        'live': bool(getattr(settings, 'PAYSTACK_IS_LIVE', False)),
        'saved_to_history': True,
    })


@csrf_exempt
@api_view(['POST', 'OPTIONS'])
def checkout_paystack_verify(request):
    if request.method == 'OPTIONS':
        return Response({'status': 'ok'})

    reference = request.data.get('reference')
    transaction_id = request.data.get('transaction_id') or request.data.get('order_id')

    if not reference or not transaction_id:
        return Response({'error': 'reference and transaction_id are required'}, status=400)

    try:
        order = Transaction.objects.get(transaction_id=transaction_id)
    except Transaction.DoesNotExist:
        return Response({'error': 'Transaction not found'}, status=404)

    if order.status == 'paid':
        return Response({
            'status': 'ok',
            'transaction_id': order.transaction_id,
            'order_id': order.transaction_id,
            'amount': str(order.total_amount),
            'saved_to_history': bool(order.customer_id),
            'already_paid': True,
        })

    customer = _resolve_customer(request.data)
    if customer and not order.customer_id:
        for key, value in _order_customer_fields(customer).items():
            setattr(order, key, value)
        order.save()

    secret_key = getattr(settings, 'PAYSTACK_SECRET_KEY', '') or ''
    if not secret_key:
        return Response({'error': 'Paystack secret key missing'}, status=503)

    verify_url = f'https://api.paystack.co/transaction/verify/{reference}'
    headers = {'Authorization': f'Bearer {secret_key}'}

    try:
        resp = requests.get(verify_url, headers=headers, timeout=15)
        result = resp.json()
    except requests.exceptions.RequestException:
        return Response({'error': 'Could not reach Paystack'}, status=502)

    if not result.get('status'):
        order.status = 'failed'
        order.save(update_fields=['status'])
        return Response({'error': result.get('message') or 'Verification failed'}, status=400)

    data = result.get('data', {})
    paid_amount = Decimal(str(data.get('amount', 0))) / 100

    if data.get('status') == 'success' and paid_amount >= order.total_amount:
        return Response(_mark_transaction_paid(order, reference=reference))

    order.status = 'failed'
    order.save(update_fields=['status'])
    return Response({'error': 'Payment not successful'}, status=400)


@csrf_exempt
def paystack_webhook(request):
    """Paystack Live webhook — marks transactions paid even if the browser closes."""
    if request.method != 'POST':
        return HttpResponse(status=405)

    secret = getattr(settings, 'PAYSTACK_SECRET_KEY', '') or ''
    signature = request.headers.get('x-paystack-signature', '')
    body = request.body
    expected = hmac.new(secret.encode('utf-8'), body, hashlib.sha512).hexdigest()
    if not secret or not hmac.compare_digest(expected, signature):
        return HttpResponse(status=401)

    try:
        payload = json.loads(body.decode('utf-8'))
    except (UnicodeDecodeError, json.JSONDecodeError):
        return HttpResponse(status=400)

    event = payload.get('event')
    data = payload.get('data') or {}
    if event == 'charge.success':
        reference = data.get('reference') or ''
        transaction = None
        if reference.startswith('SG-'):
            parts = reference.split('-')
            if len(parts) >= 2 and parts[1].isdigit():
                transaction = Transaction.objects.filter(id=int(parts[1]), status='pending').first()
        if transaction is None and reference:
            transaction = Transaction.objects.filter(reference=reference).first()
        if transaction and transaction.status != 'paid':
            _mark_transaction_paid(transaction, reference=reference)
            logger.info('Paystack webhook marked transaction %s paid', transaction.transaction_id)

    return HttpResponse(status=200)


@csrf_exempt
@api_view(['POST', 'OPTIONS'])
def report_emergency(request):
    if request.method == 'OPTIONS':
        return Response({'status': 'ok'})

    category = (request.data.get('category') or '').strip()
    details = (request.data.get('details') or '').strip()
    transaction_id = (request.data.get('transaction_id') or '').strip() or None
    customer_name = (request.data.get('customer_name') or '').strip() or None
    customer_email = (request.data.get('customer_email') or '').strip() or None

    valid_categories = {c[0] for c in EmergencyReport.CATEGORY_CHOICES}
    if not category or category not in valid_categories:
        return Response({'error': 'A valid category is required'}, status=400)

    if category == 'other' and not details:
        return Response({'error': 'Details are required for Other complaint'}, status=400)

    report = EmergencyReport.objects.create(
        category=category,
        details=details,
        transaction_id=transaction_id,
        customer_name=customer_name,
        customer_email=customer_email,
    )

    alert_to = getattr(settings, 'EMERGENCY_ALERT_EMAIL', 'sethagyeimensah2@gmail.com')
    subject = f"[Scan & Go Emergency] #{report.id} — {report.get_category_display()}"
    body = (
        f"Emergency report #{report.id}\n"
        f"Category: {report.get_category_display()}\n"
        f"Status: {report.status}\n"
        f"Transaction ID: {report.transaction_id or '—'}\n"
        f"Customer: {report.customer_name or '—'} <{report.customer_email or '—'}>\n"
        f"Created: {report.created_at.isoformat()}\n\n"
        f"Details:\n{report.details or '(none)'}\n"
    )
    email_sent = False
    try:
        send_mail(
            subject,
            body,
            settings.DEFAULT_FROM_EMAIL,
            [alert_to],
            fail_silently=False,
        )
        email_sent = True
    except Exception as exc:
        logger.exception('Failed to send emergency alert email: %s', exc)

    return Response({
        'status': 'ok',
        'report_id': report.id,
        'email_sent': email_sent,
    })


# ==================================================
# -------- Admin Dashboard Views --------
# ==================================================

def admin_login(request):
    """Custom admin login page"""
    if request.method == 'POST':
        email = request.POST.get('email', '').strip()
        phone = request.POST.get('phone', '').strip()
        full_name = request.POST.get('full_name', '').strip()
        
        # Updated admin credentials - allow any combination
        try:
            admin = Admin.objects.get(email=email)
            # For now, allow login with just email match
            request.session[ADMIN_SESSION_KEY] = admin.admin_id
            return redirect('admin_dashboard')
        except Admin.DoesNotExist:
            return render(request, 'checkout/admin_login.html', {
                'error': 'Invalid credentials'
            })
    
    return render(request, 'checkout/admin_login.html')


def admin_logout(request):
    """Logout and redirect to login"""
    if ADMIN_SESSION_KEY in request.session:
        del request.session[ADMIN_SESSION_KEY]
    return redirect('admin_login')


def admin_required(view_func):
    """Decorator to require admin authentication"""
    def wrapper(request, *args, **kwargs):
        if ADMIN_SESSION_KEY not in request.session:
            return redirect('admin_login')
        return view_func(request, *args, **kwargs)
    return wrapper


@admin_required
def admin_dashboard(request):
    """Main admin dashboard with analytics"""
    admin_id = request.session[ADMIN_SESSION_KEY]
    try:
        admin = Admin.objects.get(admin_id=admin_id)
    except Admin.DoesNotExist:
        return redirect('admin_login')
    
    # Get dashboard statistics
    today = datetime.now().date()
    week_ago = today - timedelta(days=7)
    
    # Transaction statistics
    total_transactions = Transaction.objects.count()
    today_transactions = Transaction.objects.filter(timestamp__date=today).count()
    week_transactions = Transaction.objects.filter(timestamp__date__gte=week_ago).count()
    
    # Revenue statistics
    total_revenue = Transaction.objects.filter(status='paid').aggregate(
        total=Sum('total_amount')
    )['total'] or Decimal('0.00')
    
    today_revenue = Transaction.objects.filter(
        status='paid', 
        timestamp__date=today
    ).aggregate(total=Sum('total_amount'))['total'] or Decimal('0.00')
    
    # Customer statistics
    total_customers = Customer.objects.count()
    active_customers = Customer.objects.filter(
        transactions__timestamp__date__gte=week_ago
    ).distinct().count()
    
    # Detection statistics
    total_detections = DetectionLog.objects.count()
    accepted_detections = DetectionLog.objects.filter(was_accepted=True).count()
    detection_accuracy = (accepted_detections / total_detections * 100) if total_detections > 0 else 0
    
    # Recent transactions
    recent_transactions = Transaction.objects.select_related('customer').order_by('-timestamp')[:10]
    
    # Payment method breakdown
    payment_methods = list(Transaction.objects.values('payment_method').annotate(
        count=Count('transaction_id'),
        total=Sum('total_amount')
    ))
    
    # Daily transaction data for graph (last 7 days)
    daily_data = []
    for i in range(7):
        date = today - timedelta(days=i)
        day_transactions = Transaction.objects.filter(timestamp__date=date)
        daily_data.append({
            'date': date.strftime('%Y-%m-%d'),
            'count': day_transactions.count(),
            'revenue': float(day_transactions.aggregate(total=Sum('total_amount'))['total'] or 0)
        })
    daily_data.reverse()
    
    # Convert to JSON-serializable format
    import json
    daily_data_json = json.dumps(daily_data)
    payment_methods_json = json.dumps(payment_methods)
    
    context = {
        'admin': admin,
        'stats': {
            'total_transactions': total_transactions,
            'today_transactions': today_transactions,
            'week_transactions': week_transactions,
            'total_revenue': float(total_revenue),
            'today_revenue': float(today_revenue),
            'total_customers': total_customers,
            'active_customers': active_customers,
            'total_detections': total_detections,
            'accepted_detections': accepted_detections,
            'detection_accuracy': round(detection_accuracy, 2),
        },
        'recent_transactions': recent_transactions,
        'payment_methods': payment_methods_json,
        'daily_data': daily_data_json,
    }
    
    return render(request, 'checkout/admin_dashboard.html', context)


@admin_required
def admin_products(request):
    """Product management page"""
    products = Product.objects.select_related('category').all()
    categories = Category.objects.all()
    
    context = {
        'products': products,
        'categories': categories,
    }
    return render(request, 'checkout/admin_products.html', context)


@admin_required
def admin_customers(request):
    """Customer management page"""
    customers = Customer.objects.prefetch_related('transactions').all()
    
    context = {
        'customers': customers,
    }
    return render(request, 'checkout/admin_customers.html', context)


@admin_required
def admin_transactions(request):
    """Transaction management page"""
    transactions = Transaction.objects.select_related('customer').prefetch_related('transactionitem_set').all()
    
    context = {
        'transactions': transactions,
    }
    return render(request, 'checkout/admin_transactions.html', context)


@admin_required
def admin_detection_logs(request):
    """Detection logs viewing page"""
    logs = DetectionLog.objects.select_related('product').order_by('-timestamp')[:100]
    
    context = {
        'logs': logs,
    }
    return render(request, 'checkout/admin_detection_logs.html', context)


@admin_required
def admin_reports(request):
    """Emergency reports management page"""
    reports = EmergencyReport.objects.all().order_by('-created_at')
    
    context = {
        'reports': reports,
    }
    return render(request, 'checkout/admin_reports.html', context)
