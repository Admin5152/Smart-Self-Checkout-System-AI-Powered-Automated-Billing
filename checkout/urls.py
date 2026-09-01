from django.urls import path
from . import views

urlpatterns = [
    path('', views.checkout_page, name='checkout_page'),
    path('detect/', views.detect_object, name='detect_object'),
    path('cart/', views.get_cart, name='get_cart'),
    path('cart/adjust/', views.adjust_cart, name='adjust_cart'),
    path('clear/', views.clear_cart, name='clear_cart'),
    path('products/', views.get_products, name='get_products'),
    path('last-detection/', views.get_last_detection, name='get_last_detection'),
    path('camera/stream/', views.camera_stream_proxy, name='camera_stream_proxy'),
    path('customer/identify/', views.identify_customer, name='identify_customer'),
    path('checkout/cash/', views.checkout_cash, name='checkout_cash'),
    path('checkout/paystack/init/', views.checkout_paystack_init, name='checkout_paystack_init'),
    path('checkout/paystack/verify/', views.checkout_paystack_verify, name='checkout_paystack_verify'),
    path('checkout/paystack/webhook/', views.paystack_webhook, name='paystack_webhook'),
    path('detection/pause/', views.pause_detection, name='pause_detection'),
    path('detection/resume/', views.resume_detection, name='resume_detection'),
    path('emergency/report/', views.report_emergency, name='report_emergency'),
    
    # Admin URLs
    path('admin/login/', views.admin_login, name='admin_login'),
    path('admin/logout/', views.admin_logout, name='admin_logout'),
    path('admin/dashboard/', views.admin_dashboard, name='admin_dashboard'),
    path('admin/products/', views.admin_products, name='admin_products'),
    path('admin/customers/', views.admin_customers, name='admin_customers'),
    path('admin/transactions/', views.admin_transactions, name='admin_transactions'),
    path('admin/detection-logs/', views.admin_detection_logs, name='admin_detection_logs'),
    path('admin/reports/', views.admin_reports, name='admin_reports'),
]