from django import forms
from decimal import Decimal
from .models import PaymentMethod

class DepositForm(forms.Form):
    amount = forms.DecimalField(
        min_value=5,
        max_value=10000,
        widget=forms.NumberInput(attrs={'class': 'form-input', 'placeholder': 'Enter amount', 'step': '5'})
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
        ('bank', 'Bank Transfer'),
        ('card', 'Credit/Debit Card'),
    ]

    amount = forms.DecimalField(
        min_value=10,
        max_value=5000,
        widget=forms.NumberInput(attrs={'class': 'form-input', 'placeholder': 'Enter amount', 'step': '10'})
    )
    method = forms.ChoiceField(
        choices=METHOD_CHOICES,
        widget=forms.Select(attrs={'class': 'form-input'})
    )
    paypal_email = forms.EmailField(
        required=False,
        widget=forms.EmailInput(attrs={'class': 'form-input', 'placeholder': 'your@paypal.com'})
    )
    account_holder = forms.CharField(
        required=False,
        widget=forms.TextInput(attrs={'class': 'form-input', 'placeholder': 'Account holder name'})
    )
    routing_number = forms.CharField(
        required=False,
        widget=forms.TextInput(attrs={'class': 'form-input', 'placeholder': 'Routing number'})
    )
    account_number = forms.CharField(
        required=False,
        widget=forms.TextInput(attrs={'class': 'form-input', 'placeholder': 'Account number'})
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
        
        if method == 'paypal' and not cleaned_data.get('paypal_email'):
            raise forms.ValidationError('PayPal email is required for PayPal withdrawals')
        
        if method == 'bank':
            if not cleaned_data.get('account_holder'):
                raise forms.ValidationError('Account holder name is required for bank transfers')
            if not cleaned_data.get('routing_number'):
                raise forms.ValidationError('Routing number is required for bank transfers')
            if not cleaned_data.get('account_number'):
                raise forms.ValidationError('Account number is required for bank transfers')
        
        if method == 'card' and not cleaned_data.get('card_method_id'):
            raise forms.ValidationError('Payment method is required for card withdrawals')
        
        return cleaned_data

class AddPaymentMethodForm(forms.Form):
    provider_method_id = forms.CharField(widget=forms.HiddenInput())
    last_four = forms.CharField(min_length=4, max_length=4, widget=forms.HiddenInput())
    card_brand = forms.ChoiceField(
        choices=PaymentMethod.CARD_BRANDS,
        widget=forms.HiddenInput()
    )
    cardholder_name = forms.CharField(max_length=255, widget=forms.HiddenInput())
    expiry_month = forms.IntegerField(min_value=1, max_value=12, widget=forms.HiddenInput())
    expiry_year = forms.IntegerField(min_value=2020, max_value=2100, widget=forms.HiddenInput())

class ConfirmDepositForm(forms.Form):
    payment_intent_id = forms.CharField(widget=forms.HiddenInput())

class TransferForm(forms.Form):
    recipient_email = forms.EmailField(
        widget=forms.EmailInput(attrs={'class': 'form-input', 'placeholder': 'recipient@email.com'})
    )
    amount = forms.DecimalField(
        min_value=1,
        max_value=10000,
        widget=forms.NumberInput(attrs={'class': 'form-input', 'placeholder': 'Enter amount', 'step': '1'})
    )
    description = forms.CharField(
        required=False,
        widget=forms.TextInput(attrs={'class': 'form-input', 'placeholder': 'Optional description'})
    )
    idempotency_key = forms.CharField(
        required=False,
        widget=forms.HiddenInput()
    )

    def clean_amount(self):
        amount = self.cleaned_data['amount']
        if amount < 1:
            raise forms.ValidationError('Minimum transfer amount is $1.00')
        if amount > 10000:
            raise forms.ValidationError('Maximum transfer amount is $10,000.00')
        return amount