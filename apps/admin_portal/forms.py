from django import forms
from apps.accounts.models import User
from apps.orders.models import Order
from .models import Announcement, SystemSetting, SiteContent

class UserAdminForm(forms.ModelForm):
    class Meta:
        model = User
        fields = ['email', 'full_name', 'role', 'is_active', 'is_suspended', 
                  'suspension_reason', 'suspended_until', 'email_verified', 'phone_verified']
        widgets = {
            'suspension_reason': forms.Textarea(attrs={'class': 'form-input', 'rows': 3}),
            'suspended_until': forms.DateTimeInput(attrs={'class': 'form-input', 'type': 'datetime-local'}),
        }

class OrderAdminForm(forms.ModelForm):
    class Meta:
        model = Order
        fields = ['status', 'progress_percentage', 'rating', 'feedback']
        widgets = {
            'feedback': forms.Textarea(attrs={'class': 'form-input', 'rows': 3}),
            'progress_percentage': forms.NumberInput(attrs={'class': 'form-input', 'min': 0, 'max': 100}),
        }

class RefundActionForm(forms.Form):
    reason = forms.CharField(
        required=True,
        widget=forms.Textarea(attrs={'class': 'form-input', 'rows': 3, 'placeholder': 'Reason for decision...'})
    )
    notify_student = forms.BooleanField(required=False, initial=True)

class AnnouncementForm(forms.ModelForm):
    class Meta:
        model = Announcement
        fields = ['title', 'content', 'priority', 'is_active', 'starts_at', 'expires_at']
        widgets = {
            'title': forms.TextInput(attrs={'class': 'form-input'}),
            'content': forms.Textarea(attrs={'class': 'form-input', 'rows': 6}),
            'priority': forms.Select(attrs={'class': 'form-input'}),
            'starts_at': forms.DateTimeInput(attrs={'class': 'form-input', 'type': 'datetime-local'}),
            'expires_at': forms.DateTimeInput(attrs={'class': 'form-input', 'type': 'datetime-local', 'required': False}),
        }

    target_audience = forms.MultipleChoiceField(
        choices=[('all', 'All Users'), ('students', 'Students Only'), ('admins', 'Admins Only')],
        widget=forms.CheckboxSelectMultiple,
        required=False
    )
    send_notification = forms.BooleanField(required=False, initial=False)

class SystemSettingForm(forms.ModelForm):
    class Meta:
        model = SystemSetting
        fields = ['key', 'value', 'type', 'description', 'is_public']
        widgets = {
            'key': forms.TextInput(attrs={'class': 'form-input'}),
            'value': forms.Textarea(attrs={'class': 'form-input', 'rows': 3}),
            'type': forms.Select(attrs={'class': 'form-input'}),
            'description': forms.Textarea(attrs={'class': 'form-input', 'rows': 2}),
        }

class SiteContentForm(forms.ModelForm):
    class Meta:
        model = SiteContent
        fields = ['title', 'content', 'meta_data', 'is_active']
        widgets = {
            'title': forms.TextInput(attrs={'class': 'form-input'}),
            'content': forms.Textarea(attrs={'class': 'form-input', 'rows': 10}),
            'meta_data': forms.Textarea(attrs={'class': 'form-input', 'rows': 3}),
        }