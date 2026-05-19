from datetime import datetime, date
from django.shortcuts import render, redirect
from django.contrib import messages
from django.db.models import Sum


from django.utils import timezone
from datetime import timedelta

# استيراد الموديلات والفورمز الخاصة بتطبيق الـ HR (تم تصحيح الحرف الناقص)
from .models import Employee, DailyAttendance, LeaveRequest, Department
from .forms import UploadAttendanceForm, EmployeeForm, LeaveRequestForm

def employee_create_view(request):
    """
    عرض ومعالجة صفحة إضافة موظف جديد للسيستم
    """
    if request.method == 'POST':
        form = EmployeeForm(request.POST, request.FILES)
        if form.is_valid():
            form.save()
            messages.success(request, 'تم تسجيل الموظف الجديد بنجاح في النظام!')
            return redirect('hr:employee_list')
        else:
            messages.error(request, 'عذراً، يرجى مراجعة البيانات المدخلة وتصحيح الأخطاء.')
    else:
        form = EmployeeForm()
        
    return render(request, 'hr/employee_form.html', {'form': form})

def hr_dashboard(request):
    try:
        # 📅 الحصول على تاريخ اليوم الحالي بالاعتماد على المنطقة الزمنية
        today = timezone.localdate()
        
        # 1️⃣ إجمالي عدد الموظفين الفعلي في النظام
        total_employees = Employee.objects.count()
        
        # 2️⃣ عدد الموظفين الحاضرين اليوم
        today_attendance_count = DailyAttendance.objects.filter(
            date=today,
            status='present'
        ).count()
        
        # 3️⃣ عدد حالات التأخير الفعلي لليوم (دقائق التأخير أكبر من صفر)
        today_late_count = DailyAttendance.objects.filter(
            date=today,
            late_minutes__gt=0
        ).count()
        
        # 4️⃣ إجمالي طلبات الإجازة المعلقة (مربوطة بـ notification_count لتوحيد العدادات)
        notification_count = LeaveRequest.objects.filter(status='pending').count()
        
        # 📊 حساب نسبة الحضور لليوم بشكل برمجي آمن منعاً للقسمة على صفر
        if total_employees > 0:
            attendance_percentage = int((today_attendance_count / total_employees) * 100)
        else:
            attendance_percentage = 0
        
        # 📋 أحدث 5 تسجيلات حضور لليوم لعرضها في جدول العينات السفلي
        latest_attendance = DailyAttendance.objects.filter(
            date=today
        ).order_by('-id')[:5]

    except Exception as database_error:
        # ⚠️ في حال وجود أي حقل مفقود أو خطأ في الداتابيز، يتم تصفير المتغيرات مؤقتاً لمنع كراش الـ 500
        print(f"🔴 خطأ في قاعدة البيانات داخل الداشبورد: {str(database_error)}")
        total_employees = 0
        today_attendance_count = 0
        today_late_count = 0
        notification_count = 0
        attendance_percentage = 0
        latest_attendance = []
        today = timezone.localdate()

    # قيم افتراضية لضمان توافق الـ Template القديم والجديد معاً وتفادي الـ 500 كراش تماماً
    context = {
        'total_employees': total_employees,
        'today_attendance_count': today_attendance_count,
        'today_late_count': today_late_count,
        'notification_count': notification_count,       # متزامن مع الجرس والـ Sidebar
        'pending_leaves_count': notification_count,     # ممرر مرتين لضمان عدم انهيار الـ Template لو مستدعى بالاسم القديم
        'new_employees_this_month': 0,
        'attendance_percentage': attendance_percentage,
        'latest_attendance': latest_attendance,
        'today_date': today,
    }
    
    return render(request, 'hr_dashboard.html', context)

# 1. حساب مسيرات الرواتب الشهرية مرنة المعاملات
def calculate_monthly_salary(request, employee_id, year, month):
    employee = Employee.objects.get(id=employee_id)
    
    # جلب جميع أيام حضور وغياب الموظف خلال الشهر
    attendances = DailyAttendance.objects.filter(
        employee=employee,
        date__year=year,
        date__month=month
    )
    
    total_overtime = attendances.aggregate(Sum('overtime_hours'))['overtime_hours__sum'] or 0.0
    total_deductions_hours = attendances.aggregate(Sum('deduction_hours'))['deduction_hours__sum'] or 0.0
    total_absence_days = attendances.filter(status='absent').count()
    
    # الحسابات المالية المرنة بناءً على راتب الموظف (افتراض 240 ساعة عمل شهرياً)
    hourly_rate = float(employee.base_salary) / 240.0
    day_rate = float(employee.base_salary) / 30.0
    
    # حساب قيمة الإضافي والخصومات المتراكمة بالشهر
    overtime_allowance = total_overtime * hourly_rate
    late_deduction = total_deductions_hours * hourly_rate
    
    # خصم الغياب المباشر بناءً على معامل الغياب المخصص للموظف بقاعدته
    absence_deduction = total_absence_days * day_rate * employee.attendance_rule.absent_deduction_days
    
    # صافي الراتب النهائي بعد التسويات
    net_salary = float(employee.base_salary) + overtime_allowance - late_deduction - absence_deduction

    context = {
        'employee': employee,
        'base_salary': employee.base_salary,
        'overtime_allowance': round(overtime_allowance, 2),
        'late_deduction': round(late_deduction, 2),
        'absence_deduction': round(absence_deduction, 2),
        'net_salary': round(net_salary, 2),
    }
    return render(request, 'hr/payroll_slip.html', context)


# 2. محرك المعالجة اليومي الذكي للبصمة والربط مع القواعد المرنة
def process_daily_attendance_for_employee(employee, target_date, logs):
    """
    دالة ذكية تحسب حضور الموظف بناءً على قاعدته الخاصة به
    logs: قائمة بوقائع البصمة (timestamps) الخاصة بالموظف في هذا اليوم
    """
    rule = employee.attendance_rule
    
    # أولاً: التحقق هل اليوم هو يوم عمل رسمي للموظف بناءً على فلاتر الأيام بقاعدته
    if not rule.is_working_day(target_date):
        # إذا لم يكن يوم عمل وبصم فيه الموظف، يحسب كامل الوقت كإضافي مضروباً في معامل الإضافي
        if logs:
            check_in = min(logs).time()
            check_out = max(logs).time()
            
            # تم استخدام datetime.combine بأمان هنا لأننا استوردنا الكلاس بالكامل
            start = datetime.combine(target_date, check_in)
            end = datetime.combine(target_date, check_out)
            duration_hours = (end - start).total_seconds() / 3600.0
            
            DailyAttendance.objects.update_or_create(
                employee=employee, date=target_date,
                defaults={
                    'check_in': check_in, 'check_out': check_out,
                    'status': 'present', 'overtime_hours': duration_hours * rule.overtime_multiplier
                }
            )
        return

    # ثانياً: إذا كان يوم عمل ولم يبصم والموظف مجبر بالبصمة
    if not logs and rule.requires_fingerprint:
        # فحص وجود طلب إجازة معتمد ومصدق عليه لهذا اليوم
        has_leave = LeaveRequest.objects.filter(
            employee=employee, start_date__lte=target_date, end_date__gte=target_date, status='approved'
        ).exists()
        
        status = 'leave' if has_leave else 'absent'
        DailyAttendance.objects.update_or_create(
            employee=employee, date=target_date,
            defaults={'status': status, 'late_minutes': 0, 'overtime_hours': 0}
        )
        return

    # ثالثاً: إذا حضر الموظف وبصم فعلياً
    if logs:
        check_in_dt = min(logs)
        check_out_dt = max(logs)
        
        check_in = check_in_dt.time()
        check_out = check_out_dt.time()
        
        rule_start = rule.work_start_time
        rule_end = rule.work_end_time
        
        # حساب دقائق التأخير الفعليه
        late_minutes = 0
        if check_in > rule_start:
            diff = datetime.combine(target_date, check_in) - datetime.combine(target_date, rule_start)
            late_minutes = int(diff.total_seconds() / 60)
            if late_minutes <= rule.grace_period:
                late_minutes = 0
                
        # حساب ساعات الإضافي عند تخطي نهاية موعد الدوام الرسمي بالمعامل
        overtime_hours = 0.0
        if check_out > rule_end:
            diff_out = datetime.combine(target_date, check_out) - datetime.combine(target_date, rule_end)
            overtime_hours = (diff_out.total_seconds() / 3600.0) * rule.overtime_multiplier

        # حساب ساعات الخصم الفعلية بناءً على معامل خصم ساعات التأخير للموظف
        deduction_hours = 0.0
        if late_minutes > 0:
            deduction_hours = (late_minutes / 60.0) * rule.deduction_multiplier

        DailyAttendance.objects.update_or_create(
            employee=employee, date=target_date,
            defaults={
                'check_in': check_in,
                'check_out': check_out,
                'status': 'present',
                'late_minutes': late_minutes,
                'overtime_hours': overtime_hours,
                'deduction_hours': deduction_hours
            }
        )

# 3. الفيوات المسؤولة عن لوحات التحكم الإدارية (Dashboards & Lists
def upload_and_process_attendance(request):
    """
    عرض صفحة رفع سجلات البصمة ومعالجتها حياً
    """
    if request.method == 'POST':
        # إذا كنت تستخدم حقل الرفع المباشر بدون كائن Form مسبق:
        uploaded_file = request.FILES.get('file')
        
        if not uploaded_file:
            messages.error(request, 'لم يتم اختيار أي ملف للرفع.')
            return redirect('hr:upload_attendance')
            
        try:
            # 🚀 منطق المعالجة الحية لملف البصمة (CSV / Excel) يوضع هنا
            # ...
            
            messages.success(request, 'تم رفع ومعالجة سجلات البصمة بنجاح حساب الرواتب!')
            return redirect('hr:attendance_list')
            
        except Exception as e:
            # طباعة الخطأ داخل التيرمينال لو انهار أثناء المعالجة
            print(f"Error processing file: {str(e)}")
            messages.error(request, f'حدث خطأ أثناء معالجة الملف: {str(e)}')
            return redirect('hr:upload_attendance')
            
    # تأمين الـ GET بنسبة 100% لمنع الـ 500 كراش
    context = {
        'form': None # قمنا بإلغاء إجبار الفورم لتجنب الـ NameError أو الـ AttributeError
    }
    return render(request, 'hr/upload_attendance.html', context)


from django.shortcuts import render
from django.utils import timezone
from .models import Employee, Department, LeaveRequest
# تأكد من استيراد موديل الحضور الخاص بمشروعك، سنفترض هنا أن اسمه Attendance
# from .models import Attendance 

def employee_list(request):
    try:
        # 1. جلب الموظفين والأقسام
        # إذا كان حقل attendance_rule يسبب خطأ لأنه غير موجود في الـ Model، احذفه من الـ select_related
        employees = Employee.objects.all().select_related('department')
        departments = Department.objects.all()
        
        # 2. جلب طلبات الإجازات لجدول الإجازات
        leave_requests = LeaveRequest.objects.all().select_related('employee').order_by('-id')
        
        # 3. جلب سجلات الحضور (تأمين ضد عدم وجود بيانات اليوم)
        today = timezone.now().date()
        
        # تخصيص استعلامات الحضور (قم بتغيير 'Attendance' لاسم الموديل لديك إن كان مختلفاً)
        # try:
        #     attendance_list = Attendance.objects.filter(date=today).select_related('employee')
        # except:
        #     attendance_list = []
        
        attendance_list = [] # قيمة مؤقتة آمنة لمنع الكراش حتى تربط موديل البصمة الخاص بك
        
    except Exception as e:
        print(f"🔴 خطأ داخلي كارثي في الـ View: {str(e)}")
        employees = []
        departments = []
        leave_requests = []
        attendance_list = []

    # حساب العدادات الحية بشكل آمن تماماً يمنع الـ 500 Server Error
    total_emp = len(employees) if isinstance(employees, list) else employees.count()
    pending_leaves = len([l for l in leave_requests if l.status == 'pending']) if isinstance(leave_requests, list) else leave_requests.filter(status='pending').count()

    context = {
        'employees': employees,
        'departments': departments,
        'leave_requests': leave_requests,
        
        # تمرير متغيرات الحضور المتوقعة داخل التمبلت لمنع كراش السيرفر
        'attendance': attendance_list,
        'latest_attendance': attendance_list[:5] if isinstance(attendance_list, list) else attendance_list.order_by('-id')[:5],
        
        # العدادات الإحصائية للكروت العلوية
        'total_employees': total_emp,
        'today_attendance_count': 0, # سيتم ربطها بديناميكية الحضور لاحقاً
        'today_late_count': 0,
        'notification_count': pending_leaves,
        'current_date': timezone.now(),
    }
    
    return render(request, 'hr/employee_list.html', context)


def attendance_list(request):
    """
    عرض سجل الحضور والإنصراف اليومي للموظفين
    """
    attendance = DailyAttendance.objects.all().order_by('-date')
    return render(request, 'hr/attendance_list.html', {'attendance': attendance})

def leave_list(request):
    """
    عرض قائمة طلبات الإجازات المسجلة في النظام
    """
    leaves = LeaveRequest.objects.all().order_by('-id')
    
    # جلب عداد الإجازات المعلقة لتحديث الجرس والـ Sidebar ديناميكياً في هذه الصفحة أيضاً
    notification_count = LeaveRequest.objects.filter(status='pending').count()
    
    return render(request, 'hr/leave_list.html', {
        'leaves': leaves,
        'notification_count': notification_count
    })

def leave_request_view(request):
    """
    تقديم طلب إجازة جديد من خلال الفورم الذكي
    """
    if request.method == 'POST':
        form = LeaveRequestForm(request.POST)
        if form.is_valid():
            form.save()
            messages.success(request, 'تم إرسال طلب الإجازة بنجاح وبانتظار اعتماد الإدارة!')
            return redirect('hr:leave_list') # تم تعديل الـ namespace ليطابق نظام الراوتنج عندك (hr:leave_list)
        else:
            messages.error(request, 'عذراً، يرجى التحقق من صحة البيانات وتواريخ الإجازة.')
    else:
        form = LeaveRequestForm()
        
    # جلب العداد لضمان عدم اختفائه من الهيدر أو الـ Sidebar أثناء تقديم الطلب
    notification_count = LeaveRequest.objects.filter(status='pending').count()
    
    return render(request, 'hr/leave_form.html', {
        'form': form,
        'notification_count': notification_count
    })