from django import forms
from .models import (
    Student, Grade, Classroom, Subject, CourseGroup, Teacher, SubjectPrice,
    BookSale, InventoryItem, InventoryRestock, BusSubscription, BusRoute,
    RemedialProgramRecord, RemedialFeeSetting, AttendanceRecord, ExamResult,
    ReEnrollmentRecord, SubjectConfig, AcademyEnrollment, AcademySubject, AcademyTermSubject
)
from finance.models import AcademicYear
from treasury.models import GeneralLedger

class AcademyEnrollmentForm(forms.ModelForm):
    pay_now = forms.DecimalField(
        label="المبلغ المحصل الآن (ج.م)",
        required=False,
        initial=0.00,
        widget=forms.NumberInput(attrs={
            'class': 'form-control bg-dark text-warning fw-900 fs-5 border-warning text-center',
            'placeholder': '0.00',
            'id': 'id_pay_now',
            'step': '0.01'
        })
    )
    receipt_number = forms.CharField(
        label="رقم الإيصال الدفتري / الورقي",
        required=False,
        widget=forms.TextInput(attrs={
            'class': 'form-control bg-dark text-white border-secondary fw-bold text-center',
            'placeholder': 'مثال: 15356'
        })
    )
    notes = forms.CharField(
        label="ملاحظات التسجيل والدفع",
        required=False,
        widget=forms.TextInput(attrs={
            'class': 'form-control bg-dark text-white border-secondary',
            'placeholder': 'أي ملاحظات إضافية عن طريقة السداد...'
        })
    )

    class Meta:
        model = AcademyEnrollment
        fields = ['student', 'course', 'enrollment_date', 'custom_price']
        widgets = {
            'student': forms.HiddenInput(attrs={'id': 'id_student_hidden'}),
            'course': forms.Select(attrs={'class': 'form-select bg-dark text-white border-secondary fw-bold', 'id': 'id_course_select'}),
            'enrollment_date': forms.DateInput(attrs={'type': 'date', 'class': 'form-control bg-dark text-white border-secondary'}),
            'custom_price': forms.NumberInput(attrs={'class': 'form-control bg-dark text-white border-secondary', 'id': 'id_custom_price', 'placeholder': 'اتركه فارغاً للاستفادة بالسعر الموحد'}),
        }
        labels = {
            'student': 'الطالب',
            'course': 'الكورس / الدبلومة الأكاديمية',
            'enrollment_date': 'تاريخ بدء الدراسة',
            'custom_price': 'سعر مخصص (اختياري)',
        }


class AttendanceFilterForm(forms.Form):
    date = forms.DateField(widget=forms.DateInput(attrs={'type': 'date', 'class': 'form-control'}), label="تاريخ اليوم")
    grade = forms.ModelChoiceField(queryset=Grade.objects.all(), widget=forms.Select(attrs={'class': 'form-control', 'onchange': 'this.form.submit()'}), label="الصف الدراسي")
    classroom = forms.ModelChoiceField(queryset=Classroom.objects.all(), required=False, widget=forms.Select(attrs={'class': 'form-control'}), label="الفصل")
    term = forms.ChoiceField(choices=[('term1', 'الترم الأول'), ('term2', 'الترم الثاني')], widget=forms.Select(attrs={'class': 'form-control'}), label="الترم")


class ExamResultFilterForm(forms.Form):
    exam_type = forms.ChoiceField(choices=[('month', 'امتحان شهر'), ('term', 'امتحان نهاية ترم'), ('second_session', 'امتحان دور ثاني (ملاحق)')], widget=forms.Select(attrs={'class': 'form-control', 'id': 'exam_type_select'}), label="نوع الامتحان")
    term = forms.ChoiceField(choices=[('term1', 'الترم الأول'), ('term2', 'الترم الثاني'), ('second_session', 'الدور الثاني')], widget=forms.Select(attrs={'class': 'form-control'}), label="الترم/الفترة")
    month = forms.ChoiceField(choices=[('', '---')] + [('10', 'أكتوبر'), ('11', 'نوفمبر'), ('12', 'ديسمبر'), ('2', 'فبراير'), ('3', 'مارس'), ('4', 'أبريل')], required=False, widget=forms.Select(attrs={'class': 'form-control'}), label="الشهر (إن وجد)")
    grade = forms.ModelChoiceField(queryset=Grade.objects.all(), widget=forms.Select(attrs={'class': 'form-control'}), label="الصف الدراسي")
    classroom = forms.ModelChoiceField(queryset=Classroom.objects.all(), required=False, widget=forms.Select(attrs={'class': 'form-control'}), label="الفصل")
    subject = forms.ModelChoiceField(queryset=Subject.objects.all(), widget=forms.Select(attrs={'class': 'form-control'}), label="المادة الدراسية")


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
        fields = ['student', 'item', 'quantity', 'pay_now']
        widgets = {
            'student': forms.Select(attrs={'class': 'form-select select2'}),
            'item': forms.Select(attrs={'class': 'form-select select2'}),
            'quantity': forms.NumberInput(attrs={'class': 'form-control bg-dark text-white border-secondary', 'min': 1}),
            'pay_now': forms.NumberInput(attrs={
                'class': 'form-control bg-warning text-dark fw-bold border-warning',
                'placeholder': 'أدخل المبلغ المحصل الآن...',
                'min': 0
            }),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['student'].queryset = Student.objects.all().order_by('first_name', 'last_name')
        self.fields['student'].label_from_instance = lambda obj: f"{obj.first_name} {obj.last_name} - {obj.student_code}"
        self.fields['item'].queryset = InventoryItem.objects.all().select_related('subject', 'grade', 'uniform')
        self.fields['item'].label_from_instance = self.label_from_item_instance
        self.fields['pay_now'].label = "المبلغ المدفوع نقداً الآن"

    def label_from_item_instance(self, obj):
        grade_name = obj.grade.name if obj.grade else "عام"
        if obj.item_type == 'book':
            subject_name = obj.subject.name if obj.subject else "---"
            return f"📚 كتاب {subject_name} - {grade_name}"
        else:
            uniform_name = obj.uniform.name if obj.uniform else "زي مدرسي"
            return f"👕 {uniform_name} - {grade_name}"


class CourseGroupForm(forms.ModelForm):
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
    teacher = forms.ModelChoiceField(
        queryset=Teacher.objects.all(),
        label="1. اختر المدرس",
        required=False,
        empty_label="--- ابحث واختار اسم المدرس ---",
        widget=forms.Select(attrs={'class': 'form-select', 'id': 'id_teacher_filter'})
    )

    class Meta:
        model = CourseGroup
        fields = ['student', 'course_info', 'total_sessions', 'notes']
        widgets = {
            'student': forms.Select(attrs={'class': 'form-select select2-student'}),
            'course_info': forms.Select(attrs={'class': 'form-select', 'id': 'id_course_info'}),
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

    field_order = ['is_external', 'ext_name', 'ext_phone', 'teacher', 'student', 'course_info', 'total_sessions', 'notes']

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['course_info'].empty_label = "--- اختر المدرس أولاً لرؤية مواده ---"
        self.fields['student'].empty_label = "اكتب اسم الطالب للبحث..."
        self.fields['student'].queryset = Student.objects.all()
        self.fields['student'].label_from_instance = lambda obj: f"{obj.get_full_name()} | كود: {obj.id} | قومي: {obj.national_id}"
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


class StudentForm(forms.ModelForm):
    class Meta:
        model = Student
        fields = [
            'academic_year', 'first_name', 'last_name', 'image',
            'national_id', 'nationality', 'gender', 'religion',
            'date_of_birth', 'birth_place', 'address', 'phone', 'whatsapp_number', 'mother_name', 'father_job',
            'grade', 'classroom', 'specialization', 'initial_status',
            'registration_number', 'enrollment_notes', 'is_application_fee_exempt', 'integration_status'
        ]
        widgets = {
            'academic_year': forms.Select(attrs={'class': 'form-select'}),
            'first_name': forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'الاسم الأول'}),
            'last_name': forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'اسم العائلة'}),
            'grade': forms.Select(attrs={'class': 'form-select'}),
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
            'birth_place': forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'محل الميلاد (المحافظة)'}),
            'address': forms.Textarea(attrs={'class': 'form-control', 'placeholder': 'العنوان بالتفصيل', 'rows': 1}),
            'phone': forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'رقم التليفون'}),
            'whatsapp_number': forms.TextInput(attrs={
                'class': 'form-control',
                'placeholder': 'رقم الواتساب',
                'inputmode': 'numeric',
                'oninput': "this.value = this.value.replace(/[^0-9]/g, '').slice(0, 11)"
            }),
            'father_job': forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'أدخل وظيفة الأب (اختياري)'}),
            'mother_name': forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'اسم الأم بالكامل'}),
            'classroom': forms.Select(attrs={'class': 'form-select'}),
            'specialization': forms.Select(attrs={'class': 'form-select'}),
            'initial_status': forms.Select(attrs={'class': 'form-select bg-dark text-warning fw-bold'}),
            'registration_number': forms.TextInput(attrs={
                'class': 'form-control font-monospace fw-bold text-warning',
                'placeholder': 'رقم القيد الدفتري (أرقام فقط)',
                'inputmode': 'numeric',
                'oninput': "this.value = this.value.replace(/[^0-9]/g, '')",
            }),
            'enrollment_notes': forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'اكتب أي ملاحظات خاصة بقيد الطالب هنا...'}),
            'is_application_fee_exempt': forms.CheckboxInput(attrs={'class': 'form-check-input'}),
            'integration_status': forms.CheckboxInput(attrs={'class': 'form-check-input'}),
        }
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
            'birth_place': 'محل الميلاد',
            'address': 'العنوان',
            'phone': 'رقم التليفون',
            'whatsapp_number': 'رقم الواتساب',
            'mother_name': 'اسم الأم',
            'classroom': 'الفصل',
            'specialization': 'التخصص',
            'initial_status': 'حالة القيد عند فتح الملف',
            'registration_number': 'رقم القيد',
            'enrollment_notes': 'ملاحظات القيد',
            'is_application_fee_exempt': 'معافى من رسوم فتح الملف',
            'integration_status': 'طالب دمج',
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        years_queryset = AcademicYear.objects.all().order_by('-name')
        self.fields['academic_year'].queryset = years_queryset
        active_year = years_queryset.filter(is_active=True).first()
        if active_year:
            self.fields['academic_year'].initial = active_year
        for field_name in self.fields:
            if field_name not in ['first_name', 'last_name', 'academic_year', 'grade']:
                self.fields[field_name].required = False

    def clean_whatsapp_number(self):
        number = self.cleaned_data.get('whatsapp_number')
        if number:
            if not number.startswith('01') or not number.isdigit() or len(number) != 11:
                raise forms.ValidationError("برجاء إدخال رقم واتساب مصري صحيح (11 رقم يبدأ بـ 01)")
        return number

    def clean_registration_number(self):
        reg_num = self.cleaned_data.get('registration_number')
        if reg_num and not reg_num.isdigit():
            raise forms.ValidationError("رقم القيد يجب أن يتكون من أرقام فقط بدون أي حروف.")
        return reg_num