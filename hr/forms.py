from django import forms
from .models import Employee, Department, LeaveRequest, AttendanceRule, FingerprintLog

class StyledModelForm(forms.ModelForm):
    """كلاس أساسي لإضافة تنسيق Bootstrap لكل الحقول تلقائياً"""
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        for field_name, field in self.fields.items():
            field.widget.attrs.update({'class': 'form-control'})

# 1. نموذج الموظف
class EmployeeForm(StyledModelForm):
    class Meta:
        model = Employee
        fields = '__all__'
        widgets = {
            'is_active': forms.CheckboxInput(attrs={'class': 'form-check-input ml-2'}),
        }
        help_texts = {
            'emp_id': 'رقم الموظف كما هو مسجل في جهاز البصمة.',
        }

# 2. نموذج طلب الإجازة (مع منقي تاريخ)
class LeaveRequestForm(StyledModelForm):
    class Meta:
        model = LeaveRequest
        fields = ['employee', 'leave_type', 'start_date', 'end_date']
        widgets = {
            'start_date': forms.DateInput(attrs={'type': 'date'}),
            'end_date': forms.DateInput(attrs={'type': 'date'}),
        }

    def clean(self):
        """التحقق من أن تاريخ النهاية بعد تاريخ البداية"""
        cleaned_data = super().clean()
        start = cleaned_data.get("start_date")
        end = cleaned_data.get("end_date")
        if start and end and end < start:
            raise forms.ValidationError("خطأ: تاريخ نهاية الإجازة لا يمكن أن يكون قبل تاريخ بدايتها!")
        return cleaned_data

# 3. نموذج قواعد الحضور
class AttendanceRuleForm(StyledModelForm):
    class Meta:
        model = AttendanceRule
        fields = '__all__'
        widgets = {
            'work_start_time': forms.TimeInput(attrs={'type': 'time'}),
            'work_end_time': forms.TimeInput(attrs={'type': 'time'}),
        }

# 4. نموذج الإدارة
class DepartmentForm(StyledModelForm):
    class Meta:
        model = Department
        fields = ['name']

# 5. نموذج رفع ملف البصمة (المبهر)
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
        widget=forms.TextInput(attrs={'placeholder': 'مثلاً: جهاز الفرع الرئيسي'})
    )