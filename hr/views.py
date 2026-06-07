from datetime import datetime, date, time, timedelta
from django.shortcuts import render, redirect
from django.contrib import messages
from django.db.models import Sum
import pandas as pd
from django.utils import timezone
# استيراد الموديلات والفورمز الخاصة بتطبيق الـ HR (تم تصحيح الحرف الناقص)
from .models import Employee, DailyAttendance, LeaveRequest, Department, AttendanceRule
from .forms import UploadAttendanceForm, EmployeeForm, LeaveRequestForm


def monthly_payroll_report(request):
    """
    نسخة محسنة فائقة السرعة لكشف الرواتب المجمع (استعلام واحد للداتابيز)
    """
    try:
        today = timezone.localdate()
        year = int(request.GET.get('year', today.year))
        month = int(request.GET.get('month', today.month))
        
        # 🚀 جلب الموظفين النشطين وترتيبهم
        employees = Employee.objects.filter(is_active=True).select_related('attendance_rule').order_by('name')
        
        # ⚡ الضربة القاضية للبطء: جلب كل سجلات الحضور للشهر ده في استعلام واحد فقط!
        all_attendances = DailyAttendance.objects.filter(date__year=year, date__month=month)
        
        # تحويل السجلات إلى قاموس مجمع في الذاكرة لتفادي ضرب الداتابيز جوه الـ Loop
        attendance_map = {}
        for att in all_attendances:
            if att.employee_id not in attendance_map:
                attendance_map[att.employee_id] = []
            attendance_map[att.employee_id].append(att)

        payroll_records = []
        total_company_base = 0.0
        total_company_overtime = 0.0
        total_company_deductions = 0.0
        total_company_net = 0.0

        for employee in employees:
            # جلب سجلات الموظف من الذاكرة مباشرة بدون أي Query جديد
            emp_attendances = attendance_map.get(employee.id, [])
            
            # حساب الإجماليات في الذاكرة (سريع جداً)
            total_overtime_hours = sum(float(a.overtime_hours or 0) for a in emp_attendances)
            total_deduction_hours = sum(float(a.deduction_hours or 0) for a in emp_attendances)
            total_absence_days = sum(1 for a in emp_attendances if a.status == 'absent')
            
            base_salary = float(employee.base_salary) if employee.base_salary else 0.0
            hourly_rate = base_salary / 240.0
            day_rate = base_salary / 30.0
            
            overtime_allowance = total_overtime_hours * hourly_rate
            late_deduction = total_deduction_hours * hourly_rate
            
            absent_multiplier = 1.0
            if employee.attendance_rule:
                absent_multiplier = float(employee.attendance_rule.absent_deduction_days)
                
            absence_deduction = total_absence_days * day_rate * absent_multiplier
            
            total_deductions = late_deduction + absence_deduction
            net_salary = base_salary + overtime_allowance - total_deductions
            
            total_company_base += base_salary
            total_company_overtime += overtime_allowance
            total_company_deductions += total_deductions
            total_company_net += net_salary
            
            payroll_records.append({
                'employee': employee,
                'base_salary': base_salary,
                'overtime_hours': total_overtime_hours,
                'overtime_allowance': round(overtime_allowance, 2),
                'deductions': round(total_deductions, 2),
                'net_salary': round(net_salary, 2),
            })
            
        context = {
            'payroll_records': payroll_records,
            'year': year,
            'month': month,
            'total_company_base': round(total_company_base, 2),
            'total_company_overtime': round(total_company_overtime, 2),
            'total_company_deductions': round(total_company_deductions, 2),
            'total_company_net': round(total_company_net, 2),
            'months_range': range(1, 13),
            'years_range': range(today.year - 2, today.year + 3),
        }
        return render(request, 'hr/payroll_report.html', context)
        
    except Exception as server_err:
        print(f"❌ خطأ كشف الرواتب المجمع السريع: {str(server_err)}")
        raise server_err

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


def process_daily_attendance_for_employee(employee, target_date, logs):
    """
    محرك فني فائق الذكاء لمعالجة حركات البصمة لليوم المستهدف بناءً على طبيعة لائحة الموظف:
    ثابت (Fixed)، مرن (Flexible)، أو مفتوح (Open).
    """
    rule = employee.attendance_rule
    
    # 1. فحص وجود طلب إجازة معتمد ومصدق عليه في هذا اليوم مسبقاً
    has_approved_leave = LeaveRequest.objects.filter(
        employee=employee, 
        start_date__lte=target_date, 
        end_date__gte=target_date, 
        status='approved'
    ).exists()

    # 2. إذا كان اليوم هو عطلة أو إجازة رسمية للموظف بناءً على فلاتر اللائحة الخاصة به
    if not rule.is_working_day(target_date):
        if logs:
            # إذا بصم في يوم عطلته، تحسب ساعات تواجده بالكامل كإضافي بمضاعف العطلات الاستثنائي
            check_in = min(logs).time()
            check_out = max(logs).time()
            start_dt = datetime.combine(target_date, check_in)
            end_dt = datetime.combine(target_date, check_out)
            
            actual_hours = (end_dt - start_dt).total_seconds() / 3600.0
            overtime = actual_hours * rule.overtime_multiplier_weekend
            
            DailyAttendance.objects.update_or_create(
                employee=employee, date=target_date,
                defaults={
                    'check_in': check_in, 'check_out': check_out,
                    'status': 'holiday', 'actual_work_hours': actual_hours,
                    'overtime_hours': round(overtime, 2), 'late_minutes': 0, 'deduction_hours': 0.0
                }
            )
        else:
            # عطلة رسمية اعتيادية بدون حضور وبدون عقوبات أو تأثير على الراتب
            DailyAttendance.objects.update_or_create(
                employee=employee, date=target_date,
                defaults={'status': 'holiday', 'late_minutes': 0, 'overtime_hours': 0.0, 'deduction_hours': 0.0}
            )
        return

    # 3. إذا كان يوم عمل رسمي ولم يبصم الموظف نهائياً
    if not logs:
        if has_approved_leave:
            # غياب شرعي بسبب إجازة معتمدة ومسجلة في رصيده
            DailyAttendance.objects.update_or_create(
                employee=employee, date=target_date,
                defaults={'status': 'leave', 'late_minutes': 0, 'overtime_hours': 0.0, 'deduction_hours': 0.0, 'absence_deduction_days': 0.0}
            )
        else:
            # غياب غير مبرر بدون إذن مسبق (يتم تطبيق معامل جزاء خصم الغياب)
            DailyAttendance.objects.update_or_create(
                employee=employee, date=target_date,
                defaults={
                    'status': 'absent', 'late_minutes': 0, 'overtime_hours': 0.0, 'deduction_hours': 0.0,
                    'absence_deduction_days': rule.absent_deduction_days
                }
            )
        return

    # 4. إذا حضر وبصم الموظف بالفعل (بدء تفعيل فلاتر اللوائح المرنة والثابتة)
    check_in_dt = min(logs)
    check_out_dt = max(logs)
    check_in = check_in_dt.time()
    check_out = check_out_dt.time()
    
    actual_hours = (check_out_dt - check_in_dt).total_seconds() / 3600.0
    
    late_minutes = 0
    overtime_hours = 0.0
    deduction_hours = 0.0
    status = 'present'

    # أ. الحالة الأولى: تطبيق نظام الدوام الصارم/الثابت (Fixed Shift)
    if rule.shift_type == 'fixed':
        rule_start = rule.work_start_time
        rule_end = rule.work_end_time
        
        # حساب حركات التأخير الصباحية
        if check_in > rule_start:
            diff = datetime.combine(target_date, check_in) - datetime.combine(target_date, rule_start)
            late_minutes = int(diff.total_seconds() / 60)
            # إسقاط التأخير إذا كان يقع داخل النطاق الشرعي لفترة السماح بالشركة
            if late_minutes <= rule.grace_period:
                late_minutes = 0
        
        # إذا تجاوز التأخير الحد الأقصى المسموح به بالشركة، يتم تحويل الحالة لغياب نصف يوم تلقائياً
        if late_minutes > rule.max_late_allowed_minutes:
            status = 'half_day_absent'
            
        # حساب ساعات الإضافي بعد انتهاء مواعيد الدوام الرسمي المحدد للوردية
        if check_out > rule_end:
            diff_out = datetime.combine(target_date, check_out) - datetime.combine(target_date, rule_end)
            overtime_hours = (diff_out.total_seconds() / 3600.0) * rule.overtime_multiplier_normal

        # تطبيق معامل الخصم على ساعات التأخير الفعلية المحتسبة
        if late_minutes > 0:
            deduction_hours = (late_minutes / 60.0) * rule.late_deduction_multiplier

    # ب. الحالة الثانية: تطبيق نظام الدوام المرن بالكامل (Flexible Shift)
    elif rule.shift_type == 'flexible':
        target_hours = rule.target_work_hours
        if actual_hours < target_hours:
            # الموظف لم يكمل عدد ساعات الدوام المستهدفة اليوم، يحسب النقص كساعات خصم تأخير
            deficit_hours = target_hours - actual_hours
            deduction_hours = deficit_hours * rule.late_deduction_multiplier
            late_minutes = int(deficit_hours * 60)
        elif actual_hours > target_hours:
            # الموظف تخطى الساعات المستهدفة، يتم مكافأته بحساب الساعات الزائدة كإضافي معتمد
            surplus_hours = actual_hours - target_hours
            overtime_hours = surplus_hours * rule.overtime_multiplier_normal

    # ج. الحالة الثالثة: تطبيق نظام الدوام المفتوح (Open) للإدارة والمستشارين
    elif rule.shift_type == 'open':
        # لا توجد دقائق تأخير أو خصومات ساعات نهائياً، ويحسب الدوام كاملاً بشكل اعتيادي
        late_minutes = 0
        deduction_hours = 0.0
        overtime_hours = 0.0

    # 5. الحفظ الختامي المباشر وتحديث كشوفات الداتابيز
    DailyAttendance.objects.update_or_create(
        employee=employee, date=target_date,
        defaults={
            'check_in': check_in,
            'check_out': check_out,
            'status': status,
            'actual_work_hours': round(actual_work_hours, 2),
            'late_minutes': late_minutes,
            'overtime_hours': round(overtime_hours, 2),
            'deduction_hours': round(deduction_hours, 2),
            'absence_deduction_days': 0.0 # تم إلغاؤها لأنه حضر وبصم بالفعل
        }
    )


def upload_and_process_attendance(request):
    if request.method == 'POST' and request.FILES.get('file'):
        uploaded_file = request.FILES['file']
        
        try:
            # 1. قراءة الملف بحسب الامتداد
            if uploaded_file.name.endswith('.xlsx') or uploaded_file.name.endswith('.xls'):
                df = pd.read_excel(uploaded_file)
            elif uploaded_file.name.endswith('.csv'):
                df = pd.read_csv(uploaded_file)
            else:
                messages.error(request, "صيغة الملف غير مدعومة!")
                return redirect('hr:employee_list')

            # تنظيف أسماء الأعمدة من أي مسافات زائدة
            df.columns = df.columns.str.strip()
            
            # 2. تجميع البصمات: { (الموظف, التاريخ): [قائمة مواقيت البصمة] }
            logs_by_emp_and_date = {}
            distinct_dates = set()
            
            for index, row in df.iterrows():
                # 🎯 تعديل ذكي: جلب كود الموظف سواء العمود مكتوب بـ (AC-No.) أو (AC.No.)
                raw_emp_code = row.get('AC-No.', row.get('AC.No.', ''))
                raw_emp_code = str(raw_emp_code).strip()
                
                date_str = str(row.get('Date', '')).strip()
                
                if not raw_emp_code or raw_emp_code == 'nan' or not date_str or date_str == 'nan':
                    continue
                
                # تنظيف الكود من الكسر العشري لو الإكسيل قاريه Float (مثل 1.0 يحولها لـ 1)
                emp_code = raw_emp_code.split('.')[0]
                
                try:
                    ts = pd.to_datetime(date_str)
                    parsed_date = date(ts.year, ts.month, ts.day)
                    distinct_dates.add(parsed_date)
                except Exception as date_err:
                    print(f"❌ خطأ في التاريخ بالسطر {index}: {date_err}")
                    continue
                
                # 🎯 تعديل ذكي للبحث عن الموظف: يبحث في الـ emp_id أو الـ id التلقائي أو رقم البصمة
                employee = Employee.objects.filter(emp_id=emp_code, is_active=True).first()
                if not employee:
                    try:
                        # تجربة البحث بالـ ID الرقمي الصافي المباشر المتوافق مع الداتابيز
                        employee = Employee.objects.filter(id=int(emp_code), is_active=True).first()
                    except:
                        pass
                
                # إذا لم يجد الموظف بعد كل محاولات التطابقة، يتخطى السطر
                if not employee:
                    continue 

                if str(row.get('Absent', '')).strip().lower() == 'true':
                    continue
                
                clock_in_str = str(row.get('Clock In', '')).strip()
                clock_out_str = str(row.get('Clock Out', '')).strip()
                
                key = (employee, parsed_date)
                if key not in logs_by_emp_and_date:
                    logs_by_emp_and_date[key] = []
                
                for time_str in [clock_in_str, clock_out_str]:
                    if time_str and time_str != 'nan' and time_str != '':
                        try:
                            t_parsed = pd.to_datetime(time_str)
                            dt_combined = datetime.combine(parsed_date, time(t_parsed.hour, t_parsed.minute, t_parsed.second))
                            logs_by_emp_and_date[key].append(dt_combined)
                        except:
                            pass

            # 3. تشغيل محرك المعالجة الذكي لكل موظف حضر وبصم
            records_created = 0
            for (employee, target_date), logs in logs_by_emp_and_date.items():
                process_daily_attendance_for_employee(employee, target_date, logs)
                records_created += 1
            
            # 4. إدراج الغياب أو الإجازات تلقائياً لباقي الموظفين الذين لم يبصموا بالملف
            all_active_employees = Employee.objects.filter(is_active=True)
            for target_date in distinct_dates:
                for emp in all_active_employees:
                    if (emp, target_date) not in logs_by_emp_and_date:
                        process_daily_attendance_for_employee(emp, target_date, [])
            
            if records_created > 0:
                messages.success(request, f"تمت معالجة وتحديث الحسابات الماليّة لـ {records_created} سجل حضور وغياب بناءً على لوائح الشركة.")
            else:
                messages.warning(request, "تم قراءة الملف ولكن لم يتم مطابقة أي أكواد موظفين نشطين بحساباتهم.")
            
        except Exception as e:
            messages.error(request, f"حدث خطأ أثناء معالجة ملف البصمة: {str(e)}")
            
    return redirect('hr:employee_list')

def employee_list(request):
    try:
        # 1. جلب الموظفين والأقسام في استعلام واحد محسن
        employees_query = Employee.objects.all().select_related('department')
        employees = list(employees_query)  # تثبيت في الذاكرة سريعة القراءة
        departments = Department.objects.all()
        
        # 2. جلب طلبات الإجازات لجدول الإجازات وتثبيتها
        leave_requests_query = LeaveRequest.objects.all().select_related('employee').order_by('-id')
        leave_requests = list(leave_requests_query)  # تثبيت في الذاكرة
        
        # 3. جلب التاريخ المراد تصفيته من الـ GET Request (تاريخ اليوم كوضع افتراضي)
        date_param = request.GET.get('date')
        if date_param:
            try:
                target_date = pd.to_datetime(date_param).date()
            except:
                target_date = timezone.now().date()
        else:
            # إذا لم يقم المستخدم بالاختيار، نأخذ تاريخ آخر سجل تم رفعه لتسهيل رؤية الداتا الحية مباشرة
            last_record = DailyAttendance.objects.order_by('-date').first()
            target_date = last_record.date if last_record else timezone.now().date()
        
        # 4. تفعيل جلب السجلات الحقيقية من الموديل المعتمد DailyAttendance وتحويلها لقائمة فوراً
        attendance_query = DailyAttendance.objects.filter(date=target_date).select_related('employee')
        attendance_list = list(attendance_query)  # 🚀 الضربة القاضية للبطء: تحويل لقائمة بايثون لمنع ضرب الداتابيز مجدداً
        
    except Exception as e:
        print(f"🔴 خطأ داخلي في الـ View: {str(e)}")
        employees, departments, leave_requests, attendance_list = [], [], [], []
        target_date = timezone.now().date()

    # ⚡ الحساب الذكي الفائق السرعة داخل الذاكرة (0 استعلامات SQL إضافية)
    total_emp = len(employees)
    pending_leaves = sum(1 for l in leave_requests if l.status == 'pending')
    
    # حساب الحضور والتأخير لليوم من واقع القائمة المجهزة بالـ Memory
    today_attendance_count = sum(1 for a in attendance_list if a.status in ['present', 'late'])
    today_late_count = sum(1 for a in attendance_list if a.late_minutes > 0)

    # تحديد التبويب النشط ذكياً
    active_tab = 'dashboard'
    if len(attendance_list) > 0 or request.GET.get('date'):
        active_tab = 'attendance'

    context = {
        'employees': employees,
        'departments': departments,
        'leave_requests': leave_requests,
        'attendance': attendance_list,
        'latest_attendance': attendance_list[:5], # أخذ أول 5 عناصر مباشرة من الذاكرة بسرعة فائقة
        
        # العدادات الإحصائية
        'total_employees': total_emp,
        'today_attendance_count': today_attendance_count,
        'today_late_count': today_late_count,
        'notification_count': pending_leaves,
        'current_date': target_date,
        'active_tab': active_tab,
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


from django.shortcuts import render, redirect, get_object_or_404

from .forms import LeaveRequestForm  # تأكد من أن اسم ملف الفورم والموديل صحيح لديك

def leave_request_view(request):
    """
    تقديم طلب إجازة جديد من خلال الفورم الذكي وملء قائمة الموظفين ديناميكياً
    """
    if request.method == 'POST':
        form = LeaveRequestForm(request.POST)
        if form.is_valid():
            form.save()
            messages.success(request, 'تم إرسال طلب الإجازة بنجاح وبانتظار اعتماد الإدارة!')
            return redirect('hr:leave_list') 
        else:
            messages.error(request, 'عذراً، يرجى التحقق من صحة البيانات وتواريخ الإجازة.')
    else:
        form = LeaveRequestForm()
        
    # جلب الموظفين النشطين لملء القائمة المنسدلة في التمبلت المكتوب يدويًا
    employees = Employee.objects.filter(is_active=True).order_by('name')
    
    # جلب العداد لتحديث الجرس والقائمة الجانبية
    notification_count = LeaveRequest.objects.filter(status='pending').count()
    
    return render(request, 'hr/leave_form.html', {
        'form': form,
        'employees': employees,
        'notification_count': notification_count
    })

def leave_approve(request, leave_id):
    """
    اعتماد وقبول طلب الإجازة المعلق
    """
    try:
        leave = get_object_or_404(LeaveRequest, id=leave_id)
        leave.status = 'approved'
        leave.save()
        messages.success(request, f"تم اعتماد وقبول إجازة الموظف {leave.employee.name} بنجاح.")
    except Exception as e:
        messages.error(request, f"خطأ أثناء الاعتماد: {str(e)}")
    return redirect('hr:leave_list')

def leave_reject(request, leave_id):
    """
    رفض طلب الإجازة المعلق
    """
    try:
        leave = get_object_or_404(LeaveRequest, id=leave_id)
        leave.status = 'rejected'
        leave.save()
        messages.warning(request, f"تم رفض طلب إجازة الموظف {leave.employee.name}.")
    except Exception as e:
        messages.error(request, f"خطأ أثناء الرفض: {str(e)}")
    return redirect('hr:leave_list')