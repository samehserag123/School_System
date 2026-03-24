from django import forms
from .models import GeneralLedger
from students.models import Student

class TreasuryEntryForm(forms.ModelForm):
    class Meta:
        model = GeneralLedger
        # 1. أضفنا حقل 'collected_by' هنا
        fields = ['student', 'category', 'amount', 'receipt_number', 'notes', 'collected_by']
        widgets = {
            # 2. جعل حقل المحصل مخفي تماماً عن الموظف لضمان عدم التلاعب
            'collected_by': forms.HiddenInput(), 
            
            'student': forms.Select(attrs={'class': 'form-select bg-dark text-white border-secondary select2'}),
            'category': forms.Select(attrs={'class': 'form-select bg-dark text-white border-secondary'}),
            'amount': forms.NumberInput(attrs={'class': 'form-control bg-dark text-white border-secondary', 'placeholder': '0.00'}),
            'receipt_number': forms.TextInput(attrs={'class': 'form-control bg-dark text-white border-secondary', 'placeholder': 'رقم الإيصال اليدوي'}),
            'notes': forms.Textarea(attrs={'class': 'form-control bg-dark text-white border-secondary', 'rows': 2}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['student'].required = False
        self.fields['student'].empty_label = "--- اختر طالب (اختياري) ---"