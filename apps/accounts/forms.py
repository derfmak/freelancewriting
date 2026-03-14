from django import forms
from django.contrib.auth.forms import UserCreationForm, UserChangeForm, PasswordChangeForm
from django.contrib.auth.password_validation import validate_password
from .models import User

class UserRegistrationForm(forms.ModelForm):
    password = forms.CharField(
        widget=forms.PasswordInput(attrs={'class': 'form-input', 'placeholder': 'Enter password'}),
        validators=[validate_password]
    )
    password_confirm = forms.CharField(
        widget=forms.PasswordInput(attrs={'class': 'form-input', 'placeholder': 'Confirm password'})
    )
    phone = forms.CharField(
        required=False,
        widget=forms.TextInput(attrs={'class': 'form-input', 'placeholder': '+1234567890'})
    )
    institution = forms.CharField(
        required=False,
        widget=forms.TextInput(attrs={'class': 'form-input', 'placeholder': 'Your school or university'})
    )

    class Meta:
        model = User
        fields = ['email', 'full_name', 'phone', 'institution']
        widgets = {
            'email': forms.EmailInput(attrs={'class': 'form-input', 'placeholder': 'your@email.com'}),
            'full_name': forms.TextInput(attrs={'class': 'form-input', 'placeholder': 'John Doe'}),
        }

    def clean(self):
        cleaned_data = super().clean()
        password = cleaned_data.get('password')
        password_confirm = cleaned_data.get('password_confirm')

        if password and password_confirm and password != password_confirm:
            raise forms.ValidationError({'password_confirm': 'Passwords do not match'})

        return cleaned_data

    def save(self, commit=True):
        user = super().save(commit=False)
        user.set_password(self.cleaned_data['password'])
        user.username = user.email
        if commit:
            user.save()
        return user

class UserLoginForm(forms.Form):
    email = forms.EmailField(
        widget=forms.EmailInput(attrs={'class': 'form-input', 'placeholder': 'your@email.com'})
    )
    password = forms.CharField(
        widget=forms.PasswordInput(attrs={'class': 'form-input', 'placeholder': 'Enter password'})
    )
    remember = forms.BooleanField(required=False, initial=False)

class UserProfileForm(forms.ModelForm):
    class Meta:
        model = User
        fields = ['full_name', 'display_name', 'phone', 'institution', 'course', 'year_of_study']
        widgets = {
            'full_name': forms.TextInput(attrs={'class': 'form-input'}),
            'display_name': forms.TextInput(attrs={'class': 'form-input'}),
            'phone': forms.TextInput(attrs={'class': 'form-input', 'placeholder': '+1234567890'}),
            'institution': forms.TextInput(attrs={'class': 'form-input'}),
            'course': forms.TextInput(attrs={'class': 'form-input'}),
            'year_of_study': forms.Select(attrs={'class': 'form-input'}, choices=[
                ('', 'Select year'),
                ('1st', '1st Year'),
                ('2nd', '2nd Year'),
                ('3rd', '3rd Year'),
                ('4th', '4th Year'),
                ('5th', '5th Year+'),
                ('graduate', 'Graduate'),
            ]),
        }

class ForgotPasswordForm(forms.Form):
    email = forms.EmailField(
        widget=forms.EmailInput(attrs={'class': 'form-input', 'placeholder': 'your@email.com'})
    )

class ResetPasswordForm(forms.Form):
    password = forms.CharField(
        widget=forms.PasswordInput(attrs={'class': 'form-input', 'placeholder': 'New password'}),
        validators=[validate_password]
    )
    password_confirm = forms.CharField(
        widget=forms.PasswordInput(attrs={'class': 'form-input', 'placeholder': 'Confirm new password'})
    )

    def clean(self):
        cleaned_data = super().clean()
        password = cleaned_data.get('password')
        password_confirm = cleaned_data.get('password_confirm')

        if password and password_confirm and password != password_confirm:
            raise forms.ValidationError('Passwords do not match')

        return cleaned_data

class ChangePasswordForm(PasswordChangeForm):
    old_password = forms.CharField(
        widget=forms.PasswordInput(attrs={'class': 'form-input', 'placeholder': 'Current password'})
    )
    new_password1 = forms.CharField(
        widget=forms.PasswordInput(attrs={'class': 'form-input', 'placeholder': 'New password'}),
        validators=[validate_password]
    )
    new_password2 = forms.CharField(
        widget=forms.PasswordInput(attrs={'class': 'form-input', 'placeholder': 'Confirm new password'})
    )

    class Meta:
        model = User
        fields = ['old_password', 'new_password1', 'new_password2']