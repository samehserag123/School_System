from django import forms
from .models import Student
from finance.models import AcademicYear
from .models import CourseGroup, Teacher, SubjectPrice
from .models import BookSale, InventoryItem, Student

from .models import InventoryRestock  # 👈 هذا هو السطر الناقص

from treasury.models import GeneralLedger

from .models import BusSubscription, BusRoute
from .models import RemedialProgramRecord, RemedialFeeSetting

class RemedialProgramForm(forms.ModelForm):
    class Meta:
        model = RemedialProgramRecord
        fields = ['student', 'subjects_count', 'notes']
        widgets = {
            'student': forms.Select(attrs={'class': 'form-control select2'}),
            'subjects_count': forms.NumberInput(attrs={'class': 'form-control', 'min': '1', 'step': '1'}),
            'notes': forms.Textarea(attrs={'class': 'form-control', 'rows': 2}),
        }

class RemedialFeeSettingForm(forms.ModelForm):
    class Meta:
        model = RemedialFeeSetting
        fields = ['academic_year', 'fee_per_subject']
        widgets = {
            'academic_year': forms.Select(attrs={'class': 'form-select'}),
            'fee_per_subject': forms.NumberInput(attrs={'class': 'form-control', 'step': '1'}),
        }
        

class GeneralLedgerForm(forms.ModelForm):
    class Meta:
        model = GeneralLedger
        fields = ['student', 'category', 'amount', 'receipt_number', 'notes']
        widgets = {
            'student': forms.Select(attrs={'class': 'form-select bg-dark text-white border-secondary'}),
            'category': forms.Select(attrs={'class': 'form-select bg-dark text-white border-secondary'}),
            'amount': forms.NumberInput(attrs={'class': 'form-control bg-dark text-white border-secondary', 'placeholder': '0.00'}),
            'receipt_number': forms.TextInput(attrs={'class': 'form-control bg-dark text-white border-secondary', 'placeholder': 'رقم الإيصال الدفتري'}),
            'notes': forms.Textarea(attrs={'class': 'form-control bg-dark text-white border-secondary', 'rows': 3, 'placeholder': 'أضف #رقم_الإذن لربط سداد الكتب'}),
        }

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
        # إضافة حقل pay_now لتمكين السداد الفوري من نفس الشاشة
        fields = ['student', 'item', 'quantity', 'pay_now'] 
        widgets = {
            'student': forms.Select(attrs={'class': 'form-select select2'}),
            'item': forms.Select(attrs={'class': 'form-select select2'}),
            'quantity': forms.NumberInput(attrs={'class': 'form-control bg-dark text-white border-secondary', 'min': 1}),
            # تنسيق حقل الدفع بلون مميز لتمييزه كعملية مالية
            'pay_now': forms.NumberInput(attrs={
                'class': 'form-control bg-warning text-dark fw-bold border-warning',
                'placeholder': 'أدخل المبلغ المحصل الآن...',
                'min': 0
            }),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        
        # 1. تصحيح ترتيب الطلاب وتخصيص الاسم
        self.fields['student'].queryset = Student.objects.all().order_by('first_name', 'last_name')
        self.fields['student'].label_from_instance = lambda obj: f"{obj.first_name} {obj.last_name} - {obj.student_code}"

        # 2. تحسين عرض الأصناف (كتب/زي)
        self.fields['item'].queryset = InventoryItem.objects.all().select_related('subject', 'grade', 'uniform')
        self.fields['item'].label_from_instance = self.label_from_item_instance
        
        # إضافة تسمية توضيحية لحقل الدفع
        self.fields['pay_now'].label = "المبلغ المدفوع نقداً الآن"

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
    # --- حقول التحكم والطلاب الخارجين ---
    is_external = forms.BooleanField(
        label="تسجيل طالب من خارج المدرسة؟", 
        required=False,
        widget=forms.CheckboxInput(attrs={'class': 'form-check-input', 'id': 'flexSwitchExternal'})
    )
    
    ext_name = forms.CharField(
        label="اسم الطالب الخارجي", 
        required=False,
        widget=forms.TextInput(attrs={'class': 'form-control bg-dark text-white border-info border-opacity-25', 'placeholder': 'الاسم بالكامل'})
    )
    
    
    ext_phone = forms.CharField(
        label="رقم التليفون", 
        required=False,
        widget=forms.TextInput(attrs={'class': 'form-control bg-dark text-white border-info border-opacity-25', 'placeholder': '01xxxxxxxxx'})
    )

    # --- حقل المدرس (فلتر وهمي) ---
    teacher = forms.ModelChoiceField(
        queryset=Teacher.objects.all(),
        label="1. اختر المدرس",
        required=False,
        empty_label="--- ابحث واختار اسم المدرس ---",
        widget=forms.Select(attrs={'class': 'form-select', 'id': 'id_teacher_filter'})
    )

    class Meta:
        model = CourseGroup
        # ترتيب الحقول بما يتناسب مع الإدخال الجديد
        fields = ['student', 'teacher', 'course_info', 'total_sessions', 'notes'] 
        
        widgets = {
            # حقل الطالب المدرسي
            'student': forms.Select(attrs={'class': 'form-select select2-student'}),
            
            # حقل المادة
            'course_info': forms.Select(attrs={'class': 'form-select', 'id': 'id_course_info'}),
            
            # حقل عدد الحصص المطور لراحة عينك
            'total_sessions': forms.NumberInput(attrs={
                'class': 'form-control',
                'placeholder': '4',
                'min': '1',
                'style': 'font-weight: 900; text-align: center;' 
            }),
            
            'notes': forms.Textarea(attrs={'class': 'form-control', 'rows': 1, 'placeholder': 'أي ملاحظات إضافية...'}),
        }
        
        labels = {
            'student': 'اسم الطالب المدرسي',
            'course_info': '2. المادة / النوع / السعر',
            'total_sessions': 'إجمالي الحصص',
            'notes': 'ملاحظات',
        }

    # students/forms.py

def __init__(self, *args, **kwargs):
    super().__init__(*args, **kwargs)
    
    # 1. تخصيص رسائل القوائم الفارغة [cite: 2026-04-06]
    self.fields['course_info'].empty_label = "--- اختر المدرس أولاً لرؤية مواده ---"
    self.fields['student'].empty_label = "اكتب اسم الطالب للبحث..."
    
    # هذا التعديل يتيح لك البحث بأي من هذه البيانات داخل القائمة المنسدلة
    self.fields['student'].queryset = Student.objects.all()
    self.fields['student'].label_from_instance = lambda obj: f"{obj.get_full_name()} | كود: {obj.id} | قومي: {obj.national_id}" 
    
    # 3. التأكد من أن حقل الحصص مطلوب ونشط [cite: 2026-04-06]
    self.fields['total_sessions'].required = True
    
    self.fields['student'].required = False

class BusSubscriptionForm(forms.ModelForm):
    class Meta:
        model = BusSubscription
        fields = ['student', 'route', 'sub_type', 'start_date', 'end_date', 'required_amount', 'notes']
        widgets = {
            'student': forms.Select(attrs={'class': 'form-select bg-black text-white border-secondary select2'}),
            'route': forms.Select(attrs={'class': 'form-select bg-black text-white border-secondary'}),
            'sub_type': forms.Select(attrs={'class': 'form-select bg-black text-white border-secondary'}),
            'start_date': forms.DateInput(attrs={'type': 'date', 'class': 'form-control bg-black text-white border-secondary'}),
            'end_date': forms.DateInput(attrs={'type': 'date', 'class': 'form-control bg-black text-white border-secondary'}),
            'required_amount': forms.NumberInput(attrs={'class': 'form-control border-info text-info', 'style': 'background: rgba(56, 189, 248, 0.05);', 'placeholder': '0.00'}),
            'notes': forms.Textarea(attrs={'class': 'form-control bg-black text-white border-secondary', 'rows': 2}),
        }
        
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        # يمكنك هنا إضافة فلاتر مخصصة، مثلاً:
        # self.fields['route'].queryset = BusRoute.objects.filter(capacity__gt=0)             
 
class StudentForm(forms.ModelForm):
    class Meta:
        model = Student
        # 1. تم إزالة المسافة الزائدة من 'whatsapp_number'
        fields = [
            'academic_year', 'first_name', 'last_name', 'image',
            'national_id', 'nationality', 'gender', 'religion', 
            'date_of_birth', 'address', 'phone', 'whatsapp_number', 'mother_name', 'father_job',
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
            'image': forms.FileInput(attrs={'class': 'form-control'}),
            'nationality': forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'مثال: مصري'}),
            'gender': forms.Select(attrs={'class': 'form-select'}),
            'religion': forms.Select(attrs={'class': 'form-select'}),
            'date_of_birth': forms.DateInput(attrs={'class': 'form-control', 'type': 'date'}),
            'address': forms.Textarea(attrs={'class': 'form-control', 'placeholder': 'العنوان بالتفصيل', 'rows': 1}),
            'phone': forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'رقم التليفون'}),
            # تم إضافة حقل الواتساب هنا
            'whatsapp_number': forms.TextInput(attrs={
                'class': 'form-control', 
                'placeholder': 'رقم الواتساب',
                'inputmode': 'numeric',
                'oninput': "this.value = this.value.replace(/[^0-9]/g, '').slice(0, 11)"
            }),
            'father_job': forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'أدخل وظيفة الأب (اختياري)'}),
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
            'whatsapp_number': 'رقم الواتساب', # تم إضافة التسمية هنا
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
                
                
    def clean_whatsapp_number(self):
        number = self.cleaned_data.get('whatsapp_number')

        # تحسين التحقق ليشمل الأرقام فقط والتأكد من الطول (11 رقم)
        if number:
            if not number.startswith('01') or not number.isdigit() or len(number) != 11:
                raise forms.ValidationError("برجاء إدخال رقم واتساب مصري صحيح (11 رقم يبدأ بـ 01)")

        return number