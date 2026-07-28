from django import forms
from django.contrib.auth.forms import PasswordChangeForm
from django.contrib.auth.password_validation import validate_password
from django.core.validators import RegexValidator
from django.core.exceptions import ValidationError
from django_recaptcha.fields import ReCaptchaField
from django_recaptcha.widgets import ReCaptchaV2Checkbox
from .models import User


class UserRegistrationForm(forms.ModelForm):
    email = forms.EmailField(
        widget=forms.EmailInput(attrs={
            'class': 'form-input w-full px-4 py-3 border border-gray-300 rounded-lg focus:border-green-600 focus:ring-1 focus:ring-green-600 outline-none transition-colors',
            'placeholder': 'you@example.com',
            'autocomplete': 'email',
            'spellcheck': 'false'
        }),
        error_messages={
            'required': 'Email is required',
            'invalid': 'Please enter a valid email address'
        }
    )
    
    full_name = forms.CharField(
        widget=forms.TextInput(attrs={
            'class': 'form-input w-full px-4 py-3 border border-gray-300 rounded-lg focus:border-green-600 focus:ring-1 focus:ring-green-600 outline-none transition-colors',
            'placeholder': 'John Doe',
            'autocomplete': 'name',
            'spellcheck': 'false'
        }),
        error_messages={
            'required': 'Full name is required'
        }
    )
    
    password = forms.CharField(
        widget=forms.PasswordInput(attrs={
            'class': 'form-input w-full px-4 py-3 border border-gray-300 rounded-lg focus:border-green-600 focus:ring-1 focus:ring-green-600 outline-none transition-colors',
            'placeholder': 'Create a strong password',
            'autocomplete': 'new-password'
        }),
        validators=[validate_password],
        error_messages={
            'required': 'Password is required'
        }
    )
    
    password_confirm = forms.CharField(
        widget=forms.PasswordInput(attrs={
            'class': 'form-input w-full px-4 py-3 border border-gray-300 rounded-lg focus:border-green-600 focus:ring-1 focus:ring-green-600 outline-none transition-colors',
            'placeholder': 'Confirm your password',
            'autocomplete': 'new-password'
        }),
        error_messages={
            'required': 'Please confirm your password'
        }
    )
    
    phone = forms.CharField(
        required=False,
        widget=forms.TextInput(attrs={
            'class': 'form-input w-full px-4 py-3 border border-gray-300 rounded-lg focus:border-green-600 focus:ring-1 focus:ring-green-600 outline-none transition-colors',
            'placeholder': '+254 700 000 000',
            'autocomplete': 'tel',
            'spellcheck': 'false'
        }),
        validators=[RegexValidator(
            regex=r'^\+?1?\d{9,15}$',
            message='Enter a valid phone number (e.g., +254700000000)'
        )]
    )
    
    institution = forms.CharField(
        required=False,
        widget=forms.TextInput(attrs={
            'class': 'form-input w-full px-4 py-3 border border-gray-300 rounded-lg focus:border-green-600 focus:ring-1 focus:ring-green-600 outline-none transition-colors',
            'placeholder': 'Your school or university',
            'spellcheck': 'false'
        })
    )
    
    terms = forms.BooleanField(
        required=True,
        error_messages={
            'required': 'You must agree to the terms and conditions'
        }
    )
    
    captcha = ReCaptchaField(
        widget=ReCaptchaV2Checkbox(attrs={
            'data-theme': 'light',
            'data-size': 'normal'
        })
    )

    class Meta:
        model = User
        fields = ['email', 'full_name', 'phone', 'institution']

    def clean_email(self):
        email = self.cleaned_data.get('email')
        if email:
            email = email.lower().strip()
            if User.objects.filter(email=email).exists():
                raise ValidationError('An account with this email already exists')
        return email

    def clean_full_name(self):
        full_name = self.cleaned_data.get('full_name')
        if full_name:
            full_name = full_name.strip()
            if len(full_name) < 2:
                raise ValidationError('Full name must be at least 2 characters')
        return full_name

    def clean(self):
        cleaned_data = super().clean()
        password = cleaned_data.get('password')
        password_confirm = cleaned_data.get('password_confirm')

        if password and password_confirm:
            if password != password_confirm:
                self.add_error('password_confirm', 'Passwords do not match')

        return cleaned_data

    def save(self, commit=True):
        user = super().save(commit=False)
        user.set_password(self.cleaned_data['password'])
        user.email = self.cleaned_data['email'].lower().strip()
        user.username = user.email
        user.role = 'client'
        if commit:
            user.save()
        return user


class UserLoginForm(forms.Form):
    email = forms.EmailField(
        widget=forms.EmailInput(attrs={
            'class': 'form-input w-full px-4 py-3 border border-gray-300 rounded-lg focus:border-green-600 focus:ring-1 focus:ring-green-600 outline-none transition-colors',
            'placeholder': 'you@example.com',
            'autocomplete': 'email',
            'spellcheck': 'false'
        }),
        error_messages={
            'required': 'Email is required',
            'invalid': 'Please enter a valid email address'
        }
    )
    
    password = forms.CharField(
        widget=forms.PasswordInput(attrs={
            'class': 'form-input w-full px-4 py-3 border border-gray-300 rounded-lg focus:border-green-600 focus:ring-1 focus:ring-green-600 outline-none transition-colors',
            'placeholder': 'Enter your password',
            'autocomplete': 'current-password'
        }),
        error_messages={
            'required': 'Password is required'
        }
    )
    
    remember = forms.BooleanField(
        required=False,
        initial=False,
        widget=forms.CheckboxInput(attrs={
            'class': 'form-checkbox h-4 w-4 text-green-600 rounded border-gray-300 focus:ring-green-500'
        })
    )
    
    captcha = ReCaptchaField(
        required=False,
        widget=ReCaptchaV2Checkbox(attrs={
            'data-theme': 'light',
            'data-size': 'normal'
        })
    )

    def clean_email(self):
        email = self.cleaned_data.get('email')
        if email:
            email = email.lower().strip()
        return email


class UserProfileForm(forms.ModelForm):
    full_name = forms.CharField(
        widget=forms.TextInput(attrs={
            'class': 'form-input w-full px-4 py-3 border border-gray-300 rounded-lg focus:border-green-600 focus:ring-1 focus:ring-green-600 outline-none transition-colors',
            'placeholder': 'John Doe',
            'spellcheck': 'false'
        }),
        error_messages={
            'required': 'Full name is required'
        }
    )
    
    phone = forms.CharField(
        required=False,
        widget=forms.TextInput(attrs={
            'class': 'form-input w-full px-4 py-3 border border-gray-300 rounded-lg focus:border-green-600 focus:ring-1 focus:ring-green-600 outline-none transition-colors',
            'placeholder': '+254 700 000 000',
            'spellcheck': 'false'
        }),
        validators=[RegexValidator(
            regex=r'^\+?1?\d{9,15}$',
            message='Enter a valid phone number (e.g., +254700000000)'
        )]
    )
    
    institution = forms.CharField(
        required=False,
        widget=forms.TextInput(attrs={
            'class': 'form-input w-full px-4 py-3 border border-gray-300 rounded-lg focus:border-green-600 focus:ring-1 focus:ring-green-600 outline-none transition-colors',
            'placeholder': 'Your school or university',
            'spellcheck': 'false'
        })
    )

    class Meta:
        model = User
        fields = ['full_name', 'phone', 'institution']

    def clean_full_name(self):
        full_name = self.cleaned_data.get('full_name')
        if full_name:
            full_name = full_name.strip()
            if len(full_name) < 2:
                raise ValidationError('Full name must be at least 2 characters')
        return full_name


class ForgotPasswordForm(forms.Form):
    email = forms.EmailField(
        widget=forms.EmailInput(attrs={
            'class': 'form-input w-full px-4 py-3 border border-gray-300 rounded-lg focus:border-green-600 focus:ring-1 focus:ring-green-600 outline-none transition-colors',
            'placeholder': 'you@example.com',
            'autocomplete': 'email',
            'spellcheck': 'false'
        }),
        error_messages={
            'required': 'Email is required',
            'invalid': 'Please enter a valid email address'
        }
    )
    
    captcha = ReCaptchaField(
        widget=ReCaptchaV2Checkbox(attrs={
            'data-theme': 'light',
            'data-size': 'normal'
        })
    )

    def clean_email(self):
        email = self.cleaned_data.get('email')
        if email:
            email = email.lower().strip()
        return email


class ResetPasswordForm(forms.Form):
    password = forms.CharField(
        widget=forms.PasswordInput(attrs={
            'class': 'form-input w-full px-4 py-3 border border-gray-300 rounded-lg focus:border-green-600 focus:ring-1 focus:ring-green-600 outline-none transition-colors',
            'placeholder': 'New password',
            'autocomplete': 'new-password'
        }),
        validators=[validate_password],
        error_messages={
            'required': 'Password is required'
        }
    )
    
    password_confirm = forms.CharField(
        widget=forms.PasswordInput(attrs={
            'class': 'form-input w-full px-4 py-3 border border-gray-300 rounded-lg focus:border-green-600 focus:ring-1 focus:ring-green-600 outline-none transition-colors',
            'placeholder': 'Confirm new password',
            'autocomplete': 'new-password'
        }),
        error_messages={
            'required': 'Please confirm your password'
        }
    )

    def clean(self):
        cleaned_data = super().clean()
        password = cleaned_data.get('password')
        password_confirm = cleaned_data.get('password_confirm')

        if password and password_confirm:
            if password != password_confirm:
                self.add_error('password_confirm', 'Passwords do not match')

        return cleaned_data


class ChangePasswordForm(forms.Form):
    current_password = forms.CharField(
        widget=forms.PasswordInput(attrs={
            'class': 'form-input w-full px-4 py-3 border border-gray-300 rounded-lg focus:border-green-600 focus:ring-1 focus:ring-green-600 outline-none transition-colors',
            'placeholder': 'Current password',
            'autocomplete': 'current-password'
        }),
        error_messages={
            'required': 'Current password is required'
        }
    )
    
    new_password = forms.CharField(
        widget=forms.PasswordInput(attrs={
            'class': 'form-input w-full px-4 py-3 border border-gray-300 rounded-lg focus:border-green-600 focus:ring-1 focus:ring-green-600 outline-none transition-colors',
            'placeholder': 'New password (min 8 characters)',
            'autocomplete': 'new-password'
        }),
        validators=[validate_password],
        error_messages={
            'required': 'New password is required'
        }
    )
    
    confirm_password = forms.CharField(
        widget=forms.PasswordInput(attrs={
            'class': 'form-input w-full px-4 py-3 border border-gray-300 rounded-lg focus:border-green-600 focus:ring-1 focus:ring-green-600 outline-none transition-colors',
            'placeholder': 'Confirm new password',
            'autocomplete': 'new-password'
        }),
        error_messages={
            'required': 'Please confirm your new password'
        }
    )

    def clean(self):
        cleaned_data = super().clean()
        new_password = cleaned_data.get('new_password')
        confirm_password = cleaned_data.get('confirm_password')

        if new_password and confirm_password and new_password != confirm_password:
            self.add_error('confirm_password', 'Passwords do not match')

        return cleaned_data


class OTPVerificationForm(forms.Form):
    otp_code = forms.CharField(
        max_length=6,
        min_length=6,
        widget=forms.TextInput(attrs={
            'class': 'form-input w-full px-4 py-3 border border-gray-300 rounded-lg focus:border-green-600 focus:ring-1 focus:ring-green-600 outline-none transition-colors text-center text-2xl tracking-widest',
            'placeholder': '000000',
            'maxlength': '6',
            'autocomplete': 'one-time-code',
            'inputmode': 'numeric',
            'spellcheck': 'false'
        }),
        error_messages={
            'required': 'Verification code is required',
            'min_length': 'Please enter a valid 6-digit code',
            'max_length': 'Please enter a valid 6-digit code'
        }
    )

    def clean_otp_code(self):
        code = self.cleaned_data.get('otp_code')
        if code:
            code = code.strip()
            if not code.isdigit():
                raise ValidationError('Verification code must contain only numbers')
        return code


class ResendOTPForm(forms.Form):
    email = forms.EmailField(
        widget=forms.EmailInput(attrs={
            'class': 'form-input w-full px-4 py-3 border border-gray-300 rounded-lg focus:border-green-600 focus:ring-1 focus:ring-green-600 outline-none transition-colors',
            'placeholder': 'you@example.com',
            'autocomplete': 'email',
            'spellcheck': 'false'
        }),
        error_messages={
            'required': 'Email is required',
            'invalid': 'Please enter a valid email address'
        }
    )

    def clean_email(self):
        email = self.cleaned_data.get('email')
        if email:
            email = email.lower().strip()
        return email


class SendPasswordChangeCodeForm(forms.Form):
    current_password = forms.CharField(
        widget=forms.PasswordInput(attrs={
            'class': 'form-input w-full px-4 py-3 border border-gray-300 rounded-lg focus:border-green-600 focus:ring-1 focus:ring-green-600 outline-none transition-colors',
            'placeholder': 'Current password',
            'autocomplete': 'current-password'
        }),
        error_messages={
            'required': 'Current password is required'
        }
    )
    
    new_password = forms.CharField(
        widget=forms.PasswordInput(attrs={
            'class': 'form-input w-full px-4 py-3 border border-gray-300 rounded-lg focus:border-green-600 focus:ring-1 focus:ring-green-600 outline-none transition-colors',
            'placeholder': 'New password (min 8 characters)',
            'autocomplete': 'new-password'
        }),
        validators=[validate_password],
        error_messages={
            'required': 'New password is required'
        }
    )


class VerifyPasswordChangeCodeForm(forms.Form):
    code = forms.CharField(
        max_length=6,
        min_length=6,
        widget=forms.TextInput(attrs={
            'class': 'form-input w-full px-4 py-3 border border-gray-300 rounded-lg focus:border-green-600 focus:ring-1 focus:ring-green-600 outline-none transition-colors text-center text-2xl tracking-widest',
            'placeholder': '000000',
            'maxlength': '6',
            'autocomplete': 'one-time-code',
            'inputmode': 'numeric',
            'spellcheck': 'false'
        }),
        error_messages={
            'required': 'Verification code is required',
            'min_length': 'Please enter a valid 6-digit code',
            'max_length': 'Please enter a valid 6-digit code'
        }
    )

    def clean_code(self):
        code = self.cleaned_data.get('code')
        if code:
            code = code.strip()
            if not code.isdigit():
                raise ValidationError('Verification code must contain only numbers')
        return code


class CompletePasswordChangeForm(forms.Form):
    current_password = forms.CharField(
        widget=forms.PasswordInput(attrs={
            'class': 'form-input w-full px-4 py-3 border border-gray-300 rounded-lg focus:border-green-600 focus:ring-1 focus:ring-green-600 outline-none transition-colors',
            'placeholder': 'Current password',
            'autocomplete': 'current-password'
        }),
        error_messages={
            'required': 'Current password is required'
        }
    )
    
    new_password = forms.CharField(
        widget=forms.PasswordInput(attrs={
            'class': 'form-input w-full px-4 py-3 border border-gray-300 rounded-lg focus:border-green-600 focus:ring-1 focus:ring-green-600 outline-none transition-colors',
            'placeholder': 'New password (min 8 characters)',
            'autocomplete': 'new-password'
        }),
        validators=[validate_password],
        error_messages={
            'required': 'New password is required'
        }
    )