import datetime
from django import forms
from .models import Employee, Department, Leave

class DepartmentForm(forms.ModelForm):
    class Meta:
        model = Department
        fields = '__all__'
        widgets = {
            'description': forms.Textarea(attrs={'rows': 3, 'class': 'form-control'}),
        }

class EmployeeForm(forms.ModelForm):
    class Meta:
        model = Employee
        fields = '__all__'
        widgets = {
            'contract_date': forms.DateInput(attrs={'type': 'date', 'class': 'form-control'}),
        }

class UploadAttendanceForm(forms.Form):
    # إنشاء قوائم لاختيار الشهر والسنة
    MONTHS = [(i, str(i)) for i in range(1, 13)]
    current_year = datetime.date.today().year
    YEARS = [(i, str(i)) for i in range(current_year - 2, current_year + 3)]

    month = forms.ChoiceField(choices=MONTHS, label="شهر الاستحقاق", widget=forms.Select(attrs={'class': 'form-select'}))
    year = forms.ChoiceField(choices=YEARS, label="سنة الاستحقاق", widget=forms.Select(attrs={'class': 'form-select'}))
    
    file = forms.FileField(
        label="ملف إكسيل البصمة",
        widget=forms.FileInput(attrs={'class': 'form-control', 'accept': '.xlsx, .xls'})
    )
    
    
class LeaveForm(forms.ModelForm):
    class Meta:
        model = Leave
        fields = ['employee', 'leave_type', 'start_date', 'end_date', 'days', 'notes']
        widgets = {
            'start_date': forms.DateInput(attrs={'type': 'date', 'class': 'form-control'}),
            'end_date': forms.DateInput(attrs={'type': 'date', 'class': 'form-control'}),
            'notes': forms.Textarea(attrs={'rows': 2, 'class': 'form-control'}),
        }