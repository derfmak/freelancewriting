from django import forms
from decimal import Decimal
from django.utils import timezone
from datetime import timedelta
from .models import PaymentMethod


class DepositForm(forms.Form):
    amount = forms.DecimalField(
        min_value=5,
        max_value=10000,
        widget=forms.NumberInput(attrs={
            'class': 'form-input w-full border border-gray-300 px-4 py-3 focus:border-green-600 focus:ring-1 focus:ring-green-600 outline-none transition-colors',
            'placeholder': 'Enter amount',
            'step': '5',
            'min': '5'
        })
    )
    payment_method = forms.ChoiceField(
        choices=[('stripe', 'Credit/Debit Card'), ('paypal', 'PayPal')],
        widget=forms.RadioSelect(attrs={'class': 'form-radio'})
    )
    payment_method_id = forms.CharField(
        required=False,
        widget=forms.HiddenInput()
    )
    idempotency_key = forms.CharField(
        required=False,
        widget=forms.HiddenInput()
    )

    def clean_amount(self):
        amount = self.cleaned_data['amount']
        if amount < 5:
            raise forms.ValidationError('Minimum deposit is $5.00')
        if amount > 10000:
            raise forms.ValidationError('Maximum deposit is $10,000.00')
        return amount


class WithdrawForm(forms.Form):
    METHOD_CHOICES = [
        ('paypal', 'PayPal'),
        ('card', 'Credit/Debit Card'),
    ]

    amount = forms.DecimalField(
        min_value=10,
        max_value=5000,
        widget=forms.NumberInput(attrs={
            'class': 'form-input w-full border border-gray-300 px-4 py-3 focus:border-green-600 focus:ring-1 focus:ring-green-600 outline-none transition-colors',
            'placeholder': 'Enter amount',
            'step': '10',
            'min': '10'
        })
    )
    method = forms.ChoiceField(
        choices=METHOD_CHOICES,
        widget=forms.Select(attrs={
            'class': 'form-input w-full border border-gray-300 px-4 py-3 focus:border-green-600 focus:ring-1 focus:ring-green-600 outline-none transition-colors'
        })
    )
    paypal_email = forms.EmailField(
        required=False,
        widget=forms.EmailInput(attrs={
            'class': 'form-input w-full border border-gray-300 px-4 py-3 focus:border-green-600 focus:ring-1 focus:ring-green-600 outline-none transition-colors',
            'placeholder': 'your@paypal.com'
        })
    )
    card_method_id = forms.CharField(
        required=False,
        widget=forms.HiddenInput()
    )
    idempotency_key = forms.CharField(
        required=False,
        widget=forms.HiddenInput()
    )

    def clean_amount(self):
        amount = self.cleaned_data['amount']
        if amount < 10:
            raise forms.ValidationError('Minimum withdrawal is $10.00')
        if amount > 5000:
            raise forms.ValidationError('Maximum withdrawal is $5,000.00')
        return amount

    def clean(self):
        cleaned_data = super().clean()
        method = cleaned_data.get('method')
        amount = cleaned_data.get('amount')
        
        if method == 'paypal':
            if not cleaned_data.get('paypal_email'):
                raise forms.ValidationError('PayPal email is required for PayPal withdrawals')
        
        if method == 'card':
            if not cleaned_data.get('card_method_id'):
                raise forms.ValidationError('Please select a card for withdrawal')
        
        return cleaned_data


class AddPaymentMethodForm(forms.Form):
    CARD_TYPES = [
        ('visa', 'Visa'),
        ('mastercard', 'Mastercard'),
        ('amex', 'American Express'),
        ('discover', 'Discover'),
        ('jcb', 'JCB'),
        ('diners', 'Diners Club'),
    ]

    card_number = forms.CharField(
        max_length=19,
        widget=forms.TextInput(attrs={
            'class': 'form-input w-full border border-gray-300 px-4 py-3 focus:border-green-600 focus:ring-1 focus:ring-green-600 outline-none transition-colors',
            'placeholder': '1234 5678 9012 3456',
            'autocomplete': 'cc-number'
        })
    )
    cardholder_name = forms.CharField(
        max_length=255,
        widget=forms.TextInput(attrs={
            'class': 'form-input w-full border border-gray-300 px-4 py-3 focus:border-green-600 focus:ring-1 focus:ring-green-600 outline-none transition-colors',
            'placeholder': 'John Doe',
            'autocomplete': 'cc-name'
        })
    )
    expiry_month = forms.ChoiceField(
        choices=[(str(i), f'{i:02d}') for i in range(1, 13)],
        widget=forms.Select(attrs={
            'class': 'form-input w-full border border-gray-300 px-4 py-3 focus:border-green-600 focus:ring-1 focus:ring-green-600 outline-none transition-colors'
        })
    )
    expiry_year = forms.ChoiceField(
        choices=[(str(i), str(i)) for i in range(2024, 2035)],
        widget=forms.Select(attrs={
            'class': 'form-input w-full border border-gray-300 px-4 py-3 focus:border-green-600 focus:ring-1 focus:ring-green-600 outline-none transition-colors'
        })
    )
    cvv = forms.CharField(
        max_length=4,
        widget=forms.TextInput(attrs={
            'class': 'form-input w-full border border-gray-300 px-4 py-3 focus:border-green-600 focus:ring-1 focus:ring-green-600 outline-none transition-colors',
            'placeholder': '123',
            'autocomplete': 'cc-csc',
            'type': 'password'
        })
    )
    set_default = forms.BooleanField(
        required=False,
        widget=forms.CheckboxInput(attrs={'class': 'form-checkbox'})
    )

    def clean_card_number(self):
        card_number = self.cleaned_data['card_number'].replace(' ', '').replace('-', '')
        
        if not card_number.isdigit():
            raise forms.ValidationError('Card number must contain only digits')
        
        if len(card_number) < 13 or len(card_number) > 19:
            raise forms.ValidationError('Invalid card number length')
        
        if not self.luhn_check(card_number):
            raise forms.ValidationError('Invalid card number')
        
        return card_number

    def clean_cvv(self):
        cvv = self.cleaned_data['cvv']
        if not cvv.isdigit():
            raise forms.ValidationError('CVV must contain only digits')
        if len(cvv) < 3 or len(cvv) > 4:
            raise forms.ValidationError('CVV must be 3 or 4 digits')
        return cvv

    def clean(self):
        cleaned_data = super().clean()
        expiry_month = cleaned_data.get('expiry_month')
        expiry_year = cleaned_data.get('expiry_year')
        
        if expiry_month and expiry_year:
            try:
                month = int(expiry_month)
                year = int(expiry_year)
                now = timezone.now()
                
                if year < now.year or (year == now.year and month < now.month):
                    raise forms.ValidationError('Card has expired')
                
                if year > 2035:
                    raise forms.ValidationError('Invalid expiry year')
                    
            except ValueError:
                raise forms.ValidationError('Invalid expiry date')
        
        return cleaned_data

    @staticmethod
    def luhn_check(card_number):
        """Luhn algorithm for card validation"""
        sum_val = 0
        num_digits = len(card_number)
        parity = num_digits % 2
        
        for i, digit in enumerate(card_number):
            digit_int = int(digit)
            if i % 2 == parity:
                digit_int *= 2
                if digit_int > 9:
                    digit_int -= 9
            sum_val += digit_int
        
        return sum_val % 10 == 0

    def detect_card_brand(self, card_number):
        """Detect card brand from number"""
        patterns = {
            'visa': r'^4[0-9]{12}(?:[0-9]{3})?$',
            'mastercard': r'^5[1-5][0-9]{14}$|^2(?:2[2-9][0-9]{2}|[3-6][0-9]{3}|7[0-1][0-9]{2}|720)[0-9]{12}$',
            'amex': r'^3[47][0-9]{13}$',
            'discover': r'^6(?:011|5[0-9]{2})[0-9]{12}$',
            'jcb': r'^(?:2131|1800|35[0-9]{3})[0-9]{11}$',
            'diners': r'^3(?:0[0-5]|[68][0-9])[0-9]{11}$',
        }
        
        import re
        for brand, pattern in patterns.items():
            if re.match(pattern, card_number):
                return brand
        return 'unknown'


class PayPalPaymentForm(forms.Form):
    paypal_email = forms.EmailField(
        widget=forms.EmailInput(attrs={
            'class': 'form-input w-full border border-gray-300 px-4 py-3 focus:border-green-600 focus:ring-1 focus:ring-green-600 outline-none transition-colors',
            'placeholder': 'your@paypal.com'
        })
    )
    amount = forms.DecimalField(
        min_value=1,
        widget=forms.NumberInput(attrs={
            'class': 'form-input w-full border border-gray-300 px-4 py-3 focus:border-green-600 focus:ring-1 focus:ring-green-600 outline-none transition-colors',
            'placeholder': 'Enter amount',
            'step': '0.01'
        })
    )

    def clean_paypal_email(self):
        email = self.cleaned_data['paypal_email']
        if not email:
            raise forms.ValidationError('PayPal email is required')
        return email


class OrderPaymentForm(forms.Form):
    PAYMENT_METHODS = [
        ('wallet', 'Wallet Balance'),
        ('card', 'Credit/Debit Card'),
        ('paypal', 'PayPal'),
    ]

    payment_method = forms.ChoiceField(
        choices=PAYMENT_METHODS,
        widget=forms.RadioSelect(attrs={'class': 'form-radio'})
    )
    card_method_id = forms.CharField(
        required=False,
        widget=forms.HiddenInput()
    )
    paypal_email = forms.EmailField(
        required=False,
        widget=forms.EmailInput(attrs={
            'class': 'form-input w-full border border-gray-300 px-4 py-3 focus:border-green-600 focus:ring-1 focus:ring-green-600 outline-none transition-colors',
            'placeholder': 'your@paypal.com'
        })
    )
    idempotency_key = forms.CharField(
        required=False,
        widget=forms.HiddenInput()
    )

    def clean(self):
        cleaned_data = super().clean()
        payment_method = cleaned_data.get('payment_method')
        
        if payment_method == 'card' and not cleaned_data.get('card_method_id'):
            raise forms.ValidationError('Please select a card for payment')
        
        if payment_method == 'paypal' and not cleaned_data.get('paypal_email'):
            raise forms.ValidationError('PayPal email is required')
        
        return cleaned_data


class PaymentVerificationForm(forms.Form):
    payment_intent_id = forms.CharField(
        max_length=255,
        widget=forms.HiddenInput()
    )
    order_id = forms.CharField(
        max_length=36,
        widget=forms.HiddenInput()
    )


class RefundForm(forms.Form):
    order_id = forms.CharField(
        max_length=36,
        widget=forms.HiddenInput()
    )
    amount = forms.DecimalField(
        min_value=0.01,
        widget=forms.NumberInput(attrs={
            'class': 'form-input w-full border border-gray-300 px-4 py-3 focus:border-green-600 focus:ring-1 focus:ring-green-600 outline-none transition-colors',
            'placeholder': 'Enter refund amount',
            'step': '0.01'
        })
    )
    reason = forms.CharField(
        widget=forms.Textarea(attrs={
            'class': 'form-input w-full border border-gray-300 px-4 py-3 focus:border-green-600 focus:ring-1 focus:ring-green-600 outline-none transition-colors',
            'rows': 4,
            'placeholder': 'Reason for refund...'
        })
    )
    notify_client = forms.BooleanField(
        required=False,
        initial=True,
        widget=forms.CheckboxInput(attrs={'class': 'form-checkbox'})
    )

    def clean_amount(self):
        amount = self.cleaned_data['amount']
        if amount <= 0:
            raise forms.ValidationError('Amount must be greater than 0')
        return amount


class PaymentMethodForm(forms.ModelForm):
    class Meta:
        model = PaymentMethod
        fields = [
            'cardholder_name',
            'expiry_month',
            'expiry_year',
            'is_default',
        ]
        widgets = {
            'expiry_month': forms.Select(attrs={'class': 'form-input w-full border border-gray-300 px-4 py-3 focus:border-green-600 focus:ring-1 focus:ring-green-600 outline-none transition-colors'}),
            'expiry_year': forms.Select(attrs={'class': 'form-input w-full border border-gray-300 px-4 py-3 focus:border-green-600 focus:ring-1 focus:ring-green-600 outline-none transition-colors'}),
            'cardholder_name': forms.TextInput(attrs={'class': 'form-input w-full border border-gray-300 px-4 py-3 focus:border-green-600 focus:ring-1 focus:ring-green-600 outline-none transition-colors', 'placeholder': 'John Doe'}),
            'is_default': forms.CheckboxInput(attrs={'class': 'form-checkbox'}),
        }