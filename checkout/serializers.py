from rest_framework import serializers
from .models import Product, CartItem


class ProductSerializer(serializers.ModelSerializer):
    id = serializers.IntegerField(read_only=True)  # Add id field for compatibility
    image_url = serializers.SerializerMethodField()

    class Meta:
        model = Product
        fields = ['id', 'display_name', 'price', 'yolo_class_name', 'image', 'image_url']

    def get_image_url(self, obj):
        if obj.image:
            return obj.image.url
        return None


class CartItemSerializer(serializers.ModelSerializer):
    id = serializers.IntegerField(source='cart_item_id', read_only=True)  # Add id field for compatibility
    product_id = serializers.IntegerField(source='product.id', read_only=True)
    product_name = serializers.CharField(source='product.display_name', read_only=True)
    price = serializers.DecimalField(source='product.price', max_digits=8, decimal_places=2, read_only=True)
    subtotal = serializers.SerializerMethodField()

    class Meta:
        model = CartItem
        fields = ['id', 'cart_item_id', 'product_id', 'product_name', 'price', 'quantity', 'subtotal']

    def get_subtotal(self, obj):
        return obj.subtotal()