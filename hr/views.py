import pandas as pd
from django.shortcuts import render, redirect, get_object_or_404
from django.contrib import messages
from .forms import UploadAttendanceForm, EmployeeForm, DepartmentForm, LeaveForm
from .models import Employee, Department, PayrollArchive, Leave
from django.db.models import Sum

# ==========================================
# إدارة الموظفين والأقسام
# ==========================================
def employee_list(request):
    employees = Employee.objects.select_related('department').all().order_by('emp_id')
    return render(request, 'hr/employee_list.html', {'employees': employees})

def employee_create(request):
    if request.method == 'POST':
        form = EmployeeForm(request.POST)
        if form.is_valid():
            form.save()
            messages.success(request, 'تم إضافة الموظف بنجاح!')
            return redirect('hr:employee_list')
    else:
        form = EmployeeForm()
    return render(request, 'hr/employee_form.html', {'form': form, 'title': 'إضافة موظف جديد'})

def employee_update(request, pk):
    employee = get_object_or_404(Employee, pk=pk)
    if request.method == 'POST':
        form = EmployeeForm(request.POST, instance=employee)
        if form.is_valid():
            form.save()
            messages.success(request, 'تم تحديث بيانات الموظف بنجاح!')
            return redirect('hr:employee_list')
    else:
        form = EmployeeForm(instance=employee)
    return render(request, 'hr/employee_form.html', {'form': form, 'title': 'تعديل بيانات الموظف'})

def department_list(request):
    departments = Department.objects.all()
    return render(request, 'hr/department_list.html', {'departments': departments})

def department_create(request):
    if request.method == 'POST':
        form = DepartmentForm(request.POST)
        if form.is_valid():
            form.save()
            messages.success(request, 'تم إضافة القسم بنجاح!')
            return redirect('hr:department_list')
    else:
        form = DepartmentForm()
    return render(request, 'hr/department_form.html', {'form': form, 'title': 'إضافة قسم جديد'})

def department_update(request, pk):
    department = get_object_or_404(Department, pk=pk)
    if request.method == 'POST':
        form = DepartmentForm(request.POST, instance=department)
        if form.is_valid():
            form.save()
            messages.success(request, 'تم تعديل القسم بنجاح!')
            return redirect('hr:department_list')
    else:
        form = DepartmentForm(instance=department)
    return render(request, 'hr/department_form.html', {'form': form, 'title': 'تعديل بيانات القسم'})


# ==========================================
# معالجة البصمة (المنطق الجديد الأوتوماتيكي)
# ==========================================
# ==========================================
# معالجة البصمة والمرتبات (الكود الأقوى والأكثر حماية)
# ==========================================
def calculate_payroll(request):
    if request.method == 'POST':
        form = UploadAttendanceForm(request.POST, request.FILES)
        if form.is_valid():
            excel_file = request.FILES['file']
            month = form.cleaned_data['month']
            year = form.cleaned_data['year']
            
            try:
                df = pd.read_excel(excel_file)
                
                required_columns = ['EmpID', 'Date']
                if not all(col in df.columns for col in required_columns):
                    messages.error(request, "الملف لا يحتوي على عمودي (EmpID, Date).")
                    return render(request, 'hr/upload.html', {'form': form})
                
                late_col = 'Late' if 'Late' in df.columns else 'late' if 'late' in df.columns else None
                if not late_col:
                    messages.error(request, "الملف لا يحتوي على عمود التأخير برجاء تسميته (Late).")
                    return render(request, 'hr/upload.html', {'form': form})

                # تنظيف البصمات
                if 'CheckIn' in df.columns:
                    df['CheckIn'] = df['CheckIn'].astype(str).str.strip().replace(['nan', 'NaT', 'None', ''], pd.NA)
                else:
                    df['CheckIn'] = pd.NA
                    
                if 'CheckOut' in df.columns:
                    df['CheckOut'] = df['CheckOut'].astype(str).str.strip().replace(['nan', 'NaT', 'None', ''], pd.NA)
                else:
                    df['CheckOut'] = pd.NA

                # الموظف يعتبر "حاضر" إذا كان له بصمة دخول أو انصراف
                df['IsPresent'] = df['CheckIn'].notna() | df['CheckOut'].notna()
                
                def parse_late_minutes(val):
                    val = str(val).strip()
                    if val in ['nan', 'NaT', 'None', '', '0']: return 0
                    try:
                        if ':' in val:
                            parts = val.split(':')
                            return int(parts[0]) * 60 + int(parts[1])
                        else:
                            return int(float(val))
                    except:
                        return 0
                        
                df['DelayMinutes'] = df[late_col].apply(parse_late_minutes)
                df.loc[~df['IsPresent'], 'DelayMinutes'] = 0

                # حساب الغياب والحضور
                total_days = df.groupby('EmpID').agg(TotalDaysInSheet=('Date', 'nunique')).reset_index()
                present_data = df[df['IsPresent']].groupby('EmpID').agg(DaysPresent=('Date', 'nunique')).reset_index()
                delay_data = df.groupby('EmpID').agg(TotalDelayMinutes=('DelayMinutes', 'sum')).reset_index()
                
                summary = pd.merge(total_days, present_data, on='EmpID', how='left').fillna({'DaysPresent': 0})
                summary = pd.merge(summary, delay_data, on='EmpID', how='left').fillna({'TotalDelayMinutes': 0})
                
                summary['AbsentDaysSheet'] = summary['TotalDaysInSheet'] - summary['DaysPresent']
                summary['AbsentDaysSheet'] = summary['AbsentDaysSheet'].apply(lambda x: max(0, int(x)))

                payroll_data = []
                for index, row in summary.iterrows():
                    emp_id = str(row['EmpID']).split('.')[0].strip()
                    days_present = int(row['DaysPresent'])
                    sheet_absent_days = int(row['AbsentDaysSheet']) 
                    total_delay_minutes = int(row['TotalDelayMinutes'])
                    
                    try:
                        emp = Employee.objects.select_related('department').get(emp_id=emp_id)
                        name = emp.name
                        department_name = emp.department.name if emp.department else "بدون قسم"
                        base_salary = float(emp.base_salary)
                        social_insurance = float(emp.social_insurance)
                        medical_insurance = float(emp.medical_insurance)
                        penalties = float(emp.penalties)
                        loans = float(emp.loans)
                    except Employee.DoesNotExist:
                        continue 
                        
                    daily_rate = base_salary / 30 if base_salary > 0 else 0
                    
                    # =========================================================
                    # الكود الجديد والمضمون لقراءة الإجازات بشكل قاطع
                    # =========================================================
                    target_month = int(month)
                    target_year = int(year)
                    
                    calc_leaves = 0
                    # سحب كافة الإجازات المرتبطة بالموظف
                    all_leaves = Leave.objects.filter(employee=emp)
                    
                    for l in all_leaves:
                        l_type = str(l.leave_type).strip()
                        # نستبعد الإجازات بدون أجر
                        if l_type != 'Unpaid':
                            try:
                                # قراءة التاريخ كنص واستخراج الشهر والسنة منه لتجنب أي مشاكل في قاعدة البيانات
                                l_str = str(l.start_date).strip() # الشكل سيكون: YYYY-MM-DD
                                if len(l_str) >= 10:
                                    l_year = int(l_str[0:4])
                                    l_month = int(l_str[5:7])
                                    
                                    # إذا طابق الشهر والسنة، نجمع عدد الأيام
                                    if l_year == target_year and l_month == target_month:
                                        calc_leaves += float(l.days)
                            except Exception as parse_err:
                                pass # تجاهل الأخطاء الصامتة للتواريخ الفارغة
                                
                    leaves_taken = int(calc_leaves)
                    # =========================================================

                    actual_absent_days = sheet_absent_days - leaves_taken
                    if actual_absent_days < 0: actual_absent_days = 0
                    absence_deduction = actual_absent_days * daily_rate
                    
                    grace_period = days_present * 2
                    if grace_period > 60: grace_period = 60
                        
                    net_delay_minutes = total_delay_minutes - grace_period
                    if net_delay_minutes < 0: net_delay_minutes = 0
                    net_delay_hours = net_delay_minutes / 60.0
                    
                    if days_present > 0:
                        day_value_by_attendance = base_salary / days_present
                        lateness_deduction = net_delay_hours * day_value_by_attendance
                    else:
                        day_value_by_attendance = 0
                        lateness_deduction = 0
                    
                    total_deductions = social_insurance + medical_insurance + penalties + loans + lateness_deduction
                    net_salary = base_salary - absence_deduction - total_deductions
                    
                    payroll_data.append({
                        'emp_id': emp_id, 'name': name, 'department': department_name, 
                        'base_salary': round(base_salary, 2), 
                        'days_present': days_present, 
                        'leaves_taken': leaves_taken,
                        'sheet_absent_days': sheet_absent_days,
                        'absent_days': actual_absent_days, 
                        'absence_deduction': round(absence_deduction, 2),
                        'total_delay_minutes': total_delay_minutes,
                        'grace_period': grace_period,
                        'net_delay_minutes': net_delay_minutes,
                        'total_delay_hours': round(net_delay_hours, 2),
                        'lateness_deduction': round(lateness_deduction, 2),
                        'penalties': round(penalties, 2), 'loans': round(loans, 2),
                        'insurances': round(social_insurance + medical_insurance, 2),
                        'total_deductions': round(total_deductions, 2), 'net_salary': round(net_salary, 2)
                    })

                request.session['payroll_data'] = payroll_data
                request.session['payroll_month'] = month
                request.session['payroll_year'] = year

                return render(request, 'hr/payroll_report.html', {
                    'payroll_data': payroll_data, 'month': month, 'year': year, 'is_preview': True
                })
            except Exception as e:
                messages.error(request, f"حدث خطأ أثناء معالجة الملف: {str(e)}")
    else:
        form = UploadAttendanceForm()
    return render(request, 'hr/upload.html', {'form': form})


# ==========================================
# دالة ترحيل المرتبات للأرشيف
# ==========================================
def save_payroll_archive(request):
    if request.method == 'POST':
        payroll_data = request.session.get('payroll_data')
        month = request.session.get('payroll_month')
        year = request.session.get('payroll_year')

        if not payroll_data:
            messages.error(request, "انتهت الجلسة أو لا توجد بيانات للترحيل.")
            return redirect('hr:calculate_payroll')

        PayrollArchive.objects.filter(month=month, year=year).delete()

        for row in payroll_data:
            try:
                emp = Employee.objects.get(emp_id=row['emp_id'])
                PayrollArchive.objects.create(
                    employee=emp, month=month, year=year,
                    base_salary=row['base_salary'], days_present=row['days_present'],
                    leaves_taken=row.get('leaves_taken', 0), 
                    absent_days=row['absent_days'], absence_deduction=row['absence_deduction'],
                    lateness_deduction=row.get('lateness_deduction', 0),
                    total_delay_minutes=row.get('total_delay_minutes', 0),
                    penalties=row['penalties'], loans=row['loans'], insurances=row['insurances'],
                    net_salary=row['net_salary']
                )
            except Employee.DoesNotExist:
                pass

        for row in payroll_data:
            Employee.objects.filter(emp_id=row['emp_id']).update(penalties=0, loans=0)

        for key in ['payroll_data', 'payroll_month', 'payroll_year']:
            if key in request.session: del request.session[key]
        
        messages.success(request, f"تم ترحيل وحفظ مرتبات شهر {month}/{year} بنجاح!")
        return redirect('hr:payroll_archive')
    

# ==========================================
# دالة عرض أرشيف المرتبات
# ==========================================
def payroll_archive(request):
    available_archives = PayrollArchive.objects.values('month', 'year').distinct().order_by('-year', '-month')
    selected_month = request.GET.get('month')
    selected_year = request.GET.get('year')
    records = None
    if selected_month and selected_year:
        records = PayrollArchive.objects.filter(month=selected_month, year=selected_year).select_related('employee__department')
        
    return render(request, 'hr/payroll_archive.html', {
        'available_archives': available_archives,
        'records': records,
        'selected_month': selected_month,
        'selected_year': selected_year
    })

# ==========================================
# إدارة الإجازات والطباعة
# ==========================================
def leave_list(request):
    leaves = Leave.objects.select_related('employee').all().order_by('-start_date')
    return render(request, 'hr/leave_list.html', {'leaves': leaves})

def leave_create(request):
    if request.method == 'POST':
        form = LeaveForm(request.POST)
        if form.is_valid():
            # تم تصحيح هذا السطر: form.save بدلاً من form.form.save
            leave = form.save(commit=False) 
            emp = leave.employee
            if leave.leave_type == 'Annual':
                if emp.annual_leave_balance >= leave.days:
                    emp.annual_leave_balance -= leave.days
                else:
                    messages.error(request, "رصيد الإجازات السنوية لا يكفي!")
                    return render(request, 'hr/leave_form.html', {'form': form, 'title': 'تسجيل إجازة'})
            elif leave.leave_type == 'Casual':
                if emp.casual_leave_balance >= leave.days:
                    emp.casual_leave_balance -= leave.days
                else:
                    messages.error(request, "رصيد الإجازات العارضة لا يكفي!")
                    return render(request, 'hr/leave_form.html', {'form': form, 'title': 'تسجيل إجازة'})
            emp.save()
            leave.save()
            messages.success(request, 'تم تسجيل الإجازة وخصمها من رصيد الموظف بنجاح!')
            return redirect('hr:leave_list')
    else:
        form = LeaveForm()
    return render(request, 'hr/leave_form.html', {'form': form, 'title': 'تسجيل إجازة جديدة'})

def print_pay_slips(request, month, year):
    records = PayrollArchive.objects.filter(month=month, year=year).select_related('employee__department')
    if not records.exists():
        messages.error(request, "لا توجد بيانات مرحلة لهذا الشهر لطباعتها.")
        return redirect('hr:payroll_archive')
    return render(request, 'hr/print_pay_slips.html', {'records': records, 'month': month, 'year': year})