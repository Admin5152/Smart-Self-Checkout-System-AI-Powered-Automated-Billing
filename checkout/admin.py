from django.contrib import admin
from .models import (
    Product, CartItem, Cart, Transaction, TransactionItem, 
    Customer, EmergencyReport, DetectionLog, PaymentMethod, 
    Payment, Receipt, Admin, Category
)


@admin.register(Category)
class CategoryAdmin(admin.ModelAdmin):
    list_display = ['name', 'description']
    search_fields = ['name']


@admin.register(Product)
class ProductAdmin(admin.ModelAdmin):
    list_display = ['display_name', 'yolo_class_name', 'category', 'price', 'stock_quantity', 'image_preview']
    list_filter = ['category', 'price']
    search_fields = ['display_name', 'yolo_class_name']
    fieldsets = (
        ('Product Information', {
            'fields': ('display_name', 'yolo_class_name', 'category', 'price', 'stock_quantity', 'image')
        }),
    )

    def image_preview(self, obj):
        if obj.image:
            return f'<img src="{obj.image.url}" width="50" height="50" style="object-fit: cover; border-radius: 4px;">'
        return 'No image'
    image_preview.short_description = 'Image'
    image_preview.allow_tags = True


@admin.register(Cart)
class CartAdmin(admin.ModelAdmin):
    list_display = ['cart_id', 'created_at', 'status']
    list_filter = ['status', 'created_at']


@admin.register(CartItem)
class CartItemAdmin(admin.ModelAdmin):
    list_display = ['cart_item_id', 'cart', 'product', 'quantity', 'subtotal']
    list_filter = ['cart']


class TransactionInline(admin.TabularInline):
    model = Transaction
    extra = 0
    fields = ['transaction_id', 'payment_method', 'status', 'total_amount', 'timestamp']
    readonly_fields = ['transaction_id', 'payment_method', 'status', 'total_amount', 'timestamp']
    show_change_link = True
    can_delete = False

    def get_queryset(self, request):
        return super().get_queryset(request).filter(status='paid')


@admin.register(Customer)
class CustomerAdmin(admin.ModelAdmin):
    list_display = ['name', 'email', 'phone', 'created_at', 'transaction_count']
    search_fields = ['name', 'email', 'phone']
    list_filter = ['created_at']
    readonly_fields = ['created_at']
    inlines = [TransactionInline]

    def transaction_count(self, obj):
        return obj.transactions.count()
    transaction_count.short_description = 'Transactions'

    def get_queryset(self, request):
        return super().get_queryset(request).prefetch_related('transactions')


@admin.register(Transaction)
class TransactionAdmin(admin.ModelAdmin):
    list_display = ['transaction_id', 'customer', 'customer_name', 'customer_email', 'payment_method', 'status', 'total_amount', 'timestamp']
    list_filter = ['status', 'payment_method', 'timestamp', 'customer']
    search_fields = ['customer_name', 'customer_email', 'customer_phone', 'reference', 'customer__name', 'customer__email']
    readonly_fields = ['timestamp']
    autocomplete_fields = ['customer']
    fieldsets = (
        ('Customer Information', {
            'fields': ('customer', 'customer_name', 'customer_email', 'customer_phone')
        }),
        ('Transaction Details', {
            'fields': ('payment_method', 'status', 'total_amount', 'reference', 'cart')
        }),
        ('Timestamps', {
            'fields': ('timestamp',)
        }),
    )


@admin.register(TransactionItem)
class TransactionItemAdmin(admin.ModelAdmin):
    list_display = ['transaction_item_id', 'transaction', 'product', 'quantity', 'unit_price', 'line_total']
    list_filter = ['transaction']


@admin.register(DetectionLog)
class DetectionLogAdmin(admin.ModelAdmin):
    list_display = ['log_id', 'detected_class', 'confidence_score', 'was_accepted', 'timestamp']
    list_filter = ['was_accepted', 'timestamp']
    search_fields = ['detected_class']


@admin.register(PaymentMethod)
class PaymentMethodAdmin(admin.ModelAdmin):
    list_display = ['method_id', 'name', 'is_active']


@admin.register(Payment)
class PaymentAdmin(admin.ModelAdmin):
    list_display = ['payment_id', 'transaction', 'method', 'amount', 'status', 'gateway_reference', 'timestamp']
    list_filter = ['status', 'method', 'timestamp']


@admin.register(Receipt)
class ReceiptAdmin(admin.ModelAdmin):
    list_display = ['receipt_id', 'receipt_number', 'payment', 'issued_at']
    list_filter = ['issued_at']
    readonly_fields = ['receipt_id']


@admin.register(Admin)
class AdminAdmin(admin.ModelAdmin):
    list_display = ['admin_id', 'username', 'email', 'full_name', 'created_at']
    search_fields = ['username', 'email', 'full_name']
    readonly_fields = ['created_at', 'password_hash']


@admin.register(EmergencyReport)
class EmergencyReportAdmin(admin.ModelAdmin):
    list_display = ['id', 'category', 'transaction_id', 'customer_name', 'customer_email', 'status', 'created_at']
    list_filter = ['status', 'category', 'created_at']
    search_fields = ['transaction_id', 'customer_name', 'customer_email', 'details']
    list_editable = ['status']
    readonly_fields = ['created_at']
    ordering = ['-created_at']
