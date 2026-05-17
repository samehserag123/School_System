from django import forms
from .models import Employee, Department, LeaveRequest, AttendanceRule, FingerprintLog

class EmployeeForm(forms.ModelForm):
    class Meta:
        model = Employee
        # خيار 'all' بيخلي الفورم يسحب كل حقول الموظف تلقائياً (الاسم، الوظيفة، الهاتف، إلخ)
        fields = '__all__'
        
        # يمكنك تخصيص عناوين الحقول بالعربي لتظهر بشكل احترافي في صفحة الـ HTML
        labels = {
            'name': 'اسم الموظف بالكامل',
            'job_title': 'المسمى الوظيفي',
            'department': 'القسم',
            'phone': 'رقم الهاتف',
            'email': 'البريد الإلكتروني',
            'hire_date': 'تاريخ التعيين',
            'salary': 'الراتب الأساسي',
            'attendance_id': 'رقم كارت البصمة (الماكينة)',
        }
        
        # تحويل حقول التواريخ إلى تقويم تفاعلي بدل خانة نصية عادية
        widgets = {
            'hire_date': forms.DateInput(attrs={'type': 'date'}),
        }

class StyledModelForm(forms.ModelForm):
    """كلاس أساسي لإضافة تنسيق Bootstrap لكل الحقول تلقائياً مع استثناء الـ Checkboxes"""
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        for field_name, field in self.fields.items():
            # إذا كان الحقل مربع اختيار، نمنحه كلاس مخصص لـ Bootstrap بدلاً من تشويهه بـ form-control
            if isinstance(field.widget, forms.CheckboxInput):
                field.widget.attrs.update({'class': 'form-check-input'})
            else:
                field.widget.attrs.update({'class': 'form-control'})

# 1. نموذج الموظف


# 2. نموذج طلب الإجازة (الذكي)
class LeaveRequestForm(StyledModelForm):
    class Meta:
        model = LeaveRequest
        fields = ['employee', 'leave_type', 'start_date', 'end_date']
        widgets = {
            'start_date': forms.DateInput(attrs={'type': 'date'}),
            'end_date': forms.DateInput(attrs={'type': 'date'}),
        }

    def clean(self):
        """التحقق من التواريخ ومن رصيد الإجازات المتبقي للموظف"""
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

        return cleaned_data

# 3. نموذج قواعد الحضور (تمت تهيئته ليدعم الحقول الحسابية الجديدة وأيام الأسبوع)
class AttendanceRuleForm(StyledModelForm):
    class Meta:
        model = AttendanceRule
        fields = '__all__'
        widgets = {
            'work_start_time': forms.TimeInput(attrs={'type': 'time'}),
            'work_end_time': forms.TimeInput(attrs={'type': 'time'}),
        }
        help_texts = {
            'deduction_multiplier': 'مثال: إذا كانت ساعة التأخير تحسب بساعتين خصم، اكتب 2.0',
            'absent_deduction_days': 'مثال: يوم الغياب يخصم بيوم ونصف، اكتب 1.5',
            'requires_fingerprint': 'قم بإلغاء التحديد للموظفين المستثنين من نظام البصمة (كالإدارة العليا).',
        }

# 4. نموذج الإدارة
class DepartmentForm(StyledModelForm):
    class Meta:
        model = Department
        fields = ['name', 'manager'] # أضفنا حقل المدير ليتطابق مع التحديث الأخير للموديل

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