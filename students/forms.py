from django import forms
from .models import Student
from finance.models import AcademicYear
from .models import CourseGroup, Teacher, SubjectPrice


class CourseGroupForm(forms.ModelForm):
    # 1. حقل المدرس (فلتر وهمي): ده اللي هيخلينا نختار المدرس عشان المادة تظهر
    teacher = forms.ModelChoiceField(
        queryset=Teacher.objects.all(),
        label="1. اختر المدرس",
        required=False,
        empty_label="--- ابحث واختار اسم المدرس ---",
        widget=forms.Select(attrs={'class': 'form-select', 'id': 'id_teacher_filter'})
    )

    class Meta:
        model = CourseGroup
        # نرتتب الحقول بحيث المدرس يظهر قبل المادة
        fields = ['student', 'teacher', 'course_info', 'notes'] 
        
        widgets = {
            # حقل الطالب: هنركب عليه Select2 في الـ HTML عشان الـ 1000 طالب
            'student': forms.Select(attrs={'class': 'form-select select2-student'}),
            
            # حقل المادة: هيتفلتر بناءً على المدرس بواسطة JavaScript
            'course_info': forms.Select(attrs={'class': 'form-select', 'id': 'id_course_info'}),
            
            'notes': forms.Textarea(attrs={'class': 'form-control', 'rows': 1, 'placeholder': 'أي ملاحظات إضافية...'}),
        }
        
        labels = {
            'student': 'اسم الطالب (بحث بالاسم)',
            'course_info': '2. المادة / النوع / السعر',
            'notes': 'ملاحظات',
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        # تخصيص رسائل القوائم الفارغة
        self.fields['course_info'].empty_label = "--- اختر المدرس أولاً لرؤية مواده ---"
        self.fields['student'].empty_label = "اكتب اسم الطالب للبحث..."
             
        
class StudentForm(forms.ModelForm):
    class Meta:
        model = Student
        fields = [
            'academic_year', 'first_name', 'last_name', 'national_id',
            'grade'
        ]
        
        widgets = {
            'academic_year': forms.Select(attrs={'class': 'form-control'}),
            'first_name': forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'الاسم الأول'}),
            'last_name': forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'اسم العائلة'}),
            'grade': forms.Select(attrs={'class': 'form-control'}),
            'national_id': forms.TextInput(attrs={
                'class': 'form-control',
                'placeholder': 'أدخل 14 رقم (الرقم القومي)',
                'inputmode': 'numeric',
                'oninput': "this.value = this.value.replace(/[^0-9]/g, '').slice(0, 14)",
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
        
        # 1. جلب السنوات وترتيبها تنازلياً
        years_queryset = AcademicYear.objects.all().order_by('-name')
        self.fields['academic_year'].queryset = years_queryset
        
        # 2. تحديد السنة النشطة كوضع افتراضي
        # تأكد أن اسم الحقل في موديل AcademicYear هو 'is_active'
        active_year = years_queryset.filter(is_active=True).first()
        
        if active_year:
            self.fields['academic_year'].initial = active_year
    
        