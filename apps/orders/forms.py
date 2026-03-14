from django import forms
from django.utils import timezone
from .models import Order, Attachment

class OrderCreateForm(forms.ModelForm):
    deadline = forms.DateTimeField(
        widget=forms.DateTimeInput(attrs={'class': 'form-input', 'type': 'datetime-local'}),
        required=True
    )
    instructions = forms.CharField(
        widget=forms.Textarea(attrs={'class': 'form-input', 'rows': 6, 'placeholder': 'Detailed instructions...'}),
        required=True
    )
    plagiarism_report = forms.BooleanField(required=False, initial=False)
    abstract = forms.BooleanField(required=False, initial=False)

    class Meta:
        model = Order
        fields = [
            'academic_level', 'paper_type', 'subject', 'topic', 'pages',
            'deadline', 'sources', 'format', 'instructions',
            'plagiarism_report', 'abstract'
        ]
        widgets = {
            'academic_level': forms.Select(attrs={'class': 'form-input'}),
            'paper_type': forms.Select(attrs={'class': 'form-input'}),
            'subject': forms.TextInput(attrs={'class': 'form-input', 'placeholder': 'e.g., Psychology'}),
            'topic': forms.TextInput(attrs={'class': 'form-input', 'placeholder': 'Your paper topic'}),
            'pages': forms.NumberInput(attrs={'class': 'form-input', 'min': 1, 'value': 1}),
            'sources': forms.TextInput(attrs={'class': 'form-input', 'value': 5}),
            'format': forms.Select(attrs={'class': 'form-input'}),
        }

    def clean_deadline(self):
        deadline = self.cleaned_data['deadline']
        min_deadline = timezone.now() + timezone.timedelta(hours=6)
        
        if deadline < min_deadline:
            raise forms.ValidationError('Deadline must be at least 6 hours from now')
        
        return deadline

class OrderActionForm(forms.Form):
    ACTION_CHOICES = [
        ('cancel', 'Cancel Order'),
        ('request_revision', 'Request Revision'),
        ('approve', 'Approve Order'),
        ('request_refund', 'Request Refund'),
    ]
    
    action = forms.ChoiceField(choices=ACTION_CHOICES)
    reason = forms.CharField(required=False, widget=forms.Textarea(attrs={'class': 'form-input', 'rows': 3}))
    grade = forms.CharField(required=False, widget=forms.TextInput(attrs={'class': 'form-input', 'placeholder': 'e.g., F, 45%'}))

class OrderFilterForm(forms.Form):
    STATUS_CHOICES = [
        ('', 'All Status'),
        ('pending', 'Pending'),
        ('ongoing', 'Ongoing'),
        ('awaiting_review', 'Awaiting Review'),
        ('completed', 'Completed'),
        ('cancelled', 'Cancelled'),
    ]
    
    status = forms.ChoiceField(choices=STATUS_CHOICES, required=False)
    search = forms.CharField(required=False, widget=forms.TextInput(attrs={'class': 'form-input', 'placeholder': 'Search orders...'}))

class AttachmentForm(forms.ModelForm):
    class Meta:
        model = Attachment
        fields = ['file']