from django import forms
from django.utils import timezone
from datetime import timedelta
from .models import Order, Attachment


class OrderCreateForm(forms.ModelForm):
    deadline = forms.DateTimeField(
        widget=forms.DateTimeInput(attrs={'class': 'form-input w-full border border-gray-300 px-4 py-3 focus:border-green-600 focus:ring-1 focus:ring-green-600 outline-none transition-colors', 'type': 'datetime-local'}),
        required=True
    )
    instructions = forms.CharField(
        widget=forms.Textarea(attrs={'class': 'form-input w-full border border-gray-300 px-4 py-3 focus:border-green-600 focus:ring-1 focus:ring-green-600 outline-none transition-colors', 'rows': 6, 'placeholder': 'Detailed instructions...'}),
        required=True
    )
    plagiarism_report = forms.BooleanField(required=False, initial=False)
    abstract = forms.BooleanField(required=False, initial=False)
    proofreading = forms.BooleanField(required=False, initial=False)
    one_page_summary = forms.BooleanField(required=False, initial=False)

    class Meta:
        model = Order
        fields = [
            'academic_level', 'paper_type', 'subject', 'topic', 'pages',
            'words', 'spacing', 'slides', 'sources_count', 'deadline', 'format',
            'instructions', 'links'
        ]
        widgets = {
            'academic_level': forms.Select(attrs={'class': 'form-input w-full border border-gray-300 px-4 py-3 focus:border-green-600 focus:ring-1 focus:ring-green-600 outline-none transition-colors'}),
            'paper_type': forms.Select(attrs={'class': 'form-input w-full border border-gray-300 px-4 py-3 focus:border-green-600 focus:ring-1 focus:ring-green-600 outline-none transition-colors'}),
            'subject': forms.TextInput(attrs={'class': 'form-input w-full border border-gray-300 px-4 py-3 focus:border-green-600 focus:ring-1 focus:ring-green-600 outline-none transition-colors', 'placeholder': 'e.g., Psychology'}),
            'topic': forms.TextInput(attrs={'class': 'form-input w-full border border-gray-300 px-4 py-3 focus:border-green-600 focus:ring-1 focus:ring-green-600 outline-none transition-colors', 'placeholder': 'Your paper topic'}),
            'pages': forms.NumberInput(attrs={'class': 'form-input w-full border border-gray-300 px-4 py-3 focus:border-green-600 focus:ring-1 focus:ring-green-600 outline-none transition-colors', 'min': 0.5, 'step': 0.5}),
            'words': forms.NumberInput(attrs={'class': 'form-input w-full border border-gray-300 px-4 py-3 focus:border-green-600 focus:ring-1 focus:ring-green-600 outline-none transition-colors', 'min': 1}),
            'spacing': forms.Select(attrs={'class': 'form-input w-full border border-gray-300 px-4 py-3 focus:border-green-600 focus:ring-1 focus:ring-green-600 outline-none transition-colors'}),
            'slides': forms.NumberInput(attrs={'class': 'form-input w-full border border-gray-300 px-4 py-3 focus:border-green-600 focus:ring-1 focus:ring-green-600 outline-none transition-colors', 'min': 1}),
            'sources_count': forms.NumberInput(attrs={'class': 'form-input w-full border border-gray-300 px-4 py-3 focus:border-green-600 focus:ring-1 focus:ring-green-600 outline-none transition-colors', 'min': 0}),
            'format': forms.Select(attrs={'class': 'form-input w-full border border-gray-300 px-4 py-3 focus:border-green-600 focus:ring-1 focus:ring-green-600 outline-none transition-colors'}),
            'links': forms.Textarea(attrs={'class': 'form-input w-full border border-gray-300 px-4 py-3 focus:border-green-600 focus:ring-1 focus:ring-green-600 outline-none transition-colors', 'rows': 3, 'placeholder': 'One link per line'}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['pages'].required = False
        self.fields['words'].required = False
        self.fields['slides'].required = False
        
        min_date = timezone.now() + timedelta(hours=12)
        self.fields['deadline'].widget.attrs['min'] = min_date.strftime('%Y-%m-%dT%H:%M')
        self.fields['deadline'].initial = min_date.strftime('%Y-%m-%dT%H:%M')

    def clean(self):
        cleaned_data = super().clean()
        paper_type = cleaned_data.get('paper_type')
        pages = cleaned_data.get('pages')
        words = cleaned_data.get('words')
        slides = cleaned_data.get('slides')
        deadline = cleaned_data.get('deadline')

        if paper_type == 'presentation':
            if not slides:
                self.add_error('slides', 'Number of slides is required for presentations')
        else:
            if not pages and not words:
                self.add_error(None, 'Either pages or words must be provided')
            
            if pages and pages < 0.5:
                self.add_error('pages', 'Minimum pages is 0.5')
            
            if words and words < 1:
                self.add_error('words', 'Minimum words is 1')

        if deadline:
            min_deadline = timezone.now() + timedelta(hours=12)
            if deadline < min_deadline:
                self.add_error('deadline', 'Deadline must be at least 12 hours from now')

        return cleaned_data

    def clean_links(self):
        links = self.cleaned_data.get('links', '')
        if not links:
            return []
        
        link_list = []
        for link in links.split('\n'):
            link = link.strip()
            if link:
                dangerous_protocols = ['javascript:', 'data:', 'vbscript:', 'file:']
                is_dangerous = False
                for protocol in dangerous_protocols:
                    if link.lower().startswith(protocol):
                        is_dangerous = True
                        break
                if not is_dangerous:
                    link_list.append({'url': link, 'title': ''})
        
        return link_list


class OrderEditForm(forms.ModelForm):
    class Meta:
        model = Order
        fields = [
            'academic_level', 'paper_type', 'subject', 'topic', 'pages',
            'words', 'spacing', 'slides', 'sources_count', 'deadline', 'format',
            'instructions', 'links'
        ]
        widgets = {
            'academic_level': forms.Select(attrs={'class': 'form-input w-full border border-gray-300 px-4 py-3 focus:border-green-600 focus:ring-1 focus:ring-green-600 outline-none transition-colors'}),
            'paper_type': forms.Select(attrs={'class': 'form-input w-full border border-gray-300 px-4 py-3 focus:border-green-600 focus:ring-1 focus:ring-green-600 outline-none transition-colors'}),
            'subject': forms.TextInput(attrs={'class': 'form-input w-full border border-gray-300 px-4 py-3 focus:border-green-600 focus:ring-1 focus:ring-green-600 outline-none transition-colors'}),
            'topic': forms.TextInput(attrs={'class': 'form-input w-full border border-gray-300 px-4 py-3 focus:border-green-600 focus:ring-1 focus:ring-green-600 outline-none transition-colors'}),
            'pages': forms.NumberInput(attrs={'class': 'form-input w-full border border-gray-300 px-4 py-3 focus:border-green-600 focus:ring-1 focus:ring-green-600 outline-none transition-colors', 'min': 0.5, 'step': 0.5}),
            'words': forms.NumberInput(attrs={'class': 'form-input w-full border border-gray-300 px-4 py-3 focus:border-green-600 focus:ring-1 focus:ring-green-600 outline-none transition-colors', 'min': 1}),
            'spacing': forms.Select(attrs={'class': 'form-input w-full border border-gray-300 px-4 py-3 focus:border-green-600 focus:ring-1 focus:ring-green-600 outline-none transition-colors'}),
            'slides': forms.NumberInput(attrs={'class': 'form-input w-full border border-gray-300 px-4 py-3 focus:border-green-600 focus:ring-1 focus:ring-green-600 outline-none transition-colors', 'min': 1}),
            'sources_count': forms.NumberInput(attrs={'class': 'form-input w-full border border-gray-300 px-4 py-3 focus:border-green-600 focus:ring-1 focus:ring-green-600 outline-none transition-colors', 'min': 0}),
            'format': forms.Select(attrs={'class': 'form-input w-full border border-gray-300 px-4 py-3 focus:border-green-600 focus:ring-1 focus:ring-green-600 outline-none transition-colors'}),
            'instructions': forms.Textarea(attrs={'class': 'form-input w-full border border-gray-300 px-4 py-3 focus:border-green-600 focus:ring-1 focus:ring-green-600 outline-none transition-colors', 'rows': 6}),
            'links': forms.Textarea(attrs={'class': 'form-input w-full border border-gray-300 px-4 py-3 focus:border-green-600 focus:ring-1 focus:ring-green-600 outline-none transition-colors', 'rows': 3, 'placeholder': 'One link per line'}),
        }

    def clean_links(self):
        links = self.cleaned_data.get('links', '')
        if not links:
            return []
        
        link_list = []
        for link in links.split('\n'):
            link = link.strip()
            if link:
                dangerous_protocols = ['javascript:', 'data:', 'vbscript:', 'file:']
                is_dangerous = False
                for protocol in dangerous_protocols:
                    if link.lower().startswith(protocol):
                        is_dangerous = True
                        break
                if not is_dangerous:
                    link_list.append({'url': link, 'title': ''})
        
        return link_list


class CancelOrderForm(forms.Form):
    CANCELLATION_REASONS = [
        ('deadline_passed', 'Deadline passed with no response'),
        ('unsatisfied_quality', 'Unsatisfied with quality'),
        ('found_elsewhere', 'Found help elsewhere'),
        ('change_of_requirements', 'Changed requirements'),
        ('writer_communication', 'Poor writer communication'),
        ('other', 'Other reason'),
    ]
    
    reason = forms.ChoiceField(
        choices=CANCELLATION_REASONS,
        widget=forms.Select(attrs={'class': 'form-input w-full border border-gray-300 px-4 py-3 focus:border-green-600 focus:ring-1 focus:ring-green-600 outline-none transition-colors'})
    )
    feedback = forms.CharField(
        required=False,
        widget=forms.Textarea(attrs={'class': 'form-input w-full border border-gray-300 px-4 py-3 focus:border-green-600 focus:ring-1 focus:ring-green-600 outline-none transition-colors', 'rows': 4, 'placeholder': 'Please provide details about why you are cancelling...'})
    )


class DeclineOrderForm(forms.Form):
    reason = forms.CharField(
        widget=forms.Textarea(attrs={'class': 'form-input w-full border border-gray-300 px-4 py-3 focus:border-green-600 focus:ring-1 focus:ring-green-600 outline-none transition-colors', 'rows': 4, 'placeholder': 'Reason for declining...'}),
        required=True
    )
    feedback = forms.CharField(
        required=False,
        widget=forms.Textarea(attrs={'class': 'form-input w-full border border-gray-300 px-4 py-3 focus:border-green-600 focus:ring-1 focus:ring-green-600 outline-none transition-colors', 'rows': 3, 'placeholder': 'Additional feedback for the client...'})
    )


class ResubmitOrderForm(forms.Form):
    notes = forms.CharField(
        required=False,
        widget=forms.Textarea(attrs={'class': 'form-input w-full border border-gray-300 px-4 py-3 focus:border-green-600 focus:ring-1 focus:ring-green-600 outline-none transition-colors', 'rows': 4, 'placeholder': 'Any changes made or additional notes...'})
    )


class SplitOrderForm(forms.Form):
    parts = forms.IntegerField(
        min_value=2,
        max_value=10,
        initial=2,
        widget=forms.NumberInput(attrs={'class': 'form-input w-full border border-gray-300 px-4 py-3 focus:border-green-600 focus:ring-1 focus:ring-green-600 outline-none transition-colors', 'min': 2, 'max': 10})
    )


class OrderActionForm(forms.Form):
    ACTION_CHOICES = [
        ('cancel', 'Cancel Order'),
        ('request_revision', 'Request Revision'),
        ('approve', 'Approve Order'),
        ('request_refund', 'Request Refund'),
        ('decline', 'Decline Order'),
        ('resubmit', 'Resubmit Order'),
        ('reorder', 'Reorder'),
        ('split', 'Split Order'),
    ]
    
    action = forms.ChoiceField(
        choices=ACTION_CHOICES,
        widget=forms.Select(attrs={'class': 'form-input w-full border border-gray-300 px-4 py-3 focus:border-green-600 focus:ring-1 focus:ring-green-600 outline-none transition-colors'})
    )
    reason = forms.CharField(
        required=False,
        widget=forms.Textarea(attrs={'class': 'form-input w-full border border-gray-300 px-4 py-3 focus:border-green-600 focus:ring-1 focus:ring-green-600 outline-none transition-colors', 'rows': 3})
    )
    feedback = forms.CharField(
        required=False,
        widget=forms.Textarea(attrs={'class': 'form-input w-full border border-gray-300 px-4 py-3 focus:border-green-600 focus:ring-1 focus:ring-green-600 outline-none transition-colors', 'rows': 3})
    )
    grade = forms.CharField(
        required=False,
        widget=forms.TextInput(attrs={'class': 'form-input w-full border border-gray-300 px-4 py-3 focus:border-green-600 focus:ring-1 focus:ring-green-600 outline-none transition-colors', 'placeholder': 'e.g., A, 95%'})
    )
    parts = forms.IntegerField(
        required=False,
        min_value=2,
        max_value=10,
        widget=forms.NumberInput(attrs={'class': 'form-input w-full border border-gray-300 px-4 py-3 focus:border-green-600 focus:ring-1 focus:ring-green-600 outline-none transition-colors', 'placeholder': 'Number of parts'})
    )


class OrderFilterForm(forms.Form):
    STATUS_CHOICES = [
        ('', 'All Status'),
        ('request', 'Request'),
        ('in_progress', 'In Progress'),
        ('awaiting_approval', 'Awaiting Approval'),
        ('completed', 'Completed'),
        ('cancelled', 'Cancelled'),
        ('declined', 'Declined'),
        ('refund_pending', 'Refund Pending'),
    ]
    
    status = forms.ChoiceField(
        choices=STATUS_CHOICES,
        required=False,
        widget=forms.Select(attrs={'class': 'form-input w-full border border-gray-300 px-4 py-3 focus:border-green-600 focus:ring-1 focus:ring-green-600 outline-none transition-colors'})
    )
    search = forms.CharField(
        required=False,
        widget=forms.TextInput(attrs={'class': 'form-input w-full border border-gray-300 px-4 py-3 focus:border-green-600 focus:ring-1 focus:ring-green-600 outline-none transition-colors', 'placeholder': 'Search by order number or topic...'})
    )


class AttachmentForm(forms.ModelForm):
    class Meta:
        model = Attachment
        fields = ['file']
        widgets = {
            'file': forms.FileInput(attrs={'class': 'form-input w-full border border-gray-300 px-4 py-3 focus:border-green-600 focus:ring-1 focus:ring-green-600 outline-none transition-colors'})
        }


class RevisionRequestForm(forms.Form):
    notes = forms.CharField(
        widget=forms.Textarea(attrs={'class': 'form-input w-full border border-gray-300 px-4 py-3 focus:border-green-600 focus:ring-1 focus:ring-green-600 outline-none transition-colors', 'rows': 6, 'placeholder': 'Please provide detailed revision instructions...'}),
        required=True
    )


class RefundRequestForm(forms.Form):
    reason = forms.CharField(
        widget=forms.Textarea(attrs={'class': 'form-input w-full border border-gray-300 px-4 py-3 focus:border-green-600 focus:ring-1 focus:ring-green-600 outline-none transition-colors', 'rows': 6, 'placeholder': 'Please explain why you are requesting a refund...'}),
        required=True
    )


class RatingForm(forms.Form):
    rating = forms.ChoiceField(
        choices=[(i, str(i)) for i in range(1, 6)],
        widget=forms.RadioSelect(attrs={'class': 'form-radio'}),
        required=True
    )
    feedback = forms.CharField(
        required=False,
        widget=forms.Textarea(attrs={'class': 'form-input w-full border border-gray-300 px-4 py-3 focus:border-green-600 focus:ring-1 focus:ring-green-600 outline-none transition-colors', 'rows': 4, 'placeholder': 'Share your experience with this writer...'})
    )


class SearchForm(forms.Form):
    q = forms.CharField(
        required=False,
        widget=forms.TextInput(attrs={'class': 'form-input w-full border border-gray-300 px-4 py-3 focus:border-green-600 focus:ring-1 focus:ring-green-600 outline-none transition-colors', 'placeholder': 'Search orders by number or topic...'})
    )
    status = forms.ChoiceField(
        choices=[('', 'All')] + Order.STATUS_CHOICES,
        required=False,
        widget=forms.Select(attrs={'class': 'form-input w-full border border-gray-300 px-4 py-3 focus:border-green-600 focus:ring-1 focus:ring-green-600 outline-none transition-colors'})
    )
    date_from = forms.DateField(
        required=False,
        widget=forms.DateInput(attrs={'class': 'form-input w-full border border-gray-300 px-4 py-3 focus:border-green-600 focus:ring-1 focus:ring-green-600 outline-none transition-colors', 'type': 'date'})
    )
    date_to = forms.DateField(
        required=False,
        widget=forms.DateInput(attrs={'class': 'form-input w-full border border-gray-300 px-4 py-3 focus:border-green-600 focus:ring-1 focus:ring-green-600 outline-none transition-colors', 'type': 'date'})
    )


class TemplateSaveForm(forms.Form):
    name = forms.CharField(
        max_length=200,
        widget=forms.TextInput(attrs={'class': 'form-input w-full border border-gray-300 px-4 py-3 focus:border-green-600 focus:ring-1 focus:ring-green-600 outline-none transition-colors', 'placeholder': 'Template name...'}),
        required=True
    )
    description = forms.CharField(
        required=False,
        widget=forms.Textarea(attrs={'class': 'form-input w-full border border-gray-300 px-4 py-3 focus:border-green-600 focus:ring-1 focus:ring-green-600 outline-none transition-colors', 'rows': 3, 'placeholder': 'Template description...'})
    )