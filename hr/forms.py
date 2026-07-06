from django import forms
from .models import Employee, Department, LeaveRequest, AttendanceRule, FingerprintLog

class StyledModelForm(forms.ModelForm):
    """كلاس أساسي لإضافة تنسيق Bootstrap لكل الحقول تلقائياً مع استثناء الـ Checkboxes"""
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        for field_name, field in self.fields.items():
            if isinstance(field.widget, forms.CheckboxInput):
                field.widget.attrs.update({'class': 'form-check-input'})
            else:
                field.widget.attrs.update({'class': 'form-control'})


# 1. نموذج الموظف المطور (يشمل الحقول التأمينية والأرصدة الجديدة)
class EmployeeForm(StyledModelForm):
    class Meta:
        model = Employee
        fields = '__all__'
        labels = {
            'emp_id': 'كود البصمة الرقمي',
            'name': 'اسم الموظف بالكامل',
            'department': 'القسم',
            'attendance_rule': 'لائحة العمل المطبقة',
            'is_active': 'على رأس العمل (نشط)',
            'base_salary': 'الراتب الأساسي التعاقدي',
            
            # حقول التأمينات الاجتماعية الجديدة
            'is_insured': 'خاضع للتأمينات الاجتماعية؟',
            'insurance_number': 'الرقم التأميني للموظف',
            'insurance_basic_salary': 'الأجر الأساسي التأميني',
            'insurance_variable_allowance': 'البدلات التأمينية / الأجر المتغير',
            'insurance_deduction': 'قيمة الاستقطاع التأميني (حصة الموظف)',
            
            # أرصدة الإجازات المتاحة
            'annual_balance': 'رصيد الإجازات السنوية',
            'casual_balance': 'رصيد الإجازات العارضة',
            'sick_balance': 'رصيد الإجازات المرضية المتاحة',
        }


# 2. نموذج طلب الإجازة (الذكي - مع إضافة فحص الرصيد المرضي)
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
        """التحقق من التواريخ ومن رصيد الإجازات المتبقي للموظف بناءً على الأرصدة الجديدة"""
        cleaned_data = super().clean()
        employee = cleaned_data.get("employee")
        leave_type = cleaned_data.get("leave_type")
        start = cleaned_data.get("start_date")
        end = cleaned_data.get("end_date")

        # 1. التحقق من منطقية التواريخ
        if start and end and end < start:
            raise forms.ValidationError("خطأ: تاريخ نهاية الإجازة لا يمكن أن يكون قبل تاريخ بدايتها!")

        # 2. التحقق الذكي من الرصيد المتاح للموظف في قاعدة البيانات
        if employee and leave_type and start and end:
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