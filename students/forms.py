from django import forms
from .models import Student
from finance.models import AcademicYear
from .models import CourseGroup, Teacher, SubjectPrice
from .models import BookSale, InventoryItem, Student

from .models import InventoryRestock  # 👈 هذا هو السطر الناقص

class RestockForm(forms.ModelForm):
    class Meta:
        model = InventoryRestock
        fields = ['quantity', 'note']
        widgets = {
            'quantity': forms.NumberInput(attrs={'class': 'form-control bg-dark text-white border-info', 'min': '1'}),
            'note': forms.TextInput(attrs={'class': 'form-control bg-dark text-white border-info', 'placeholder': 'ملاحظات التوريد'}),
        }

class BookSaleForm(forms.ModelForm):
    class Meta:
        model = BookSale
        fields = ['student', 'item', 'quantity']
        widgets = {
            'student': forms.Select(attrs={'class': 'form-select select2'}),
            'item': forms.Select(attrs={'class': 'form-select select2'}),
            'quantity': forms.NumberInput(attrs={'class': 'form-control bg-dark text-white border-secondary', 'min': 1}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        
        # 1. تصحيح ترتيب الطلاب (استخدام first_name بدلاً من name)
        self.fields['student'].queryset = Student.objects.all().order_by('first_name', 'last_name')
        
        # تخصيص ظهور اسم الطالب (الاسم الأول + الأخير) في القائمة
        self.fields['student'].label_from_instance = lambda obj: f"{obj.first_name} {obj.last_name} - {obj.student_code}"

        # 2. تحسين عرض الأصناف (كتب/زي)
        self.fields['item'].queryset = InventoryItem.objects.all().select_related('subject', 'grade', 'uniform')
        self.fields['item'].label_from_instance = self.label_from_item_instance

    def label_from_item_instance(self, obj):
        """تنسيق اسم الكتاب أو الزي"""
        grade_name = obj.grade.name if obj.grade else "عام"
        if obj.item_type == 'book':
            subject_name = obj.subject.name if obj.subject else "---"
            return f"📚 كتاب {subject_name} - {grade_name}"
        else:
            uniform_name = obj.uniform.name if obj.uniform else "زي مدرسي"
            return f"👕 {uniform_name} - {grade_name}"


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
        # 1. إضافة كل الحقول الجديدة إلى القائمة
        fields = [
            'academic_year', 'first_name', 'last_name', 'image',
            'national_id', 'nationality', 'gender', 'religion', 
            'date_of_birth', 'address', 'phone', 'mother_name',
            'grade', 'classroom', 'specialization', 'enrollment_status',
            'registration_number', 'integration_status'
        ]
        
        # 2. تعريف الـ Widgets لضمان مظهر الـ Dark Theme
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
            # الحقول الجديدة
            'image': forms.FileInput(attrs={'class': 'form-control'}),
            'nationality': forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'مثال: مصري'}),
            'gender': forms.Select(attrs={'class': 'form-select'}),
            'religion': forms.Select(attrs={'class': 'form-select'}),
            'date_of_birth': forms.DateInput(attrs={'class': 'form-control', 'type': 'date'}),
            'address': forms.Textarea(attrs={'class': 'form-control', 'placeholder': 'العنوان بالتفصيل', 'rows': 1}),
            'phone': forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'رقم التليفون'}),
            'mother_name': forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'اسم الأم بالكامل'}),
            'classroom': forms.Select(attrs={'class': 'form-control'}),
            'specialization': forms.Select(attrs={'class': 'form-select'}),
            'enrollment_status': forms.Select(attrs={'class': 'form-select'}),
            'registration_number': forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'رقم القيد الدفتري'}),
            'integration_status': forms.CheckboxInput(attrs={'class': 'form-check-input'}),
        }

        # 3. تسمية الحقول (Labels)
        labels = {
            'academic_year': 'السنة الدراسية',
            'first_name': 'الاسم الأول',
            'last_name': 'اسم العائلة',
            'grade': 'الصف الدراسي',
            'national_id': 'الرقم القومي',
            'nationality': 'الجنسية',
            'gender': 'النوع',
            'religion': 'الديانة',
            'date_of_birth': 'تاريخ الميلاد',
            'address': 'العنوان',
            'phone': 'رقم التليفون',
            'mother_name': 'اسم الأم',
            'classroom': 'الفصل',
            'specialization': 'التخصص',
            'enrollment_status': 'حالة القيد',
            'registration_number': 'رقم القيد',
            'integration_status': 'طالب دمج',
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        
        # جلب السنوات وترتيبها تنازلياً وتحديد النشطة كافتراضية
        years_queryset = AcademicYear.objects.all().order_by('-name')
        self.fields['academic_year'].queryset = years_queryset
        
        active_year = years_queryset.filter(is_active=True).first()
        if active_year:
            self.fields['academic_year'].initial = active_year

        # تأكد من أن الحقول الاختيارية لا تتطلب إدخالاً (للأمان الإضافي)
        for field_name in self.fields:
            if field_name not in ['first_name', 'last_name', 'academic_year', 'grade']:
                self.fields[field_name].required = False