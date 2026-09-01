import os
import django
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "checkout_system.settings")
django.setup()

from checkout.models import Cart, Transaction, Product, CartItem
from checkout.views import checkout_paystack_init, identify_customer
from django.test import RequestFactory
import json

Product.objects.get_or_create(display_name="Apple", yolo_class_name="apple", price=10)
cart, _ = Cart.objects.get_or_create(status='active')
product = Product.objects.get(yolo_class_name="apple")
CartItem.objects.get_or_create(cart=cart, product=product, quantity=1)

factory = RequestFactory()

# Create customer
req1 = factory.post('/api/customer/identify/', data=json.dumps({
    'name': 'Test User',
    'email': 'test@example.com',
    'phone': '0123456789'
}), content_type='application/json')
req1.data = json.loads(req1.body)
identify_customer(req1)

# Init paystack
request = factory.post('/api/checkout/paystack/init/', data=json.dumps({
    'is_guest': False,
    'save_history': True,
    'customer_name': 'Test User',
    'customer_email': 'test@example.com',
    'customer_phone': '0123456789'
}), content_type='application/json')
request.data = json.loads(request.body)
response = checkout_paystack_init(request)
print("Status:", response.status_code)
print("Content:", response.data)
