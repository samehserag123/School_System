from django import forms
from .models import GeneralLedger
from students.models import Student

class TreasuryEntryForm(forms.ModelForm):
    class Meta:
        model = GeneralLedger
        # 1. الحقول المطلوبة مع حقل المحصل المخفي
        fields = ['student', 'category', 'amount', 'receipt_number', 'notes', 'collected_by']
        
        widgets = {
            # 2. جعل حقل المحصل مخفي تماماً لضمان عدم التلاعب
            'collected_by': forms.HiddenInput(), 
            
            'student': forms.Select(attrs={'class': 'form-select bg-dark text-white border-secondary select2'}),
            'category': forms.Select(attrs={'class': 'form-select bg-dark text-white border-secondary'}),
            'amount': forms.NumberInput(attrs={'class': 'form-control bg-dark text-white border-secondary', 'placeholder': '0.00'}),
            'receipt_number': forms.TextInput(attrs={'class': 'form-control bg-dark text-white border-secondary', 'placeholder': 'رقم الإيصال اليدوي'}),
            'notes': forms.Textarea(attrs={'class': 'form-control bg-dark text-white border-secondary', 'rows': 2}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        # جعل اختيار الطالب اختيارياً وتنسيق النص الافتراضي
        self.fields['student'].required = False
        self.fields['student'].empty_label = "--- اختر طالب (اختياري) ---"

    # 🔥 إضافة التحقق من تكرار رقم الإيصال قبل الحفظ لمنع الـ Error الأحمر
    def clean_receipt_number(self):
        receipt_number = self.cleaned_data.get('receipt_number')
        # التأكد من عدم وجود الرقم مسبقاً في قاعدة البيانات
        if GeneralLedger.objects.filter(receipt_number=receipt_number).exists():
            raise forms.ValidationError("عفواً، رقم الإيصال هذا مسجل مسبقاً في المنظومة!")
        return receipt_number