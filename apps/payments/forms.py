from django import forms
from decimal import Decimal
from .models import PaymentMethod


class AddPayPalMethodForm(forms.Form):
    paypal_email = forms.EmailField(
        widget=forms.EmailInput(attrs={
            'class': 'form-input w-full border border-gray-300 px-4 py-3 focus:border-green-600 focus:ring-1 focus:ring-green-600 outline-none transition-colors rounded-lg',
            'placeholder': 'your@paypal.com'
        })
    )
    paypal_account_type = forms.ChoiceField(
        choices=[('personal', 'Personal'), ('business', 'Business')],
        widget=forms.Select(attrs={
            'class': 'form-input w-full border border-gray-300 px-4 py-3 focus:border-green-600 focus:ring-1 focus:ring-green-600 outline-none transition-colors rounded-lg'
        })
    )
    set_default = forms.BooleanField(
        required=False,
        widget=forms.CheckboxInput(attrs={'class': 'form-checkbox h-4 w-4 text-green-600 rounded border-gray-300 focus:ring-green-500'})
    )

    def clean_paypal_email(self):
        email = self.cleaned_data['paypal_email']
        if not email:
            raise forms.ValidationError('PayPal email is required')
        return email


class PayPalDepositForm(forms.Form):
    amount = forms.DecimalField(
        min_value=5,
        max_value=10000,
        widget=forms.NumberInput(attrs={
            'class': 'form-input w-full border border-gray-300 px-4 py-3 focus:border-green-600 focus:ring-1 focus:ring-green-600 outline-none transition-colors rounded-lg',
            'placeholder': 'Enter amount',
            'step': '5',
            'min': '5'
        })
    )

    def clean_amount(self):
        amount = self.cleaned_data['amount']
        if amount < 5:
            raise forms.ValidationError('Minimum deposit is $5.00')
        if amount > 10000:
            raise forms.ValidationError('Maximum deposit is $10,000.00')
        return amount


class PayPalWithdrawForm(forms.Form):
    amount = forms.DecimalField(
        min_value=10,
        max_value=5000,
        widget=forms.NumberInput(attrs={
            'class': 'form-input w-full border border-gray-300 px-4 py-3 focus:border-green-600 focus:ring-1 focus:ring-green-600 outline-none transition-colors rounded-lg',
            'placeholder': 'Enter amount',
            'step': '10',
            'min': '10'
        })
    )
    paypal_email = forms.EmailField(
        widget=forms.EmailInput(attrs={
            'class': 'form-input w-full border border-gray-300 px-4 py-3 focus:border-green-600 focus:ring-1 focus:ring-green-600 outline-none transition-colors rounded-lg',
            'placeholder': 'your@paypal.com'
        })
    )

    def clean_amount(self):
        amount = self.cleaned_data['amount']
        if amount < 10:
            raise forms.ValidationError('Minimum withdrawal is $10.00')
        if amount > 5000:
            raise forms.ValidationError('Maximum withdrawal is $5,000.00')
        return amount

    def clean_paypal_email(self):
        email = self.cleaned_data['paypal_email']
        if not email:
            raise forms.ValidationError('PayPal email is required')
        return email