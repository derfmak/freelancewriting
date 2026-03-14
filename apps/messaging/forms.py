from django import forms
from .models import Message, Conversation

class MessageForm(forms.ModelForm):
    class Meta:
        model = Message
        fields = ['content', 'message_type', 'file_url', 'file_name']
        widgets = {
            'content': forms.Textarea(attrs={
                'class': 'w-full border border-gray-300 px-4 py-3 focus:border-green-600 focus:ring-1 focus:ring-green-600 outline-none transition-colors',
                'rows': 2,
                'placeholder': 'Type your message...'
            }),
            'message_type': forms.HiddenInput(),
            'file_url': forms.HiddenInput(),
            'file_name': forms.HiddenInput(),
        }

class MessageFilterForm(forms.Form):
    search = forms.CharField(required=False, widget=forms.TextInput(attrs={
        'class': 'w-full border border-gray-300 px-4 py-2 focus:border-green-600 focus:ring-1 focus:ring-green-600 outline-none transition-colors text-sm',
        'placeholder': 'Search messages...'
    }))

class ConversationCreateForm(forms.ModelForm):
    class Meta:
        model = Conversation
        fields = ['order', 'student', 'admin']
        widgets = {
            'order': forms.HiddenInput(),
            'student': forms.HiddenInput(),
            'admin': forms.HiddenInput(),
        }