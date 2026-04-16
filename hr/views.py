from django.shortcuts import render, redirect
from django.contrib import messages
from .models import Employee, DailyAttendance, LeaveRequest
from .forms import UploadAttendanceForm, EmployeeForm, LeaveRequestForm # تأكد من مطابقة الأسماء هنا

# تأكد أن اسم هذه الدالة مطابق تماماً لما في urls.py
def upload_and_process_attendance(request):
    """الفيو المسؤول عن رفع ومعالجة ملف البصمة"""
    if request.method == 'POST':
        form = UploadAttendanceForm(request.POST, request.FILES)
        if form.is_valid():
            # منطق المعالجة (Pandas) الذي كتبناه سابقاً يوضع هنا
            messages.success(request, "تم رفع الملف بنجاح")
            return redirect('attendance_list')
    else:
        form = UploadAttendanceForm()
    return render(request, 'hr/upload.html', {'form': form})

def employee_list(request):
    employees = Employee.objects.all()
    return render(request, 'hr/employee_list.html', {'employees': employees})

def attendance_list(request):
    attendance = DailyAttendance.objects.all().order_by('-date')
    return render(request, 'hr/attendance_list.html', {'attendance': attendance})

def leave_list(request):
    leaves = LeaveRequest.objects.all()
    return render(request, 'hr/leave_list.html', {'leaves': leaves})

def leave_request_view(request):
    if request.method == 'POST':
        form = LeaveRequestForm(request.POST)
        if form.is_valid():
            form.save()
            return redirect('leave_list')
    else:
        form = LeaveRequestForm()
    return render(request, 'hr/leave_form.html', {'form': form})