from django.db import models
from django.contrib.auth.hashers import make_password, check_password


class Category(models.Model):
    category_id = models.AutoField(primary_key=True)
    name = models.CharField(max_length=100, unique=True)
    description = models.TextField(null=True, blank=True)

    def __str__(self):
        return self.name


class Product(models.Model):
    # This must match the class name YOLO outputs exactly (lowercase, e.g. "apple")
    yolo_class_name = models.CharField(max_length=100, unique=True)

    display_name = models.CharField(max_length=100)

    price = models.DecimalField(max_digits=8, decimal_places=2)

    image = models.ImageField(upload_to='product_images/', blank=True, null=True)
    
    category = models.ForeignKey(Category, on_delete=models.SET_NULL, null=True, blank=True)
    stock_quantity = models.IntegerField(default=0)

    def __str__(self):
        return self.display_name


class Cart(models.Model):
    cart_id = models.AutoField(primary_key=True)
    created_at = models.DateTimeField(auto_now_add=True)
    status = models.CharField(max_length=20, default='active')
    
    def __str__(self):
        return f"Cart #{self.cart_id}"


class CartItem(models.Model):
    cart_item_id = models.AutoField(primary_key=True)
    cart = models.ForeignKey(Cart, on_delete=models.CASCADE)
    product = models.ForeignKey(Product, on_delete=models.CASCADE)
    quantity = models.PositiveIntegerField(default=0)
    added_at = models.DateTimeField(auto_now=True)

    def subtotal(self):
        return self.product.price * self.quantity

    def __str__(self):
        return f"{self.product.display_name} x{self.quantity}"


class Customer(models.Model):
    name = models.CharField(max_length=100)
    email = models.EmailField()
    phone = models.CharField(max_length=30)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=['email'], name='unique_customer_email')
        ]

    def __str__(self):
        return f"{self.name} ({self.email})"


class Transaction(models.Model):
    PAYMENT_CHOICES = [('cash', 'Cash'), ('paystack', 'Paystack')]
    STATUS_CHOICES = [('pending', 'Pending'), ('paid', 'Paid'), ('failed', 'Failed')]

    transaction_id = models.AutoField(primary_key=True)
    cart = models.ForeignKey(Cart, on_delete=models.CASCADE, null=True, blank=True)
    reference = models.CharField(max_length=100, unique=True, blank=True, null=True)
    payment_method = models.CharField(max_length=20, choices=PAYMENT_CHOICES)
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='pending')
    total_amount = models.DecimalField(max_digits=10, decimal_places=2)
    items_snapshot = models.JSONField(default=list)
    timestamp = models.DateTimeField(auto_now_add=True)

    customer = models.ForeignKey(
        Customer,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='transactions',
    )

    # Denormalized customer details (kept for receipts / legacy admin views)
    customer_name = models.CharField(max_length=200, blank=True, null=True)
    customer_email = models.EmailField(blank=True, null=True)
    customer_phone = models.CharField(max_length=20, blank=True, null=True)

    def __str__(self):
        return f"Transaction #{self.transaction_id} - {self.payment_method} - {self.status}"


class TransactionItem(models.Model):
    transaction_item_id = models.AutoField(primary_key=True)
    transaction = models.ForeignKey(Transaction, on_delete=models.CASCADE)
    product = models.ForeignKey(Product, on_delete=models.CASCADE)
    quantity = models.IntegerField()
    unit_price = models.DecimalField(max_digits=10, decimal_places=2)
    line_total = models.DecimalField(max_digits=10, decimal_places=2)

    def __str__(self):
        return f"{self.product.display_name} x{self.quantity}"


class DetectionLog(models.Model):
    log_id = models.AutoField(primary_key=True)
    product = models.ForeignKey(Product, on_delete=models.SET_NULL, null=True, blank=True)
    detected_class = models.CharField(max_length=100)  # Changed from detected_label to detected_class
    confidence_score = models.FloatField()
    timestamp = models.DateTimeField(auto_now_add=True)
    was_accepted = models.BooleanField(default=False)

    def __str__(self):
        return f"Detection: {self.detected_class} ({self.confidence_score:.2%})"


class PaymentMethod(models.Model):
    method_id = models.AutoField(primary_key=True)
    name = models.CharField(max_length=50, unique=True)
    is_active = models.BooleanField(default=True)

    def __str__(self):
        return self.name


class Payment(models.Model):
    payment_id = models.AutoField(primary_key=True)
    transaction = models.ForeignKey(Transaction, on_delete=models.CASCADE)
    method = models.ForeignKey(PaymentMethod, on_delete=models.CASCADE)
    amount = models.DecimalField(max_digits=10, decimal_places=2)
    status = models.CharField(max_length=20, default='pending')
    gateway_reference = models.CharField(max_length=100, blank=True, null=True, unique=True)
    timestamp = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"Payment #{self.payment_id} - {self.method.name} - {self.status}"


class Receipt(models.Model):
    receipt_id = models.AutoField(primary_key=True)
    payment = models.OneToOneField(Payment, on_delete=models.CASCADE)
    receipt_number = models.CharField(max_length=50, unique=True)
    issued_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"Receipt #{self.receipt_number}"


class Admin(models.Model):
    admin_id = models.AutoField(primary_key=True)
    username = models.CharField(max_length=50, unique=True)
    password_hash = models.CharField(max_length=255)
    email = models.EmailField(unique=True)
    full_name = models.CharField(max_length=100)
    phone = models.CharField(max_length=20, blank=True, null=True)
    created_at = models.DateTimeField(auto_now_add=True)

    def set_password(self, raw_password):
        self.password_hash = make_password(raw_password)
        return self.password_hash

    def check_password(self, raw_password):
        return check_password(raw_password, self.password_hash)

    def __str__(self):
        return self.username


class EmergencyReport(models.Model):
    CATEGORY_CHOICES = [
        ('payment_failed', 'Transaction did not go through'),
        ('scan_error', 'Item scanned incorrectly'),
        ('system_glitch', 'System is glitching/not responding'),
        ('other', 'Other complaint'),
    ]
    STATUS_CHOICES = [
        ('open', 'Open'),
        ('in_progress', 'In Progress'),
        ('resolved', 'Resolved'),
    ]

    category = models.CharField(max_length=30, choices=CATEGORY_CHOICES)
    details = models.TextField(blank=True)
    transaction_id = models.CharField(max_length=100, blank=True, null=True)
    customer_name = models.CharField(max_length=100, blank=True, null=True)
    customer_email = models.EmailField(blank=True, null=True)
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='open')
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"[{self.get_category_display()}] {self.transaction_id or 'no txn'} - {self.status}"
