from django import forms
from .models import Student
from finance.models import AcademicYear

class StudentForm(forms.ModelForm):
    class Meta:
        model = Student
        # قم بإزالة 'national_id' و 'specialization' من هذه القائمة
        fields = [
            'academic_year', 'first_name', 'last_name', 'national_id',
            'grade'
        ]
        
        widgets = {
            'academic_year': forms.Select(attrs={'class': 'form-control'}),
            'first_name': forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'الاسم الأول'}),
            'last_name': forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'اسم العائلة'}),
            'grade': forms.Select(attrs={'class': 'form-control'}),
            # الحقل الجديد مع قيود لمنع الحروف والزيادة عن 14 رقم
            'national_id': forms.TextInput(attrs={
                'class': 'form-control',
                'placeholder': 'أدخل 14 رقم (الرقم القومي)',
                'inputmode': 'numeric',  # لإظهار لوحة أرقام فقط على الموبايل
                'oninput': "this.value = this.value.replace(/[^0-9]/g, '').slice(0, 14)", # منع الحروف وقص النص عند 14 رقم
            }),
        }
        labels = {
            'academic_year': 'السنة الدراسية',
            'first_name': 'الاسم الأول',
            'last_name': 'اسم العائلة',
            'grade': 'الصف الدراسي',
        }
        
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        # هذا السطر يرتب السنوات تنازلياً (من الأحدث للأقدم)
        # افترضنا أن حقل الترتيب في موديل AcademicYear هو 'year' أو 'name'
        self.fields['academic_year'].queryset = AcademicYear.objects.all().order_by('-name')
    
        