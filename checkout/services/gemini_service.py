import os
import google.generativeai as genai
from django.conf import settings
from checkout.models import Product, Cart

# Initialize Gemini with the API key from settings/environment
GEMINI_API_KEY = os.environ.get('GEMINI_API_KEY')
GEMINI_MODEL = os.environ.get('GEMINI_MODEL', 'gemini-1.5-flash')

if GEMINI_API_KEY:
    genai.configure(api_key=GEMINI_API_KEY)

SYSTEM_PROMPT = """
You are Scan & Go AI Assistant, the official customer support assistant for the Scan & Go self-checkout system.

Your responsibility is to help customers understand the Scan & Go system, its checkout process, products, cart, payment process, receipts, and assistance features.

You must answer using the information supplied by the Scan & Go application. 
Never invent product names, prices, stock quantities, payment results, employee information, or system capabilities.
If you do not have enough information to answer a question, clearly say that you do not have that information.
For questions involving current product prices, availability, categories, or other store data, rely on information retrieved from the Scan & Go database rather than guessing.

You can explain how the Scan & Go system works: The system uses camera-based AI object detection to identify retail products and retrieve their information from the product database. Customers can view detected products, manage their cart, checkout, make electronic payments, and receive digital receipts.

If a customer reports a problem that requires physical intervention, explain the problem-solving steps if possible and offer the customer the option to request assistance from a store employee by clicking the "Request Assistance" button.

You are a customer support assistant, not an administrator. Never expose private employee information, administrator credentials, API keys, database credentials, or internal security information.
Never claim that a payment succeeded unless the application provides confirmed payment status.
Never claim that a product is in stock unless the database confirms it.
Be friendly, concise, and easy for ordinary retail customers to understand.
When a customer appears to need physical help, recommend the Request Assistance feature.
"""

def build_context(session_id=None):
    context_lines = []
    
    # Add Product Info
    products = Product.objects.all()
    context_lines.append("AVAILABLE STORE PRODUCTS:")
    for p in products:
        status = "Available" if getattr(p, 'stock_quantity', 1) > 0 else "Out of Stock" # Fallback if stock doesn't exist
        # If there's an is_active field
        if hasattr(p, 'is_active') and not p.is_active:
            status = "Inactive"
        
        category = p.category.name if hasattr(p, 'category') and p.category else "Uncategorized"
        context_lines.append(f"- {p.name} | Category: {category} | Price: GH₵{p.price} | Status: {status}")
        
    context_lines.append("")
    
    # Add Cart Info if session exists
    if session_id:
        try:
            cart = Cart.objects.get(session_id=session_id)
            items = cart.items.all()
            if items.exists():
                context_lines.append("CUSTOMER'S CURRENT CART:")
                for item in items:
                    context_lines.append(f"- {item.product.name} (Qty: {item.quantity})")
                context_lines.append(f"Cart Total: GH₵{cart.total_price()}")
            else:
                context_lines.append("CUSTOMER'S CURRENT CART: Empty")
        except Cart.DoesNotExist:
            context_lines.append("CUSTOMER'S CURRENT CART: Empty")
            
    return "\n".join(context_lines)

def get_chatbot_response(message, session_id, history=None):
    """
    history should be a list of dicts with 'role' (user/model) and 'parts' (list of strings).
    """
    if not GEMINI_API_KEY:
        return "Sorry, the AI assistant is temporarily unavailable (API Key not configured)."
    
    try:
        context_str = build_context(session_id)
        
        full_system_prompt = f"{SYSTEM_PROMPT}\n\n--- CURRENT SYSTEM DATA ---\n{context_str}"
        
        model = genai.GenerativeModel(
            model_name=GEMINI_MODEL,
            system_instruction=full_system_prompt
        )
        
        chat = model.start_chat(history=history or [])
        response = chat.send_message(message)
        
        return response.text
        
    except Exception as e:
        print(f"Gemini API Error: {str(e)}")
        return "Sorry, the AI assistant is temporarily unavailable. You can still request assistance from an employee."
