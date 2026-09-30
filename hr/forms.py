from django import forms
from .models import (
    Employee,
    Department,
    LeaveRequest,
    AttendanceRule,
    FingerprintLog,
    FinancialAdjustment,
    PublicHoliday,
    MissionRequest,
    PermissionRequest,
    PenaltyRecord,
)
from django.db.models import Q

# يجب أن يكون هذا الكلاس في الأيقونة الأولى من ملف forms.py
class StyledModelForm(forms.ModelForm):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        for field_name, field in self.fields.items():
            if isinstance(field.widget, forms.CheckboxInput):
                field.widget.attrs.update({'class': 'form-check-input'})
            else:
                field.widget.attrs.update({'class': 'form-control'})


class PenaltyRecordForm(StyledModelForm):
    class Meta:
        model = PenaltyRecord
        fields = ['employee', 'date', 'penalty_type', 'deduction_days', 'reason']
        widgets = {
            'date': forms.DateInput(attrs={'type': 'date'}),
            'reason': forms.Textarea(attrs={'rows': 4, 'placeholder': 'اكتب تفاصيل المخالفة والسبب هنا...'}),
        }
        labels = {
            'employee': 'الموظف',
            'date': 'تاريخ توقيع الجزاء',
            'penalty_type': 'نوع الجزاء',
            'deduction_days': 'عدد أيام الخصم',
            'reason': 'سبب الجزاء وتفاصيله',
        }
        help_texts = {
            'deduction_days': 'حدد عدد أيام الخصم حسب تقديرك لخطورة المخالفة (لا يوجد رقم ثابت مبرمج مسبقاً).',
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        if 'employee' in self.fields:
            self.fields['employee'].queryset = Employee.objects.filter(is_active=True).order_by('name')


class MissionRequestForm(StyledModelForm):
    class Meta:
        model = MissionRequest
        fields = ['employee', 'start_date', 'end_date', 'reason']
        widgets = {
            'start_date': forms.DateInput(attrs={'type': 'date'}),
            'end_date': forms.DateInput(attrs={'type': 'date'}),
            'reason': forms.Textarea(attrs={'rows': 3, 'placeholder': 'اكتب وجهة المأمورية وتفاصيلها هنا...'}),
        }
        labels = {
            'employee': 'الموظف (المكلف بالمأمورية)',
            'start_date': 'تاريخ البداية',
            'end_date': 'تاريخ النهاية',
            'reason': 'جهة وسبب المأمورية',
        }

    def clean(self):
        cleaned_data = super().clean()
        start = cleaned_data.get("start_date")
        end = cleaned_data.get("end_date")

        # 🛡️ التحقق من منطقية التواريخ للمأمورية
        if start and end and end < start:
            raise forms.ValidationError("خطأ: تاريخ نهاية المأمورية لا يمكن أن يكون قبل تاريخ بدايتها!")

        return cleaned_data


class PermissionRequestForm(StyledModelForm):
    class Meta:
        model = PermissionRequest
        fields = ['employee', 'date', 'departure_time', 'reason']
        widgets = {
            'date': forms.DateInput(attrs={'type': 'date'}),
            'departure_time': forms.TimeInput(attrs={'type': 'time'}), # 🟢 ويدجيت اختيار الوقت
            'reason': forms.Textarea(attrs={'rows': 3, 'placeholder': 'اكتب سبب الاستئذان (مثال: ظروف عائلية طارئة)...'}),
        }
        labels = {
            'employee': 'الموظف (طالب الإذن)',
            'date': 'تاريخ الإذن (يوم واحد)',
            'departure_time': 'وقت الخروج المصرّح به (بعد 2 ظهراً)', # 🟢 التسمية
            'reason': 'سبب الاستئذان',
        }

    def clean(self):
        """🛡️ التحقق الذكي: منع الموظف من تقديم أكثر من إذن واحد في نفس الشهر"""
        cleaned_data = super().clean()
        employee = cleaned_data.get("employee")
        date = cleaned_data.get("date")

        if employee and date:
            # فحص ما إذا كان لديه إذن سابق معتمد أو قيد الانتظار في نفس الشهر والسنة
            existing_permissions = PermissionRequest.objects.filter(
                employee=employee,
                date__year=date.year,
                date__month=date.month,
                status__in=['pending', 'approved']
            )

            # استثناء الطلب الحالي في حالة التعديل (Update)
            if self.instance and self.instance.pk:
                existing_permissions = existing_permissions.exclude(pk=self.instance.pk)

            if existing_permissions.exists():
                raise forms.ValidationError(
                    f"عذراً، هذا الموظف لديه طلب إذن مسجل مسبقاً خلال شهر ({date.strftime('%B %Y')}). الحد المسموح به هو إذن واحد فقط شهرياً!"
                )

        return cleaned_data



class EmployeeForm(StyledModelForm):
    class Meta:
        model = Employee
        fields = '__all__'
        labels = {
            'emp_id': 'كود البصمة الرقمي',
            'name': 'اسم الموظف بالكامل',
            'hire_date': 'تاريخ التعيين / المباشرة',  # 🟢 إضافة التسمية هنا
            'department': 'القسم',
            'attendance_rule': 'لائحة العمل المطبقة',
            'is_active': 'على رأس العمل (نشط)',
            'base_salary': 'الراتب الأساسي التعاقدي',

            # باقي التسميات كما هي...
            'is_insured': 'خاضع للتأمينات الاجتماعية؟',
            'insurance_number': 'الرقم التأميني للموظف',
            'insurance_basic_salary': 'الأجر الأساسي التأميني',
            'insurance_variable_allowance': 'البدلات التأمينية / الأجر المتغير',
            'insurance_deduction': 'قيمة الاستقطاع التأميني (حصة الموظف)',
            'annual_balance': 'رصيد الإجازات السنوية',
            'casual_balance': 'رصيد الإجازات العارضة',
            'sick_balance': 'رصيد الإجازات المرضية المتاحة',
            'hr_managers': 'مسؤولي الـ HR (صلاحية المتابعة)',
        }
        widgets = {
            'hr_managers': forms.SelectMultiple(attrs={'class': 'select2-multiple form-control'}),
            'hire_date': forms.DateInput(format='%Y-%m-%d', attrs={'type': 'date'}),
        }


class LeaveRequestForm(StyledModelForm):
    class Meta:
        model = LeaveRequest
        fields = ['employee', 'leave_type', 'start_date', 'end_date', 'reason']
        widgets = {
            'start_date': forms.DateInput(attrs={'type': 'date'}),
            'end_date': forms.DateInput(attrs={'type': 'date'}),
            'reason': forms.Textarea(attrs={'rows': 3, 'placeholder': 'اكتب سبب طلب الإجازة بالتفصيل...'}),
        }
        labels = {
            'employee': 'الموظف',
            'leave_type': 'نوع الإجازة',
            'start_date': 'تاريخ البدء',
            'end_date': 'تاريخ الانتهاء',
            'reason': 'السبب / تفاصيل إضافية',
        }

    def clean(self):
        """التحقق من التواريخ ومن رصيد الإجازات المتبقي ومنع التداخل"""
        cleaned_data = super().clean()
        employee = cleaned_data.get("employee")
        leave_type = cleaned_data.get("leave_type")
        start = cleaned_data.get("start_date")
        end = cleaned_data.get("end_date")

        # 1. التحقق من منطقية التواريخ
        if start and end and end < start:
            raise forms.ValidationError("خطأ: تاريخ نهاية الإجازة لا يمكن أن يكون قبل تاريخ بدايتها!")

        if employee and leave_type and start and end:
            # 🟢 2. منع تداخل الإجازات (التحقق من عدم وجود إجازة أخرى في نفس الفترة)
            overlapping_requests = LeaveRequest.objects.filter(
                employee=employee,
                status__in=['pending', 'approved']
            ).filter(
                Q(start_date__lte=end) & Q(end_date__gte=start)
            )

            # استثناء الطلب الحالي في حالة التعديل
            if self.instance and self.instance.pk:
                overlapping_requests = overlapping_requests.exclude(pk=self.instance.pk)

            if overlapping_requests.exists():
                raise forms.ValidationError("عذراً، يوجد طلب إجازة آخر مسجل لك يتقاطع مع هذه التواريخ.")

            # 3. التحقق الذكي من الرصيد المتاح للموظف
            duration = (end - start).days + 1

            if leave_type == 'annual' and duration > employee.annual_balance:
                raise forms.ValidationError(
                    f"خطأ: رصيد الإجازات السنوية للموظف غير كافٍ! الرصيد المتاح: {employee.annual_balance} يوم، والمدة المطلوبة: {duration} يوم."
                )
            elif leave_type == 'casual' and duration > employee.casual_balance:
                raise forms.ValidationError(
                    f"خطأ: رصيد الإجازات العارضة للموظف غير كافٍ! الرصيد المتاح: {employee.casual_balance} يوم، والمدة المطلوبة: {duration} يوم."
                )
            elif leave_type == 'sick' and duration > employee.sick_balance:
                raise forms.ValidationError(
                    f"خطأ: رصيد الإجازات المرضية للموظف غير كافٍ! الرصيد المتاح: {employee.sick_balance} يوم، والمدة المطلوبة: {duration} يوم."
                )
            elif leave_type == 'exceptional':
                # 🟢 الإجازة الاستثنائية تُقبل فوراً بدون فحص أو خصم من الأرصدة
                pass

        return cleaned_data



# 3. نموذج قواعد الحضور (معدل ومتوافق تماماً مع المناوبات واللوائح المرنة)
class AttendanceRuleForm(StyledModelForm):
    class Meta:
        model = AttendanceRule
        fields = '__all__'
        widgets = {
            'work_start_time': forms.TimeInput(attrs={'type': 'time'}),
            'work_end_time': forms.TimeInput(attrs={'type': 'time'}),
        }
        labels = {
            'name': 'اسم قاعدة الدوام (مثلاً: دوام صباحي، مرن)',
            'shift_type': 'نوع الوردية/الدوام',
            'work_start_time': 'موعد الحضور الرسمي (للدوام الثابت)',
            'work_end_time': 'موعد الانصراف الرسمي (للدوام الثابت)',
            'target_work_hours': 'عدد الساعات المستهدفة يومياً (للصنف المرن)',
            'grace_period': 'فترة السماح (بالدقائق)',
            'max_late_allowed_minutes': 'أقصى مدة تأخير مسموح بها بالدقائق قبل اعتباره غياب نصف يوم',
            'late_deduction_multiplier': 'معامل خصم التأخير (ساعة التأخير بـ X ساعة)',
            'overtime_multiplier_normal': 'معامل الإضافي في الأيام العادية',
            'overtime_multiplier_weekend': 'معامل الإضافي في العطلات والإجازات',
            'absent_deduction_days': 'جزاء الغياب بدون إذن (اليوم بـ X يوم من الراتب)',
        }
        help_texts = {
            'shift_type': 'اختر نوع الدوام (ثابت بمواعيد صارمة، مرن بساعات مستهدفة، أو مفتوح بدون قيود).',
            'late_deduction_multiplier': 'مثال: إذا كانت ساعة التأخير تحسب بساعتين خصم، اكتب 2.0',
            'absent_deduction_days': 'مثال: يوم الغياب يخصم بيومين، اكتب 2.0',
        }


# 4. نموذج الإدارة
class DepartmentForm(StyledModelForm):
    class Meta:
        model = Department
        fields = ['name', 'manager']


# 5. نموذج رفع ملف البصمة
class UploadAttendanceForm(forms.Form):
    file = forms.FileField(
        label="ملف بيانات البصمة",
        help_text="يرجى رفع ملف بصيغة CSV أو Excel المستخرج من جهاز البصمة.",
        widget=forms.FileInput(attrs={'class': 'form-control-file', 'accept': '.csv, .xlsx, .xls'})
    )
    device_id = forms.CharField(
        max_length=50,
        required=False,
        label="معرف الجهاز (اختياري)",
        widget=forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'مثلاً: جهاز الفرع الرئيسي'})
    )


class FinancialAdjustmentForm(StyledModelForm):
    class Meta:
        model = FinancialAdjustment
        fields = ['employee', 'date', 'adjustment_type', 'amount', 'reason']
        widgets = {
            'date': forms.DateInput(attrs={'type': 'date'}),
            'reason': forms.Textarea(attrs={'rows': 3, 'placeholder': 'مثال: إعفاء من جزاء التأخير بناءً على تعليمات السيد رئيس مجلس الإدارة...'}),
        }
        labels = {
            'employee': 'الموظف',
            'date': 'تاريخ التسوية (يحدد شهر الصرف)',
            'adjustment_type': 'نوع الحركة المالية',
            'amount': 'المبلغ بالجنيه',
            'reason': 'سبب التسوية والاعتماد',
        }


class PublicHolidayForm(StyledModelForm):
    class Meta:
        model = PublicHoliday
        fields = ['name', 'start_date', 'end_date', 'notes']
        widgets = {
            'start_date': forms.DateInput(attrs={'type': 'date'}),
            'end_date': forms.DateInput(attrs={'type': 'date'}),
            'notes': forms.Textarea(attrs={'rows': 2, 'placeholder': 'ملاحظات اختيارية عن قرار الإجازة...'}),
        }
        labels = {
            'name': 'اسم العطلة / المناسبة',
            'start_date': 'تبدأ من يوم',
            'end_date': 'تنتهي في يوم',
        }