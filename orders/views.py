from django.shortcuts import render, redirect, get_object_or_404
from django.http import HttpResponse, JsonResponse
from carts.models import CartItem, Cart
from .forms import OrderForm
import datetime
from .models import Order, Payment, OrderProduct
import json
from store.models import Product
from django.core.mail import EmailMessage
from django.template.loader import render_to_string
from xhtml2pdf import pisa
from django.template.loader import get_template


def payments(request):
    body = json.loads(request.body)
    order = Order.objects.get(user=request.user, is_ordered=False, order_number=body['orderID'])

    # Store transaction details inside Payment model
    payment = Payment(
        user = request.user,
        payment_id = body['transID'],
        payment_method = body['payment_method'],
        amount_paid = order.order_total,
        status = body['status'],
    )
    payment.save()

    order.payment = payment
    order.is_ordered = True
    order.save()

    # Move the cart items to Order Product table
    cart_items = CartItem.objects.filter(user=request.user)

    for item in cart_items:
        orderproduct = OrderProduct()
        orderproduct.order_id = order.id
        orderproduct.payment = payment
        orderproduct.user_id = request.user.id
        orderproduct.product_id = item.product_id
        orderproduct.quantity = item.quantity
        orderproduct.product_price = item.product.price
        orderproduct.ordered = True
        orderproduct.save()

        cart_item = CartItem.objects.get(id=item.id)
        product_variation = cart_item.variations.all()
        orderproduct = OrderProduct.objects.get(id=orderproduct.id)
        orderproduct.variations.set(product_variation)
        orderproduct.save()


        # Reduce the quantity of the sold products
        product = Product.objects.get(id=item.product_id)
        product.stock -= item.quantity
        product.save()

    # Clear cart
    CartItem.objects.filter(user=request.user).delete()

    # Send order recieved email to customer
    mail_subject = 'Gracias por tu orden!'
    message = render_to_string('orders/order_recieved_email.html', {
        'user': request.user,
        'order': order,
    })
    to_email = request.user.email
    send_email = EmailMessage(mail_subject, message, to=[to_email])
    send_email.send()

    # Send order number and transaction id back to sendData method via JsonResponse
    data = {
        'order_number': order.order_number,
        'transID': payment.payment_id,
    }
    return JsonResponse(data)

def place_order(request, total=0, quantity=0):
    current_user = request.user

    # If the cart count is less than or equal to 0, then redirect back to shop
    cart_items = CartItem.objects.filter(user=current_user, is_active=True)
    cart_count = cart_items.count()
    if cart_count <= 0:
        return redirect('store')

    grand_total = 0
    tax = 0
    for cart_item in cart_items:
        total += (cart_item.product.price * cart_item.quantity)
        quantity += cart_item.quantity

    if request.method == 'POST':
        form = OrderForm(request.POST)
        if form.is_valid():
            try:
                # Store all the billing information inside Order table
                data = Order()
                data.user = current_user
                data.first_name = form.cleaned_data['first_name']
                data.last_name = form.cleaned_data['last_name']
                data.phone = form.cleaned_data['phone']
                data.email = form.cleaned_data['email']
                data.address_line_1 = form.cleaned_data['address_line_1']
                data.address_line_2 = form.cleaned_data['address_line_2']
                data.postalcode = form.cleaned_data['postalcode']
                data.state = form.cleaned_data['state']
                data.city = form.cleaned_data['city']
                data.order_note = form.cleaned_data['order_note']

                # Calculate tax based on state
                if data.state.lower() == 'bogota':
                    tax = 7000
                else:
                    tax = 15000

                grand_total = total + tax

                data.order_total = grand_total
                data.tax = tax
                data.ip = request.META.get('REMOTE_ADDR')
                data.save()

                # Generate order number
                yr = int(datetime.date.today().strftime('%Y'))
                dt = int(datetime.date.today().strftime('%d'))
                mt = int(datetime.date.today().strftime('%m'))
                d = datetime.date(yr, mt, dt)
                current_date = d.strftime("%Y%m%d")  # 20210305
                order_number = current_date + str(data.id)
                data.order_number = order_number
                data.save()

                # Move the cart items to OrderProduct table
                cart_items = CartItem.objects.filter(user=current_user)
                for item in cart_items:
                    order_product = OrderProduct()
                    order_product.order = data
                    order_product.payment = data.payment
                    order_product.user = current_user
                    order_product.product = item.product
                    order_product.quantity = item.quantity
                    order_product.product_price = item.product.price
                    order_product.ordered = True
                    order_product.save()

                    # Many-to-Many fields
                    cart_item_variations = item.variations.all()
                    order_product.variations.set(cart_item_variations)
                    order_product.save()

                # Clear the cart
                CartItem.objects.filter(user=current_user).delete()

                context = {
                    'order': data,
                    'cart_items': cart_items,
                    'total': total,
                    'tax': tax,
                    'grand_total': grand_total,
                }
                return render(request, 'orders/payments.html', context)
            except Exception as e:
                # If there's an error, retry with the received POST data
                print(f"Error processing order: {e}")
                # Here you can choose to log the error, send a notification, etc.
                received_data = request.POST
                return render(request, 'orders/payments.html', {'received_data': received_data})
        else:
            # Handle the case when the form is not valid
            return redirect('checkout')
    else:
        return redirect('checkout')

def order_complete(request):
    order_number = request.GET.get('order_number')
    transID = request.GET.get('payment_id')

    try:
        order = Order.objects.get(order_number=order_number, is_ordered=True)
        ordered_products = OrderProduct.objects.filter(order_id=order.id)

        subtotal = 0
        for i in ordered_products:
            subtotal += i.product_price * i.quantity

        payment = Payment.objects.get(payment_id=transID)

        context = {
            'order': order,
            'ordered_products': ordered_products,
            'order_number': order.order_number,
            'transID': payment.payment_id,
            'payment': payment,
            'subtotal': subtotal,
        }
        return render(request, 'orders/order_complete.html', context)
    except (Payment.DoesNotExist, Order.DoesNotExist):
        return redirect('home')

def generate_invoice(request, order_id):
    order = get_object_or_404(Order, id=order_id)
    order_products = OrderProduct.objects.filter(order=order)

    template_path = 'orders/invoice.html'
    context = {
        'order': order,
        'order_products': order_products,
    }

    # Create a Django response object, and specify content_type as pdf
    response = HttpResponse(content_type='application/pdf')
    response['Content-Disposition'] = f'attachment; filename="invoice_{order.order_number}.pdf"'

    # Find the template and render it.
    template = get_template(template_path)
    html = template.render(context)

    # Create a pdf
    pisa_status = pisa.CreatePDF(
        html, dest=response
    )

    # if error then show some funy view
    if pisa_status.err:
        return HttpResponse('We had some errors <pre>' + html + '</pre>')
    return response