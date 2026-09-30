from datetime import datetime, date, time, timedelta
from django.shortcuts import render, redirect, get_object_or_404
from django.contrib import messages
from django.utils import timezone
from django.db import transaction
from openpyxl.styles import Alignment, Font, PatternFill, Border, Side
from django.db.models import Sum, FloatField, F, Case, When
from django.http import HttpResponse
import re
from django.core.paginator import Paginator
import pandas as pd
from django.db.models import Q, Prefetch, Value, Count
from django.db.models.functions import Coalesce
from django.contrib.auth.decorators import login_required
from .forms import PenaltyRecordForm  # أو أضفه لقائمة الـ imports الحالية
import openpyxl
from django.utils.dateparse import parse_date
import json
from django.core.serializers.json import DjangoJSONEncoder
from django.db.models import Max
from django.http import JsonResponse
import pandas as pd

from .models import (
    Employee,
    Department,
    AttendanceRule,
    DailyAttendance,
    LeaveRequest,
    MissionRequest,
    FinancialAdjustment,
    PublicHoliday,
    PermissionRequest,
    PenaltyRecord,
)

from .forms import (
    EmployeeForm,
    LeaveRequestForm,
    AttendanceRuleForm,
    DepartmentForm,
    UploadAttendanceForm,
    MissionRequestForm,
    FinancialAdjustmentForm,
    PublicHolidayForm,
    PermissionRequestForm
)

from decimal import Decimal

from django.views.decorators.http import require_POST
from itertools import groupby

import openpyxl
from openpyxl.styles import Font, Alignment, PatternFill, Border, Side

def export_attendance_excel(request):
    search_query = request.GET.get('q', '').strip()
    month = request.GET.get('month', '')
    year = request.GET.get('year', '')

    # 1. الترتيب أبجدياً حسب اسم الموظف ثم تاريخ الحضور
    queryset = DailyAttendance.objects.select_related('employee').all().order_by('employee__name', 'date')

    if search_query:
        queryset = queryset.filter(
            Q(employee__name__icontains=search_query) |
            Q(employee__emp_id__icontains=search_query)
        )

    # 2. تطبيق نطاق الدورة المالية (من 26 الشهر السابق إلى 25 الشهر المالي)
    if month and year:
        try:
            m = int(month)
            y = int(year)

            end_date = date(y, m, 25)
            if m == 1:
                start_date = date(y - 1, 12, 26)
            else:
                start_date = date(y, m - 1, 26)

            queryset = queryset.filter(date__gte=start_date, date__lte=end_date)
        except ValueError:
            pass

    # 3. إنشاء ملف Excel
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "السجل التفصيلي اليومي"
    ws.views.sheetView[0].rightToLeft = True

    # الألوان والتنسيقات
    header_fill = PatternFill(start_color="1E3A8A", end_color="1E3A8A", fill_type="solid")
    emp_banner_fill = PatternFill(start_color="2563EB", end_color="2563EB", fill_type="solid")

    header_font = Font(name="Arial", size=11, bold=True, color="FFFFFF")
    emp_font = Font(name="Arial", size=11, bold=True, color="FFFFFF")
    data_font = Font(name="Arial", size=10)

    center_align = Alignment(horizontal="center", vertical="center", wrap_text=True)

    thin_border = Border(
        left=Side(style='thin', color='D3D3D3'),
        right=Side(style='thin', color='D3D3D3'),
        top=Side(style='thin', color='D3D3D3'),
        bottom=Side(style='thin', color='D3D3D3')
    )

    headers = ['التاريخ', 'الموظف / الشفت', 'حضور', 'انصراف', 'تأخير / خصم', 'إضافي', 'الجزاءات', 'الحالة']
    ws.append(headers)

    for col_num, header in enumerate(headers, 1):
        cell = ws.cell(row=1, column=col_num)
        cell.font = header_font
        cell.fill = header_fill
        cell.alignment = Alignment(horizontal="center", vertical="center")

    # 4. تجميع السجلات أبجدياً
    current_row = 2
    records_list = list(queryset)

    for employee, group in groupby(records_list, key=lambda x: x.employee):
        emp_records = list(group)
        emp_name = employee.name if employee else "غير محدد"
        emp_code = employee.emp_id if employee else "-"

        # شريط بيانات الموظف
        ws.merge_cells(start_row=current_row, start_column=1, end_row=current_row, end_column=len(headers))
        emp_cell = ws.cell(row=current_row, column=1)
        emp_cell.value = f"الموظف: {emp_name}  |  كود: {emp_code}"
        emp_cell.font = emp_font
        emp_cell.fill = emp_banner_fill
        emp_cell.alignment = Alignment(horizontal="right", vertical="center", indent=1)

        for col_num in range(1, len(headers) + 1):
            ws.cell(row=current_row, column=col_num).border = thin_border

        current_row += 1

        for record in emp_records:
            # صياغة نص التأخير والخصم
            late_mins = getattr(record, 'late_minutes', 0) or 0
            deduction_hrs = getattr(record, 'late_deduction_hours', None) or getattr(record, 'deduction_hours', None)
            if deduction_hrs is None and late_mins > 0:
                deduction_hrs = round(late_mins / 60, 1)

            if late_mins > 0:
                late_display = f"{late_mins} دقيقة\n(خصم: {deduction_hrs} س)"
            else:
                late_display = "-"

            # 🟢 5. صياغة تفنيط الجزاءات (أيام / يومان / يوم)
            penalty_raw = getattr(record, 'administrative_penalty_days', None)
            if penalty_raw and float(penalty_raw) > 0:
                p_val = float(penalty_raw)
                p_num = int(p_val) if p_val.is_integer() else p_val

                if p_num == 1:
                    penalty_display = "1 (يوم)"
                elif p_num == 2:
                    penalty_display = "2 (يومان)"
                elif isinstance(p_num, int) and 3 <= p_num <= 10:
                    penalty_display = f"{p_num} (أيام)"
                else:
                    penalty_display = f"{p_num} (يوم)"
            else:
                penalty_display = "-"

            row_data = [
                record.date.strftime('%Y-%m-%d') if record.date else '-',
                getattr(record, 'shift_name', 'تابع السجل'),
                record.check_in.strftime('%H:%M') if record.check_in else '-',
                record.check_out.strftime('%H:%M') if record.check_out else '-',
                late_display,
                record.overtime_hours if getattr(record, 'overtime_hours', None) else '-',
                penalty_display,  # 👈 عمود الجزاءات المُنسق بالأيام
                record.get_status_display() if hasattr(record, 'get_status_display') else getattr(record, 'status', '-')
            ]
            ws.append(row_data)

            # تطبيق التنسيق والحدود
            for col_num in range(1, len(headers) + 1):
                cell = ws.cell(row=current_row, column=col_num)
                cell.font = data_font
                cell.alignment = center_align
                cell.border = thin_border

            current_row += 1

        current_row += 1

    # ضبط أبعاد الأعمدة
    for col in ws.columns:
        max_len = max(len(str(cell.value or '')) for cell in col)
        col_letter = openpyxl.utils.get_column_letter(col[0].column)
        ws.column_dimensions[col_letter].width = max(max_len + 4, 18)

    # إرجاع الملف
    response = HttpResponse(
        content_type='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet'
    )
    filename = f"attendance_cycle_{month or 'all'}_{year or 'all'}.xlsx"
    response['Content-Disposition'] = f'attachment; filename="{filename}"'
    wb.save(response)

    return response

@require_POST
@login_required
def manual_checkout(request, record_id):
    """
    تسجيل انصراف يدوي في حال عطل ماكينة البصمة.
    يقوم بحساب الساعات، رفع جزاء البصمة الواحدة، ومراجعة قانون الانصراف المبكر.
    """
    # التأكد من صلاحيات الإدارة
    if not request.user.is_staff:
        return JsonResponse({'status': 'error', 'message': 'غير مصرح لك باتخاذ هذا الإجراء.'}, status=403)

    try:
        record = DailyAttendance.objects.select_related('employee__attendance_rule').get(id=record_id)
        checkout_time_str = request.POST.get('checkout_time') # الصيغة المتوقعة: "HH:MM"

        if not checkout_time_str:
            return JsonResponse({'status': 'error', 'message': 'يرجى تحديد وقت الانصراف.'}, status=400)

        # تحويل النص إلى كائن وقت
        checkout_time = datetime.strptime(checkout_time_str, '%H:%M').time()

        # التحقق من وجود بصمة حضور مسبقة لتجنب الأخطاء المنطقية
        if not record.check_in:
            return JsonResponse({'status': 'error', 'message': 'لا يوجد وقت حضور مسجل لهذا اليوم.'}, status=400)

        # دمج التواريخ لحساب الفارق الزمني بدقة
        chk_in_dt = datetime.combine(record.date, record.check_in)
        chk_out_dt = datetime.combine(record.date, checkout_time)

        if chk_out_dt <= chk_in_dt:
            return JsonResponse({'status': 'error', 'message': 'وقت الانصراف يجب أن يكون بعد وقت الحضور.'}, status=400)

        # 1. تحديث وقت الانصراف وحساب الساعات
        record.check_out = checkout_time
        actual_hours = (chk_out_dt - chk_in_dt).total_seconds() / 3600.0
        record.actual_work_hours = round(actual_hours, 2)

        # 2. رفع جزاء البصمة الواحدة الافتراضي وتحديث الحالة
        record.administrative_penalty_days = 0.0
        record.status = 'present'

        # 3. إعادة تطبيق قانون الانصراف المبكر الصارم (إن وجد)
        rule = record.employee.attendance_rule
        is_flexible = getattr(rule, 'shift_type', '') == 'flexible'

        if not is_flexible and checkout_time < time(14, 0):
            record.administrative_penalty_days = 3.0
            record.status = 'absent'
            record.deduction_hours = 0.0
            message = 'تم تسجيل الانصراف، ولكن تم تطبيق جزاء 3 أيام بسبب الانصراف قبل الساعة 2 ظهراً.'
        else:
            message = 'تم تسجيل الانصراف اليدوي وحساب الساعات ورفع الجزاء بنجاح.'

        record.save()
        return JsonResponse({'status': 'success', 'message': message})

    except DailyAttendance.DoesNotExist:
        return JsonResponse({'status': 'error', 'message': 'سجل الحضور غير موجود.'}, status=404)
    except ValueError:
        return JsonResponse({'status': 'error', 'message': 'صيغة الوقت غير صحيحة.'}, status=400)
    except Exception as e:
        return JsonResponse({'status': 'error', 'message': str(e)}, status=500)


@require_POST
def apply_fraud_penalty(request, record_id):
    """
    توقيع جزاء التحايل (الخروج بدون إذن ثم العودة للبصمة)
    يقوم بفرض 3 أيام جزاء إداري وتحويل اليوم إلى غياب
    """
    try:
        # التأكد من صلاحيات المدير (يفضل أن تكون للمديرين فقط)
        if not request.user.is_staff:
            return JsonResponse({'status': 'error', 'message': 'غير مصرح لك باتخاذ هذا الإجراء.'}, status=403)

        record = DailyAttendance.objects.get(id=record_id)

        # تطبيق قانون الجزاء الصارم (متوافق مع قانون الانصراف المبكر في النظام)
        record.administrative_penalty_days = 3.0
        record.status = 'absent'
        record.save()

        return JsonResponse({
            'status': 'success',
            'message': f'تم توقيع جزاء 3 أيام على الموظف {record.employee.name} واعتبار اليوم غياباً.'
        })

    except DailyAttendance.DoesNotExist:
        return JsonResponse({'status': 'error', 'message': 'تعذر العثور على سجل الحضور.'}, status=404)
    except Exception as e:
        return JsonResponse({'status': 'error', 'message': str(e)}, status=500)

@require_POST
@login_required
def remove_fraud_penalty(request, record_id):
    """إلغاء جزاء التحايل وإرجاع اليوم لحالة حاضر"""
    if not request.user.is_staff:
        return JsonResponse({'status': 'error', 'message': 'غير مصرح لك باتخاذ هذا الإجراء.'}, status=403)

    try:
        record = DailyAttendance.objects.select_related('employee').get(id=record_id)
    except DailyAttendance.DoesNotExist:
        return JsonResponse({'status': 'error', 'message': 'تعذر العثور على سجل الحضور.'}, status=404)

    record.administrative_penalty_days = 0.0

    # جزاء التحايل لا يضيف خصم غياب، فلو اليوم غياب حقيقي (absence_deduction_days > 0) نتركه غياباً
    if record.status == 'absent' and record.absence_deduction_days == 0:
        record.status = 'present'

    # بعد إضافة الحقل الجديد فقط (لو لم تضفه بعد يتجاهل السطر)
    if hasattr(record, 'is_manual_override'):
        record.is_manual_override = False

    record.save()
    return JsonResponse({
        'status': 'success',
        'message': f'تم إلغاء الجزاء عن الموظف {record.employee.name}.'
    })



@login_required
def penalty_add(request, employee_id=None):
    employee = get_object_or_404(Employee, id=employee_id) if employee_id else None

    if request.method == 'POST':
        form = PenaltyRecordForm(request.POST)
        if employee:
            form.fields['employee'].required = False
        if form.is_valid():
            penalty = form.save(commit=False)
            if employee:
                penalty.employee = employee
            penalty.created_by = request.user if request.user.is_authenticated else None
            penalty.save()
            messages.success(request, f"تم توقيع الجزاء على الموظف {penalty.employee.name} بخصم {penalty.deduction_days} يوم بنجاح.")
            return redirect('hr:penalty_list_for_employee', employee_id=penalty.employee.id)
    else:
        form = PenaltyRecordForm(initial={'date': timezone.localdate()})
        if employee:
            form.fields['employee'].required = False

    # 🟢 تجهيز قائمة الموظفين للبحث الفوري
    all_employees = list(Employee.objects.filter(is_active=True).values('id', 'name', 'emp_id'))

    context = {
        'employee': employee,
        'form': form,
        'all_employees_json': json.dumps(all_employees, cls=DjangoJSONEncoder), # تحويل البيانات لـ JSON
        'penalty_types': PenaltyRecord.PENALTY_TYPES,
        'today': timezone.localdate(),
    }
    return render(request, 'hr/penalty_form.html', context)


@login_required
def penalty_list(request, employee_id=None):
    """
    🟢 سجل الجزاءات الإدارية: عام لكل الموظفين، أو مفلتر على موظف واحد لو
    اتبعت employee_id (تُستخدم برضو داخل صفحة بروفايل الموظف).
    """
    penalties = PenaltyRecord.objects.select_related('employee', 'created_by').all()

    employee = None
    if employee_id:
        employee = get_object_or_404(Employee, id=employee_id)
        penalties = penalties.filter(employee=employee)

    search_query = request.GET.get('q', '').strip()
    if search_query and not employee_id:
        if search_query.isdigit():
            # 🟢 مطابقة تامة Exact Match لكود البصمة إذا كان المدخل رقماً
            penalties = penalties.filter(employee__emp_id=search_query)
        else:
            # 🔵 بحث مرن بالهمزات والحروف المتشابهة لاسم الموظف إذا كان المدخل نصاً
            pattern = search_query
            pattern = re.sub(r'[اأإآ]', r'[اأإآ]', pattern)
            pattern = re.sub(r'[هة]', r'[هة]', pattern)
            pattern = re.sub(r'[يى]', r'[يى]', pattern)

            penalties = penalties.filter(
                Q(employee__name__iregex=pattern)
            )

    paginator = Paginator(penalties, 30)
    page_number = request.GET.get('page')
    penalties_page = paginator.get_page(page_number)

    context = {
        'penalties': penalties_page,
        'employee': employee,
        'search_query': search_query,
    }
    return render(request, 'hr/penalty_list.html', context)


@require_POST
@login_required
def penalty_delete(request, penalty_id):
    """🟢 إلغاء جزاء تم توقيعه بالغلط (مثلاً خطأ إداري)."""
    penalty = get_object_or_404(PenaltyRecord, id=penalty_id)
    employee_id = penalty.employee_id
    penalty.delete()
    messages.success(request, "تم إلغاء الجزاء بنجاح.")
    return redirect('hr:penalty_list_for_employee', employee_id=employee_id)


def request_leave(request, employee_id):
    employee = get_object_or_404(Employee, id=employee_id)

    if request.method == 'POST':
        leave_date_str = request.POST.get('leave_date', '').strip()

        # 1. 🛡️ التحقق من أمان وصحة التاريخ المدخل (تجنب أخطاء تقطيع النصوص ValueError / TypeError)
        leave_date = parse_date(leave_date_str)
        if not leave_date:
            messages.error(request, "🛑 خطأ: يرجى تحديد تاريخ إجازة صحيح.")
            return redirect('leave_requests')

        # 2. ⚡ حساب بداية الشهر باستخدام replace(day=1) بشكل سريع وآمن
        leave_month_start = leave_date.replace(day=1)

        # 3. 🟢 الفحص: التأكد من وجود تاريخ التعيين وقارنته بأول الشهر
        if employee.hire_date and employee.hire_date > leave_month_start:
            messages.error(
                request,
                "🛑 غير مصرح: الموظف المعين خلال الشهر الحالي ليس له رصيد إجازات. سيتم احتساب هذا اليوم كغياب بدون أجر."
            )
            return redirect('leave_requests')

        # 4. 🚀 تنفيذ الحفظ بأمان داخل Atomic Transaction لتفادي تعارض البيانات
        with transaction.atomic():
            # ... إكمال كود تسجيل الإجازة للمستحقين ...
            pass

        messages.success(request, "تم تقديم طلب الإجازة بنجاح.")
        return redirect('leave_requests')

    return render(request, 'hr/request_leave.html', {'employee': employee})

def calculate_monthly_payroll(employee, year, month):
    """
    محرك الرواتب: يحسب الراتب التناسبي، يمنع الإجازات للمعينين الجدد، ويحسب الجزاءات.
    """
    month_start = date(year, month, 1)

    # 1. حساب الأيام المستحقة والأجر اليومي
    active_days = employee.get_active_days_in_month(year, month)
    daily_wage = employee.daily_wage

    if active_days == 0:
        return None # لا يستحق راتب هذا الشهر

    # 2. هل يستحق رصيد إجازات هذا الشهر؟
    # (الشرط: يجب أن يكون تعين قبل أو في أول يوم من الشهر)
    is_eligible_for_leave = (employee.hire_date <= month_start)

    # 3. حساب الراتب الإجمالي (النسبة والتناسب)
    gross_salary = Decimal(str(active_days)) * daily_wage

    # استبدال AttendanceRecord بـ DailyAttendance
    absent_days = DailyAttendance.objects.filter(
        employee=employee,
        date__year=year,
        date__month=month,
        date__gte=employee.hire_date,
        status='absent'
    ).count()

    if not is_eligible_for_leave:
        unauthorized_leaves = DailyAttendance.objects.filter(
            employee=employee,
            date__year=year,
            date__month=month,
            date__gte=employee.hire_date,
            status='leave'
        ).count()
        absent_days += unauthorized_leaves

    # جلب الجزاءات الإدارية (بالأيام)
    penalty_days_agg = PenaltyRecord.objects.filter(
        employee=employee,
        date__year=year,
        date__month=month
    ).aggregate(total_days=Sum('deduction_days'))
    penalty_days = penalty_days_agg['total_days'] or 0

    # 5. حساب الخصومات بناءً على الأجر اليومي
    total_deduction_days = Decimal(str(absent_days)) + Decimal(str(penalty_days))
    total_deductions_amount = total_deduction_days * daily_wage

    # 6. الراتب الصافي
    net_salary = max(Decimal('0.00'), gross_salary - total_deductions_amount)

    return {
        'employee_name': employee.name,
        'active_days': active_days,
        'daily_wage': round(daily_wage, 2),
        'gross_salary': round(gross_salary, 2),
        'absent_days': absent_days,
        'penalty_days': penalty_days,
        'total_deductions_amount': round(total_deductions_amount, 2),
        'net_salary': round(net_salary, 2),
        'has_leave_balance': is_eligible_for_leave,
    }

@transaction.atomic
def leave_cancel(request, leave_id):
    try:
        leave = get_object_or_404(LeaveRequest.objects.select_related('employee'), id=leave_id)

        # التأكد أن الإجازة معتمدة بالفعل قبل الإلغاء
        if leave.status == 'approved':
            emp = leave.employee

            # 🛑 إلغاء التعديل اليدوي للرصيد من هنا لمنع التكرار
            # دالة leave.save() أدناه ستشعر بتغير الحالة من approved إلى rejected
            # وتستدعي _update_employee_balance(operation='refund') تلقائياً.

            # 1. تغيير حالة الطلب (سيقوم الموديل باسترداد الرصيد تلقائياً)
            leave.status = 'rejected'
            leave.save()

            # 2. تعديل سجل الحضور وتطبيق جزاء الغياب الصارم (3 أيام)
            DailyAttendance.objects.filter(
                employee=emp,
                date__range=[leave.start_date, leave.end_date],
                status='leave'
            ).update(
                status='absent',
                administrative_penalty_days=3.0
            )

            if request.headers.get('x-requested-with') == 'XMLHttpRequest':
                return JsonResponse({'status': 'success', 'message': f'تم إلغاء الإجازة، استرجاع الرصيد، وتطبيق الغياب لـ {emp.name}'})

            messages.success(request, f"تم إلغاء إجازة {emp.name} واسترجاع رصيده وتطبيق جزاء الغياب بنجاح.")
        else:
            if request.headers.get('x-requested-with') == 'XMLHttpRequest':
                return JsonResponse({'status': 'error', 'message': 'لا يمكن إلغاء هذه الإجازة لأنها غير معتمدة حالياً.'}, status=400)

    except Exception as e:
        if request.headers.get('x-requested-with') == 'XMLHttpRequest':
            return JsonResponse({'status': 'error', 'message': str(e)}, status=400)
        messages.error(request, f"خطأ أثناء الإلغاء: {str(e)}")

    return redirect('hr:leave_list')


@login_required
def mobile_approvals_view(request):
    today = timezone.localdate()

    # 1. قراءة الفلاتر القادمة من الرابط (الحالة والشهر)
    status_filter = request.GET.get('status', 'pending')
    month_param = request.GET.get('month')

    # 2. تحديد السنة والشهر المستهدفين بدقة
    if month_param and '-' in month_param:
        try:
            parts = month_param.split('-')
            target_year = int(parts[0])
            target_month = int(parts[1])
        except ValueError:
            target_year = today.year
            target_month = today.month
    else:
        # إذا لم يتم تحديد شهر، يتم تحديد الدورة الحالية بناءً على تاريخ اليوم
        if today.day >= 26:
            target_month = today.month + 1 if today.month < 12 else 1
            target_year = today.year if today.month < 12 else today.year + 1
        else:
            target_month = today.month
            target_year = today.year

    # 3. 🟢 حساب الدورة المحاسبية (من يوم 26 الشهر السابق إلى 25 الشهر الحالي)
    cycle_end = date(target_year, target_month, 25)
    prev_month = target_month - 1 if target_month > 1 else 12
    prev_year = target_year if target_month > 1 else target_year - 1
    cycle_start = date(prev_year, prev_month, 26)

    # 4. بناء الاستعلام بناءً على الحالة (معلقة/معتمدة) وتواريخ الدورة
    leaves_query = LeaveRequest.objects.select_related('employee').filter(
        status=status_filter,
        start_date__gte=cycle_start,
        start_date__lte=cycle_end
    ).order_by('employee__name', 'start_date')

    # 5. الحماية الاحترافية: فلترة الطلبات للموظفين المربوطين بحساب الـ HR الحالي
    if not request.user.is_superuser:
        leaves_query = leaves_query.filter(employee__hr_managers=request.user)

    # تنفيذ الاستعلام مرة واحدة (للحفاظ على الخفة والسرعة)
    leaves_list = list(leaves_query)

    # 6. استخراج أرقام الموظفين لحساب الإحصائيات والأرصدة
    emp_ids = {leave.employee_id for leave in leaves_list}

    if emp_ids:
        # جلب الإجازات المعتمدة خلال "نفس الدورة المحددة" لخصمها من الرصيد المعروض
        approved_this_cycle = LeaveRequest.objects.filter(
            employee_id__in=emp_ids,
            status='approved',
            start_date__gte=cycle_start,
            start_date__lte=cycle_end,
            leave_type__in=['casual', 'annual']
        )

        stats_dict = {}
        for leave in approved_this_cycle:
            emp_id = leave.employee_id
            if emp_id not in stats_dict:
                stats_dict[emp_id] = {'casual': 0, 'annual': 0}
            stats_dict[emp_id][leave.leave_type] += leave.duration_days

        # حقن الإحصائيات في الطلبات المعروضة
        for leave in leaves_list:
            emp = leave.employee
            emp.annotated_casual_taken = stats_dict.get(emp.id, {}).get('casual', 0)
            emp.annotated_annual_taken = stats_dict.get(emp.id, {}).get('annual', 0)
    else:
        # تأمين المتغيرات في حالة عدم وجود طلبات
        for leave in leaves_list:
            leave.employee.annotated_casual_taken = 0
            leave.employee.annotated_annual_taken = 0

    return render(request, 'hr/mobile_approvals.html', {
        'leaves': leaves_list
    })



def get_payroll_data(year, month):
    cycle_end = date(year, month, 25)
    cycle_start = date(year - 1, 12, 26) if month == 1 else date(year, month - 1, 26)

    # جلب جميع الموظفين النشطين
    employees = Employee.objects.filter(is_active=True).select_related('department', 'attendance_rule').order_by('name')

    records = []
    totals = {
        'base': 0.0, 'overtime': 0.0, 'deductions': 0.0, 'net': 0.0,
        'abs_days': 0.0, 'abs_amt': 0.0, 'pen_days': 0.0, 'pen_amt': 0.0,
        'late_hrs': 0.0, 'late_amt': 0.0
    }

    for emp in employees:
        # 🟢 تحديد بداية فترة الحساب الفعلية للموظف (تاريخ تعيينه أو بداية الدورة أيهما أحدث)
        emp_effective_start = emp.hire_date if (emp.hire_date and emp.hire_date > cycle_start) else cycle_start

        # جلب سجلات حضور الموظف ابتداءً من تاريخ التعيين فقط وحتى نهاية الدورة
        attendance_qs = emp.daily_attendance_records.filter(
            date__gte=emp_effective_start,
            date__lte=cycle_end
        )

        # حساب الساعات والأيام من السجلات المفلترة فقط
        overtime_hours = attendance_qs.aggregate(
            total=Coalesce(Sum('overtime_hours'), Value(0.0), output_field=FloatField())
        )['total']

        absence_days = attendance_qs.filter(status='absent').count()

        late_hours = attendance_qs.exclude(
            status__in=['mission', 'leave', 'holiday', 'permission', 'excused']
        ).aggregate(
            total=Coalesce(Sum('deduction_hours'), Value(0.0), output_field=FloatField())
        )['total']

        attendance_penalties = attendance_qs.exclude(
            status__in=['mission', 'leave', 'holiday', 'permission', 'excused']
        ).aggregate(
            total=Coalesce(
                Sum(
                    Case(
                        When(status='absent', administrative_penalty_days__gte=1.0, then=F('administrative_penalty_days') - 1.0),
                        default=F('administrative_penalty_days'),
                        output_field=FloatField()
                    )
                ),
                Value(0.0), output_field=FloatField()
            )
        )['total']

        # الجزاءات الإدارية الصادرة للموظف بعد تاريخ تعيينه
        admin_penalties = PenaltyRecord.objects.filter(
            employee=emp,
            date__gte=emp_effective_start,
            date__lte=cycle_end
        ).aggregate(
            total=Coalesce(Sum('deduction_days'), Value(0.0), output_field=FloatField())
        )['total']

        # نوع الشفت
        is_open_shift = bool(emp.attendance_rule and getattr(emp.attendance_rule, 'shift_type', '') == 'open')

        if is_open_shift:
            absence_days = 0
            late_hours = 0.0
            attendance_penalties = 0.0

        penalty_days = attendance_penalties + admin_penalties
        base_salary = float(emp.base_salary) if emp.base_salary else 0.0

        days_in_month_rule = 12.0 if (emp.attendance_rule and "12" in emp.attendance_rule.name) else 30.0
        actual_attended_days = max(0.0, days_in_month_rule - absence_days)

        attendance_ratio = (actual_attended_days / days_in_month_rule) if (days_in_month_rule > 0 and actual_attended_days > 0) else 1.0
        penalty_multiplier = 1.0 / attendance_ratio if attendance_ratio > 0 else 1.0

        standard_day_rate = base_salary / days_in_month_rule if days_in_month_rule > 0 else 0.0
        standard_hourly_rate = base_salary / 240.0

        effective_day_rate = standard_day_rate * penalty_multiplier
        effective_hourly_rate = standard_hourly_rate * penalty_multiplier

        absence_deduction = absence_days * standard_day_rate
        penalty_deduction = penalty_days * effective_day_rate
        late_deduction = late_hours * effective_hourly_rate

        overtime_allowance = overtime_hours * standard_hourly_rate
        insurance_deduction = float(emp.insurance_deduction) if (getattr(emp, 'is_insured', False) and emp.insurance_deduction) else 0.0

        admin_deductions = late_deduction + absence_deduction + penalty_deduction
        total_deductions_combined = admin_deductions + insurance_deduction

        max_possible_deduction = base_salary + overtime_allowance
        actual_total_deductions = min(total_deductions_combined, max_possible_deduction)

        net_salary = max(0.0, base_salary + overtime_allowance - actual_total_deductions)

        totals['base'] += base_salary
        totals['overtime'] += overtime_allowance
        totals['deductions'] += actual_total_deductions
        totals['net'] += net_salary
        totals['abs_days'] += absence_days
        totals['abs_amt'] += absence_deduction
        totals['pen_days'] += penalty_days
        totals['pen_amt'] += penalty_deduction
        totals['late_hrs'] += late_hours
        totals['late_amt'] += late_deduction

        records.append({
            'employee': emp,
            'base_salary': round(base_salary, 2),
            'absence_days': absence_days,
            'absence_deduction': round(absence_deduction, 2),
            'penalty_days': round(penalty_days, 2),
            'penalty_deduction': round(penalty_deduction, 2),
            'late_hours': round(late_hours, 2),
            'late_deduction': round(late_deduction, 2),
            'overtime_hours': overtime_hours,
            'overtime_allowance': round(overtime_allowance, 2),
            'insurance_deduction': round(insurance_deduction, 2),
            'admin_deductions': round(admin_deductions, 2),
            'deductions': round(actual_total_deductions, 2),
            'net_salary': round(net_salary, 2),
        })

    return {
        'records': records,
        'totals': totals,
        'cycle_start': cycle_start,
        'cycle_end': cycle_end
    }


def monthly_payroll_report(request):
    try:
        today = timezone.localdate()
        year = int(request.GET.get('year', today.year))
        month = int(request.GET.get('month', today.month))

        payroll_data = get_payroll_data(year, month)

        context = {
            'payroll_records': payroll_data['records'],
            'year': year,
            'month': month,
            'total_company_base': round(payroll_data['totals']['base'], 2),
            'total_company_overtime': round(payroll_data['totals']['overtime'], 2),
            'total_company_deductions': round(payroll_data['totals']['deductions'], 2),
            'total_company_net': round(payroll_data['totals']['net'], 2),
            'months_range': range(1, 13),
            'years_range': range(today.year - 2, today.year + 3),
        }
        return render(request, 'hr/payroll_report.html', context)

    except Exception as server_err:
        print(f"❌ خطأ كشف الرواتب: {str(server_err)}")
        raise server_err


def export_payroll_excel(request, year, month):
    year, month = int(year), int(month)
    payroll_data = get_payroll_data(year, month)

    cycle_start = payroll_data['cycle_start']
    cycle_end = payroll_data['cycle_end']

    response = HttpResponse(content_type='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet')
    response['Content-Disposition'] = f'attachment; filename="Payroll_Talaat_Harb_{year}_{month}.xlsx"'

    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = f"مرتبات {month}-{year}"
    ws.sheet_view.rightToLeft = True

    title_font = Font(name='Arial', size=14, bold=True)
    header_font = Font(name='Arial', size=12, bold=True)
    normal_font = Font(name='Arial', size=11, bold=True)
    center_aligned = Alignment(horizontal='center', vertical='center', wrap_text=True)
    thin_border = Border(left=Side(style='thin'), right=Side(style='thin'), top=Side(style='thin'), bottom=Side(style='thin'))
    header_fill = PatternFill(start_color='E2EFDA', end_color='E2EFDA', fill_type='solid')

    ws.merge_cells('A1:C2')
    ws['A1'].value = "محافظة القاهرة\nإدارة عين شمس التعليمية\nمدارس طلعت حرب الثانوية الفندقية"
    ws['A1'].font = header_font; ws['A1'].alignment = center_aligned

    ws.merge_cells('D1:O2')
    ws['D1'].value = f"كشف مرتبات العاملين بالمدرسة عن دورة شهر {month} لعام {year} (من {cycle_start.strftime('%d/%m')} إلى {cycle_end.strftime('%d/%m')})"
    ws['D1'].font = title_font; ws['D1'].alignment = center_aligned

    headers = {
        'A': 'م', 'B': 'الاســـــــــــــــم', 'C': 'الوظيفة', 'D': 'المرتب الأساسي',
        'K': 'إضافي', 'L': 'إجمالي الخصومات', 'M': 'صافى المرتب', 'N': 'التوقيــع', 'O': 'ملاحظات'
    }

    for col, text in headers.items():
        ws.merge_cells(f'{col}3:{col}4')
        cell = ws[f'{col}3']
        cell.value = text; cell.font = header_font; cell.alignment = center_aligned; cell.fill = header_fill; cell.border = thin_border
        ws[f'{col}4'].border = thin_border

    ws.merge_cells('E3:F3'); ws['E3'] = 'غياب'; ws['E3'].font = header_font; ws['E3'].alignment = center_aligned; ws['E3'].fill = header_fill; ws['E3'].border = thin_border
    ws.merge_cells('G3:H3'); ws['G3'] = 'جزاءات وتحايل'; ws['G3'].font = header_font; ws['G3'].alignment = center_aligned; ws['G3'].fill = header_fill; ws['G3'].border = thin_border
    ws.merge_cells('I3:J3'); ws['I3'] = 'تأخيرات'; ws['I3'].font = header_font; ws['I3'].alignment = center_aligned; ws['I3'].fill = header_fill; ws['I3'].border = thin_border

    sub_headers = {'E': 'أيام', 'F': 'المبلغ', 'G': 'أيام', 'H': 'المبلغ', 'I': 'ساعات', 'J': 'المبلغ'}
    for col, text in sub_headers.items():
        cell = ws[f'{col}4']
        cell.value = text; cell.font = Font(name='Arial', size=10, bold=True); cell.alignment = center_aligned; cell.fill = header_fill; cell.border = thin_border

    ws.column_dimensions['B'].width = 30
    for col in ['E', 'F', 'G', 'H', 'I', 'J']: ws.column_dimensions[col].width = 12

    row_num = 5
    for index, rec in enumerate(payroll_data['records'], 1):
        emp = rec['employee']
        row_data = [
            index,
            emp.name,
            emp.department.name if emp.department else '-',
            rec['base_salary'],
            rec['absence_days'] if rec['absence_days'] > 0 else '-',
            rec['absence_deduction'] if rec['absence_deduction'] > 0 else '-',
            rec['penalty_days'] if rec['penalty_days'] > 0 else '-',
            rec['penalty_deduction'] if rec['penalty_deduction'] > 0 else '-',
            rec['late_hours'] if rec['late_hours'] > 0 else '-',
            rec['late_deduction'] if rec['late_deduction'] > 0 else '-',
            rec['overtime_allowance'] if rec['overtime_allowance'] > 0 else '-',
            rec['deductions'] if rec['deductions'] > 0 else '-',
            rec['net_salary'], '', ''
        ]

        for col_idx, value in enumerate(row_data, 1):
            cell = ws.cell(row=row_num, column=col_idx)
            cell.value = value; cell.font = normal_font; cell.alignment = center_aligned; cell.border = thin_border

        row_num += 1

    # صف الإجمالي
    ws.merge_cells(start_row=row_num, start_column=1, end_row=row_num, end_column=3)
    ws.cell(row=row_num, column=1).value = "إجمالــى الكشف"
    ws.cell(row=row_num, column=1).font = title_font; ws.cell(row=row_num, column=1).alignment = center_aligned
    ws.cell(row=row_num, column=1).border = thin_border; ws.cell(row=row_num, column=1).fill = header_fill

    ws.cell(row=row_num, column=2).border = thin_border
    ws.cell(row=row_num, column=3).border = thin_border

    totals = payroll_data['totals']
    totals_data = [
        (4, totals['base']), (5, totals['abs_days']), (6, totals['abs_amt']),
        (7, totals['pen_days']), (8, totals['pen_amt']), (9, totals['late_hrs']),
        (10, totals['late_amt']), (11, totals['overtime']), (12, totals['deductions']), (13, totals['net'])
    ]

    for col_idx, total_val in totals_data:
        cell = ws.cell(row=row_num, column=col_idx)
        cell.value = round(total_val, 2) if total_val > 0 else '-'
        cell.font = Font(name='Arial', size=11, bold=True, color='FF0000')
        cell.alignment = center_aligned; cell.border = thin_border; cell.fill = header_fill

    ws.cell(row=row_num, column=14).border = thin_border; ws.cell(row=row_num, column=14).fill = header_fill
    ws.cell(row=row_num, column=15).border = thin_border; ws.cell(row=row_num, column=15).fill = header_fill

    wb.save(response)
    return response


# def monthly_payroll_report(request):
#     try:
#         today = timezone.localdate()
#         year = int(request.GET.get('year', today.year))
#         month = int(request.GET.get('month', today.month))

#         cycle_end = date(year, month, 25)
#         cycle_start = date(year - 1, 12, 26) if month == 1 else date(year, month - 1, 26)

#         employees = Employee.objects.filter(is_active=True).select_related('attendance_rule').annotate(
#             total_overtime=Coalesce(
#                 Sum('daily_attendance_records__overtime_hours',
#                     filter=Q(daily_attendance_records__date__gte=cycle_start, daily_attendance_records__date__lte=cycle_end)),
#                 Value(0.0), output_field=FloatField()
#             ),
#             total_absence=Count(
#                 'daily_attendance_records',
#                 filter=Q(daily_attendance_records__date__gte=cycle_start,
#                         daily_attendance_records__date__lte=cycle_end,
#                         daily_attendance_records__status='absent'),
#                 distinct=True
#             ),
#             total_penalty=Coalesce(
#                 Sum(
#                     Case(
#                         When(
#                             daily_attendance_records__status='absent',
#                             daily_attendance_records__administrative_penalty_days__gte=1.0,
#                             then=F('daily_attendance_records__administrative_penalty_days') - 1.0
#                         ),
#                         default=F('daily_attendance_records__administrative_penalty_days'),
#                         output_field=FloatField()
#                     ),
#                     filter=Q(daily_attendance_records__date__gte=cycle_start,
#                             daily_attendance_records__date__lte=cycle_end) &
#                           ~Q(daily_attendance_records__status__in=['mission', 'leave', 'holiday', 'permission', 'excused'])
#                 ),
#                 Value(0.0), output_field=FloatField()
#             ),
#             total_deduction_hours=Coalesce(
#                 Sum('daily_attendance_records__deduction_hours',
#                     filter=Q(daily_attendance_records__date__gte=cycle_start,
#                             daily_attendance_records__date__lte=cycle_end) &
#                           ~Q(daily_attendance_records__status__in=['mission', 'leave', 'holiday', 'permission', 'excused'])),
#                 Value(0.0), output_field=FloatField()
#             )
#         ).order_by('name')

#         penalty_records_totals = dict(
#             PenaltyRecord.objects.filter(date__gte=cycle_start, date__lte=cycle_end)
#             .values('employee_id')
#             .annotate(total=Sum('deduction_days'))
#             .values_list('employee_id', 'total')
#         )

#         payroll_records = []
#         total_company_base = total_company_overtime = total_company_deductions = total_company_net = 0.0

#         for employee in employees:
#             is_open_shift = (employee.attendance_rule and getattr(employee.attendance_rule, 'shift_type', '') == 'open')

#             total_absence_days = 0 if is_open_shift else employee.total_absence
#             total_deduction_hours = 0.0 if is_open_shift else employee.total_deduction_hours

#             attendance_penalty_days = 0.0 if is_open_shift else employee.total_penalty
#             admin_penalty_days = penalty_records_totals.get(employee.id, 0.0) or 0.0

#             total_penalty_days = attendance_penalty_days + admin_penalty_days

#             total_overtime_hours = employee.total_overtime
#             base_salary = float(employee.base_salary) if employee.base_salary else 0.0

#             # 🟢 المعالجة الجديدة: حساب نسبة الحضور وتطبيق مضاعف الجزاء
#             days_in_month_rule = 12.0 if (employee.attendance_rule and "12" in employee.attendance_rule.name) else 30.0
#             actual_attended_days = max(0.0, days_in_month_rule - total_absence_days)

#             if days_in_month_rule > 0 and actual_attended_days > 0:
#                 attendance_ratio = actual_attended_days / days_in_month_rule
#             elif days_in_month_rule > 0 and actual_attended_days == 0:
#                 attendance_ratio = 1.0 / days_in_month_rule  # الحد الأقصى للمضاعفة إذا غاب الشهر كله
#             else:
#                 attendance_ratio = 1.0

#             penalty_multiplier = 1.0 / attendance_ratio if attendance_ratio > 0 else 1.0

#             # المعدلات القياسية والمشددة
#             standard_day_rate = base_salary / days_in_month_rule if days_in_month_rule > 0 else 0.0
#             standard_hourly_rate = base_salary / 240.0

#             effective_day_rate = standard_day_rate * penalty_multiplier
#             effective_hourly_rate = standard_hourly_rate * penalty_multiplier

#             # الخصومات النهائية
#             absence_deduction = total_absence_days * standard_day_rate
#             penalty_deduction = total_penalty_days * effective_day_rate
#             late_deduction = total_deduction_hours * effective_hourly_rate

#             overtime_allowance = total_overtime_hours * standard_hourly_rate
#             insurance_monthly_deduction = float(employee.insurance_deduction) if employee.is_insured else 0.0

#             admin_deductions = late_deduction + absence_deduction + penalty_deduction
#             total_deductions_combined = admin_deductions + insurance_monthly_deduction

#             max_possible_deduction = base_salary + overtime_allowance
#             actual_total_deductions = min(total_deductions_combined, max_possible_deduction)

#             net_salary = max(0.0, base_salary + overtime_allowance - actual_total_deductions)

#             total_company_base += base_salary
#             total_company_overtime += overtime_allowance
#             total_company_deductions += actual_total_deductions
#             total_company_net += net_salary

#             payroll_records.append({
#                 'employee': employee,
#                 'base_salary': round(base_salary, 2),
#                 'overtime_hours': total_overtime_hours,
#                 'overtime_allowance': round(overtime_allowance, 2),
#                 'insurance_deduction': round(insurance_monthly_deduction, 2),
#                 'penalty_deduction': round(penalty_deduction, 2),
#                 'absence_deduction': round(absence_deduction, 2),
#                 'late_deduction': round(late_deduction, 2),
#                 'admin_deductions': round(admin_deductions, 2),
#                 'deductions': round(actual_total_deductions, 2),
#                 'net_salary': round(net_salary, 2),
#             })

#         context = {
#             'payroll_records': payroll_records,
#             'year': year,
#             'month': month,
#             'total_company_base': round(total_company_base, 2),
#             'total_company_overtime': round(total_company_overtime, 2),
#             'total_company_deductions': round(total_company_deductions, 2),
#             'total_company_net': round(total_company_net, 2),
#             'months_range': range(1, 13),
#             'years_range': range(today.year - 2, today.year + 3),
#         }
#         return render(request, 'hr/payroll_report.html', context)

#     except Exception as server_err:
#         print(f"❌ خطأ كشف الرواتب: {str(server_err)}")
#         raise server_err



# def export_payroll_excel(request, year, month):
#     year = int(year)
#     month = int(month)

#     cycle_end = date(year, month, 25)
#     cycle_start = date(year - 1, 12, 26) if month == 1 else date(year, month - 1, 26)

#     response = HttpResponse(content_type='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet')
#     response['Content-Disposition'] = f'attachment; filename="Payroll_Talaat_Harb_{year}_{month}.xlsx"'

#     wb = openpyxl.Workbook()
#     ws = wb.active
#     ws.title = f"مرتبات {month}-{year}"
#     ws.sheet_view.rightToLeft = True

#     title_font = Font(name='Arial', size=14, bold=True)
#     header_font = Font(name='Arial', size=12, bold=True)
#     normal_font = Font(name='Arial', size=11, bold=True)
#     center_aligned = Alignment(horizontal='center', vertical='center', wrap_text=True)
#     thin_border = Border(left=Side(style='thin'), right=Side(style='thin'), top=Side(style='thin'), bottom=Side(style='thin'))
#     header_fill = PatternFill(start_color='E2EFDA', end_color='E2EFDA', fill_type='solid')

#     ws.merge_cells('A1:C2')
#     ws['A1'].value = "محافظة القاهرة\nإدارة عين شمس التعليمية\nمدارس طلعت حرب الثانوية الفندقية"
#     ws['A1'].font = header_font; ws['A1'].alignment = center_aligned

#     ws.merge_cells('D1:O2')
#     ws['D1'].value = f"كشف مرتبات العاملين بالمدرسة عن دورة شهر {month} لعام {year} (من {cycle_start.strftime('%d/%m')} إلى {cycle_end.strftime('%d/%m')})"
#     ws['D1'].font = title_font; ws['D1'].alignment = center_aligned

#     headers = {
#         'A': 'م', 'B': 'الاســـــــــــــــم', 'C': 'الوظيفة', 'D': 'المرتب الأساسي',
#         'K': 'إضافي', 'L': 'إجمالي الخصومات', 'M': 'صافى المرتب', 'N': 'التوقيــع', 'O': 'ملاحظات'
#     }

#     for col, text in headers.items():
#         ws.merge_cells(f'{col}3:{col}4')
#         cell = ws[f'{col}3']
#         cell.value = text; cell.font = header_font; cell.alignment = center_aligned; cell.fill = header_fill; cell.border = thin_border
#         ws[f'{col}4'].border = thin_border

#     ws.merge_cells('E3:F3'); ws['E3'] = 'غياب'; ws['E3'].font = header_font; ws['E3'].alignment = center_aligned; ws['E3'].fill = header_fill; ws['E3'].border = thin_border
#     ws.merge_cells('G3:H3'); ws['G3'] = 'جزاءات وتحايل'; ws['G3'].font = header_font; ws['G3'].alignment = center_aligned; ws['G3'].fill = header_fill; ws['G3'].border = thin_border
#     ws.merge_cells('I3:J3'); ws['I3'] = 'تأخيرات'; ws['I3'].font = header_font; ws['I3'].alignment = center_aligned; ws['I3'].fill = header_fill; ws['I3'].border = thin_border

#     sub_headers = {'E': 'أيام', 'F': 'المبلغ', 'G': 'أيام', 'H': 'المبلغ', 'I': 'ساعات', 'J': 'المبلغ'}
#     for col, text in sub_headers.items():
#         cell = ws[f'{col}4']
#         cell.value = text; cell.font = Font(name='Arial', size=10, bold=True); cell.alignment = center_aligned; cell.fill = header_fill; cell.border = thin_border

#     ws.column_dimensions['B'].width = 30
#     for col in ['E', 'F', 'G', 'H', 'I', 'J']: ws.column_dimensions[col].width = 12

#     employees = Employee.objects.filter(is_active=True).select_related('department', 'attendance_rule').annotate(
#         total_overtime=Coalesce(
#             Sum('daily_attendance_records__overtime_hours',
#                 filter=Q(daily_attendance_records__date__gte=cycle_start, daily_attendance_records__date__lte=cycle_end)),
#             Value(0.0), output_field=FloatField()
#         ),
#         total_absence=Count(
#             'daily_attendance_records',
#             filter=Q(daily_attendance_records__date__gte=cycle_start,
#                     daily_attendance_records__date__lte=cycle_end,
#                     daily_attendance_records__status='absent'),
#             distinct=True
#         ),
#         total_penalty=Coalesce(
#             Sum(
#                 Case(
#                     When(
#                         daily_attendance_records__status='absent',
#                         daily_attendance_records__administrative_penalty_days__gte=1.0,
#                         then=F('daily_attendance_records__administrative_penalty_days') - 1.0
#                     ),
#                     default=F('daily_attendance_records__administrative_penalty_days'),
#                     output_field=FloatField()
#                 ),
#                 filter=Q(daily_attendance_records__date__gte=cycle_start,
#                         daily_attendance_records__date__lte=cycle_end) &
#                       ~Q(daily_attendance_records__status__in=['mission', 'leave', 'holiday', 'permission', 'excused'])
#             ),
#             Value(0.0), output_field=FloatField()
#         ),
#         total_deduction_hours=Coalesce(
#             Sum('daily_attendance_records__deduction_hours',
#                 filter=Q(daily_attendance_records__date__gte=cycle_start,
#                         daily_attendance_records__date__lte=cycle_end) &
#                       ~Q(daily_attendance_records__status__in=['mission', 'leave', 'holiday', 'permission', 'excused'])),
#             Value(0.0), output_field=FloatField()
#         )
#     ).order_by('name')

#     penalty_records_totals = dict(
#         PenaltyRecord.objects.filter(date__gte=cycle_start, date__lte=cycle_end)
#         .values('employee_id')
#         .annotate(total=Sum('deduction_days'))
#         .values_list('employee_id', 'total')
#     )

#     row_num = 5
#     total_base = total_overtime = total_deductions = total_net = 0.0
#     total_abs_days = total_abs_amt = total_pen_days = total_pen_amt = total_late_hrs = total_late_amt = 0.0

#     for index, emp in enumerate(employees, 1):
#         is_open_shift = (emp.attendance_rule and getattr(emp.attendance_rule, 'shift_type', '') == 'open')

#         absence_days = 0 if is_open_shift else emp.total_absence
#         late_hours = 0.0 if is_open_shift else emp.total_deduction_hours

#         attendance_penalties = 0.0 if is_open_shift else emp.total_penalty
#         admin_penalties = penalty_records_totals.get(emp.id, 0.0) or 0.0
#         penalty_days = attendance_penalties + admin_penalties

#         overtime_hours = emp.total_overtime
#         base_salary = float(emp.base_salary) if emp.base_salary else 0.0

#         # 🟢 تطبيق نفس معادلة المضاعفة الخاصة بنسبة الحضور للإكسيل
#         days_in_month_rule = 12.0 if (emp.attendance_rule and "12" in emp.attendance_rule.name) else 30.0
#         actual_attended_days = max(0.0, days_in_month_rule - absence_days)

#         if days_in_month_rule > 0 and actual_attended_days > 0:
#             attendance_ratio = actual_attended_days / days_in_month_rule
#         elif days_in_month_rule > 0 and actual_attended_days == 0:
#             attendance_ratio = 1.0 / days_in_month_rule
#         else:
#             attendance_ratio = 1.0

#         penalty_multiplier = 1.0 / attendance_ratio if attendance_ratio > 0 else 1.0

#         standard_day_rate = base_salary / days_in_month_rule if days_in_month_rule > 0 else 0.0
#         standard_hourly_rate = base_salary / 240.0

#         effective_day_rate = standard_day_rate * penalty_multiplier
#         effective_hourly_rate = standard_hourly_rate * penalty_multiplier

#         absence_deduction = absence_days * standard_day_rate
#         penalty_deduction = penalty_days * effective_day_rate
#         late_deduction = late_hours * effective_hourly_rate

#         overtime_allowance = overtime_hours * standard_hourly_rate
#         insurance_deduction = float(emp.insurance_deduction) if emp.is_insured else 0.0

#         initial_deductions = late_deduction + absence_deduction + penalty_deduction + insurance_deduction
#         max_possible_deduction = base_salary + overtime_allowance
#         actual_deductions = min(initial_deductions, max_possible_deduction)

#         net_salary = max(0.0, base_salary + overtime_allowance - actual_deductions)

#         total_base += base_salary
#         total_abs_days += absence_days
#         total_abs_amt += absence_deduction
#         total_pen_days += penalty_days
#         total_pen_amt += penalty_deduction
#         total_late_hrs += late_hours
#         total_late_amt += late_deduction
#         total_overtime += overtime_allowance
#         total_deductions += actual_deductions
#         total_net += net_salary

#         row_data = [
#             index, emp.name, emp.department.name if emp.department else '-', round(base_salary, 2),
#             absence_days if absence_days > 0 else '-', round(absence_deduction, 2) if absence_deduction > 0 else '-',
#             round(penalty_days, 2) if penalty_days > 0 else '-', round(penalty_deduction, 2) if penalty_deduction > 0 else '-',
#             round(late_hours, 2) if late_hours > 0 else '-', round(late_deduction, 2) if late_deduction > 0 else '-',
#             round(overtime_allowance, 2) if overtime_allowance > 0 else '-',
#             round(actual_deductions, 2) if actual_deductions > 0 else '-',
#             round(net_salary, 2), '', ''
#         ]

#         for col_idx, value in enumerate(row_data, 1):
#             cell = ws.cell(row=row_num, column=col_idx)
#             cell.value = value; cell.font = normal_font; cell.alignment = center_aligned; cell.border = thin_border

#         row_num += 1

#     ws.merge_cells(start_row=row_num, start_column=1, end_row=row_num, end_column=3)
#     ws.cell(row=row_num, column=1).value = "إجمالــى الكشف"
#     ws.cell(row=row_num, column=1).font = title_font; ws.cell(row=row_num, column=1).alignment = center_aligned
#     ws.cell(row=row_num, column=1).border = thin_border; ws.cell(row=row_num, column=1).fill = header_fill

#     ws.cell(row=row_num, column=2).border = thin_border
#     ws.cell(row=row_num, column=3).border = thin_border

#     totals_data = [
#         (4, total_base), (5, total_abs_days), (6, total_abs_amt),
#         (7, total_pen_days), (8, total_pen_amt), (9, total_late_hrs),
#         (10, total_late_amt), (11, total_overtime), (12, total_deductions), (13, total_net)
#     ]

#     for col_idx, total_val in totals_data:
#         cell = ws.cell(row=row_num, column=col_idx)
#         cell.value = round(total_val, 2) if total_val > 0 else '-'
#         cell.font = Font(name='Arial', size=11, bold=True, color='FF0000')
#         cell.alignment = center_aligned; cell.border = thin_border; cell.fill = header_fill

#     ws.cell(row=row_num, column=14).border = thin_border; ws.cell(row=row_num, column=14).fill = header_fill
#     ws.cell(row=row_num, column=15).border = thin_border; ws.cell(row=row_num, column=15).fill = header_fill

#     wb.save(response)
#     return response



def calculate_daily_attendance(employee, target_date, logs, preloaded_data):
    """
    دالة نقية (Pure Function) تُنفّذ في الذاكرة بزمن تنفيذ O(1) لحساب الحضور اليومي.
    """
    emp_id = employee.id
    rule = getattr(employee, 'attendance_rule', None)
    shift_type = getattr(rule, 'shift_type', 'fixed') if rule else 'fixed'

    # 0. حماية الموظفين المضافين حديثاً (تجاهل التواريخ السابقة للتعيين)
    hire_date = getattr(employee, 'hire_date', None)
    if hire_date and target_date < hire_date:
        return {
            'check_in': None, 'check_out': None, 'status': 'not_hired',
            'actual_work_hours': 0.0, 'overtime_hours': 0.0, 'late_minutes': 0,
            'deduction_hours': 0.0, 'administrative_penalty_days': 0.0, 'absence_deduction_days': 0.0
        }

    # 1. الاستعلام السريع O(1) من القواميس والمجموعات المحملة مسبقاً
    has_mission = (emp_id, target_date) in preloaded_data.get('missions_set', set())
    has_leave = (emp_id, target_date) in preloaded_data.get('leaves_set', set())
    has_permission = (emp_id, target_date) in preloaded_data.get('permissions_set', set())
    is_public_holiday = target_date in preloaded_data.get('public_holidays_set', set())
    is_working_day = preloaded_data.get('working_days_map', {}).get((emp_id, target_date), True)

    target_hours = float(getattr(rule, 'target_work_hours', 8.0)) if rule else 8.0

    # 2. الموظفون المستثنون من البصمة (الإدارة العليا / الدوام المفتوح)
    is_exempt = (shift_type == 'open') or getattr(employee, 'is_exempt_from_fingerprint', False)
    if is_exempt:
        check_in = min(logs).time() if logs else None
        check_out = max(logs).time() if logs else None
        return {
            'check_in': check_in, 'check_out': check_out, 'status': 'present',
            'actual_work_hours': target_hours, 'overtime_hours': 0.0, 'late_minutes': 0,
            'deduction_hours': 0.0, 'administrative_penalty_days': 0.0, 'absence_deduction_days': 0.0
        }

    # 3. أيام العطلات (الأسبوعية أو الرسمية)
    if not is_working_day or is_public_holiday:
        log_count = len({log.time().replace(second=0, microsecond=0) for log in logs}) if logs else 0
        actual_hours = 0.0
        overtime_hours = 0.0

        if log_count > 1:
            actual_hours = (max(logs) - min(logs)).total_seconds() / 3600.0
            overtime_hours = actual_hours
        elif log_count == 1:
            actual_hours = target_hours if shift_type == 'flexible' else 0.0

        return {
            'check_in': min(logs).time() if logs else None,
            'check_out': max(logs).time() if logs else None,
            'status': 'holiday',
            'actual_work_hours': round(actual_hours, 2),
            'overtime_hours': round(overtime_hours, 2),
            'late_minutes': 0, 'deduction_hours': 0.0,
            'administrative_penalty_days': 0.0, 'absence_deduction_days': 0.0
        }

    # 4. حالات المأموريات والإجازات
    if has_mission:
        return {
            'check_in': min(logs).time() if logs else None,
            'check_out': max(logs).time() if logs else None,
            'status': 'mission', 'actual_work_hours': target_hours, 'overtime_hours': 0.0,
            'late_minutes': 0, 'deduction_hours': 0.0, 'administrative_penalty_days': 0.0, 'absence_deduction_days': 0.0
        }

    if has_leave and not logs:
        return {
            'check_in': None, 'check_out': None, 'status': 'leave',
            'actual_work_hours': 0.0, 'overtime_hours': 0.0, 'late_minutes': 0,
            'deduction_hours': 0.0, 'administrative_penalty_days': 0.0, 'absence_deduction_days': 0.0
        }

    # 5. الأذونات المعتمَدة
    if has_permission:
        return {
            'check_in': min(logs).time() if logs else None,
            'check_out': max(logs).time() if logs else None,
            'status': 'present', 'actual_work_hours': target_hours, 'overtime_hours': 0.0,
            'late_minutes': 0, 'deduction_hours': 0.0, 'administrative_penalty_days': 0.0, 'absence_deduction_days': 0.0
        }

    # 6. حالة عدم وجود بصمات نهائياً
    if not logs:
        return {
            'check_in': None, 'check_out': None, 'status': 'absent',
            'actual_work_hours': 0.0, 'overtime_hours': 0.0, 'late_minutes': 0,
            'deduction_hours': 0.0, 'administrative_penalty_days': 3.0, 'absence_deduction_days': 1.0
        }

    # 7. تحليل البصمات (بصمتان أو أكثر)
    check_in_dt = min(logs)
    check_out_dt = max(logs)
    log_count = len({log.time().replace(second=0, microsecond=0) for log in logs})

    if log_count == 1:
        return {
            'check_in': check_in_dt.time(), 'check_out': None, 'status': 'absent',
            'actual_work_hours': 0.0, 'overtime_hours': 0.0, 'late_minutes': 0,
            'deduction_hours': 0.0, 'administrative_penalty_days': 3.0, 'absence_deduction_days': 0.0
        }

    actual_hours = (check_out_dt - check_in_dt).total_seconds() / 3600.0
    late_minutes = 0
    deduction_hours = 0.0

    # أ) الدوام المرن
    if shift_type == 'flexible':
        if actual_hours < target_hours:
            multiplier = getattr(rule, 'late_deduction_multiplier', 1.0) if rule else 1.0
            deduction_hours = (target_hours - actual_hours) * multiplier

    # ب) الدوام الثابت والورديات الليلية
    elif shift_type == 'fixed' and rule:
        rule_start_time = getattr(rule, 'work_start_time', time(8, 0))
        rule_end_time = getattr(rule, 'work_end_time', time(16, 0))
        grace_period = getattr(rule, 'grace_period', 0)
        multiplier = getattr(rule, 'late_deduction_multiplier', 1.0)

        shift_start_dt = datetime.combine(target_date, rule_start_time)
        shift_end_dt = datetime.combine(target_date, rule_end_time)

        if rule_end_time <= rule_start_time:
            shift_end_dt += timedelta(days=1)

        if check_in_dt > shift_start_dt:
            diff_seconds = (check_in_dt - shift_start_dt).total_seconds()
            late_minutes = int(diff_seconds / 60)
            if late_minutes > grace_period:
                deduction_hours += (late_minutes / 60.0) * multiplier

        if check_out_dt < shift_end_dt:
            early_exit_minutes = int((shift_end_dt - check_out_dt).total_seconds() / 60)
            deduction_hours += (early_exit_minutes / 60.0) * multiplier

    return {
        'check_in': check_in_dt.time(),
        'check_out': check_out_dt.time(),
        'status': 'present',
        'actual_work_hours': round(actual_hours, 2),
        'overtime_hours': 0.0,
        'late_minutes': late_minutes,
        'deduction_hours': round(deduction_hours, 2),
        'administrative_penalty_days': 0.0,
        'absence_deduction_days': 0.0
    }


def upload_and_process_attendance(request):
    if request.method == 'POST' and request.FILES.get('file'):
        uploaded_file = request.FILES['file']

        try:
            logs_by_emp_and_date = {}
            distinct_dates = set()

            active_emps = list(Employee.objects.filter(is_active=True).select_related('attendance_rule'))
            emp_dict_by_emp_id = {str(emp.emp_id).strip(): emp for emp in active_emps if getattr(emp, 'emp_id', None)}
            emp_dict_by_id = {str(emp.id): emp for emp in active_emps}

            # 🟢 1. بناء مجموعات البحث وتحويل نطاقات التواريخ إلى تواريخ منفردة
            raw_missions = list(MissionRequest.objects.filter(status='approved').values('employee_id', 'start_date', 'end_date'))
            raw_leaves = list(LeaveRequest.objects.filter(status='approved').values('employee_id', 'start_date', 'end_date'))
            raw_permissions = list(PermissionRequest.objects.filter(status='approved').values('employee_id', 'date'))
            raw_holidays = list(PublicHoliday.objects.values('start_date', 'end_date'))

            missions_set = set()
            for m in raw_missions:
                curr = m['start_date']
                while curr <= m['end_date']:
                    missions_set.add((m['employee_id'], curr))
                    curr += timedelta(days=1)

            leaves_set = set()
            for l in raw_leaves:
                curr = l['start_date']
                while curr <= l['end_date']:
                    leaves_set.add((l['employee_id'], curr))
                    curr += timedelta(days=1)

            permissions_set = {(p['employee_id'], p['date']) for p in raw_permissions}

            public_holidays_set = set()
            for h in raw_holidays:
                curr = h['start_date']
                while curr <= h['end_date']:
                    public_holidays_set.add(curr)
                    curr += timedelta(days=1)

            # 🟢 2. معالجة ملف البصمة الخام (.dat)
            if uploaded_file.name.endswith('.dat'):
                lines = uploaded_file.read().decode('utf-8').splitlines()
                for line in lines:
                    parts = line.split()
                    if len(parts) >= 2:
                        emp_code = parts[0].strip()
                        date_time_str = f"{parts[1]} {parts[2]}" if len(parts) > 2 else parts[1]
                        try:
                            ts = pd.to_datetime(date_time_str)
                            parsed_date = ts.date()
                            distinct_dates.add(parsed_date)
                            employee = emp_dict_by_emp_id.get(emp_code) or (emp_dict_by_id.get(emp_code) if emp_code.isdigit() else None)
                            if employee:
                                key = (employee, parsed_date)
                                logs_by_emp_and_date.setdefault(key, []).append(ts.to_pydatetime())
                        except Exception:
                            continue

            # 🔵 3. معالجة ملفات Excel و CSV
            elif uploaded_file.name.endswith(('.xlsx', '.xls', '.csv')):
                df = pd.read_csv(uploaded_file) if uploaded_file.name.endswith('.csv') else pd.read_excel(uploaded_file)
                df.columns = df.columns.str.strip()

                for row in df.itertuples(index=False):
                    row_dict = row._asdict()
                    raw_emp_code = str(row_dict.get('AC-No.', row_dict.get('AC.No.', ''))).strip()
                    date_str = str(row_dict.get('Date', '')).strip()

                    if not raw_emp_code or raw_emp_code == 'nan' or not date_str or date_str == 'nan':
                        continue

                    emp_code = raw_emp_code.split('.')[0]
                    try:
                        ts = pd.to_datetime(date_str)
                        parsed_date = ts.date()
                        distinct_dates.add(parsed_date)
                    except Exception:
                        continue

                    employee = emp_dict_by_emp_id.get(emp_code) or (emp_dict_by_id.get(emp_code) if emp_code.isdigit() else None)
                    if not employee or str(row_dict.get('Absent', '')).strip().lower() == 'true':
                        continue

                    clock_in_str = str(row_dict.get('Clock In', '')).strip()
                    clock_out_str = str(row_dict.get('Clock Out', '')).strip()
                    key = (employee, parsed_date)

                    for time_str in [clock_in_str, clock_out_str]:
                        if time_str and time_str != 'nan':
                            try:
                                t_parsed = pd.to_datetime(time_str)
                                dt_combined = datetime.combine(parsed_date, t_parsed.time())
                                logs_by_emp_and_date.setdefault(key, []).append(dt_combined)
                            except Exception:
                                pass
            else:
                messages.error(request, "صيغة الملف غير مدعومة! يجب أن يكون الملف DAT, Excel, أو CSV.")
                return redirect('hr:upload_attendance')

            if not distinct_dates:
                messages.warning(request, "تم قراءة الملف ولكن لم يتم العثور على أي تواريخ صالحة.")
                return redirect('hr:attendance_list')

            # 🟢 4. خريطة أيام العمل الأسبوعية بناءً على التواريخ المستخرجة
            working_days_map = {}
            for emp in active_emps:
                rule = getattr(emp, 'attendance_rule', None)
                work_days = getattr(rule, 'work_days', [0, 1, 2, 3, 4, 6]) if rule else [0, 1, 2, 3, 4]
                for d in distinct_dates:
                    working_days_map[(emp.id, d)] = d.weekday() in work_days

            preloaded_data = {
                'missions_set': missions_set,
                'leaves_set': leaves_set,
                'permissions_set': permissions_set,
                'public_holidays_set': public_holidays_set,
                'working_days_map': working_days_map,
            }

            # ⚡ 5. المعالجة المجمعة والحفظ بـ Bulk Operations
            existing_records = {
                (att.employee_id, att.date): att
                for att in DailyAttendance.objects.filter(date__in=distinct_dates)
            }

            to_create = []
            to_update = []

            all_target_combinations = set(logs_by_emp_and_date.keys())
            for target_date in distinct_dates:
                for emp in active_emps:
                    all_target_combinations.add((emp, target_date))

            for (employee, target_date) in all_target_combinations:
                logs = logs_by_emp_and_date.get((employee, target_date), [])

                calculated_values = calculate_daily_attendance(
                    employee=employee,
                    target_date=target_date,
                    logs=logs,
                    preloaded_data=preloaded_data
                )

                # استثناء الموظفين غير المعينين في ذلك التاريخ من إنشاء سجلات
                if calculated_values.get('status') == 'not_hired':
                    continue

                record_key = (employee.id, target_date)
                if record_key in existing_records:
                    obj = existing_records[record_key]
                    for field, val in calculated_values.items():
                        setattr(obj, field, val)
                    to_update.append(obj)
                else:
                    to_create.append(DailyAttendance(
                        employee=employee,
                        date=target_date,
                        **calculated_values
                    ))

            with transaction.atomic():
                if to_create:
                    DailyAttendance.objects.bulk_create(to_create, batch_size=1000)
                if to_update:
                    update_fields = [
                        'check_in', 'check_out', 'status', 'actual_work_hours',
                        'overtime_hours', 'late_minutes', 'deduction_hours',
                        'administrative_penalty_days', 'absence_deduction_days'
                    ]
                    DailyAttendance.objects.bulk_update(to_update, update_fields, batch_size=1000)

            total_processed = len(to_create) + len(to_update)
            messages.success(request, f"تمت المعالجة بنجاح! تم تحديث/إنشاء {total_processed} سجل بسرعة فائقة.")
            return redirect('hr:attendance_list')

        except Exception as e:
            messages.error(request, f"حدث خطأ أثناء معالجة الملف: {str(e)}")
            return redirect('hr:upload_attendance')

    from .forms import UploadAttendanceForm
    form = UploadAttendanceForm()
    return render(request, 'hr/upload_attendance.html', {'form': form})


def get_payroll_period(target_date):
    """
    تحدد بداية ونهاية الشهر المالي بناءً على دورة (26 من الشهر السابق -> 25 من الشهر الحالي)
    """
    if target_date.day >= 26:
        start_date = target_date.replace(day=26)
        # الشهر التالي
        if target_date.month == 12:
            end_date = target_date.replace(year=target_date.year + 1, month=1, day=25)
        else:
            end_date = target_date.replace(month=target_date.month + 1, day=25)
    else:
        end_date = target_date.replace(day=25)
        # الشهر السابق
        if target_date.month == 1:
            start_date = target_date.replace(year=target_date.year - 1, month=12, day=26)
        else:
            start_date = target_date.replace(month=target_date.month - 1, day=26)

    return start_date, end_date


def validate_permission_quota(employee_id, request_date):
    """
    تتحقق مما إذا كان الموظف قد استهلك إذن الشهر بالفعل خلال دورة (26 -> 25)
    """
    start_date, end_date = get_payroll_period(request_date)
    existing_permissions_count = PermissionRequest.objects.filter(
        employee_id=employee_id,
        status='approved',
        date__gte=start_date,
        date__lte=end_date
    ).count()

    return existing_permissions_count < 1  # يرجع True إذا كان يستحق الإذن


def prepare_preloaded_data(start_date, end_date):
    """
    تجهيز البيانات في الذاكرة بصيغة Hash Sets / Dicts للوصول في زمن O(1)
    """
    # 1. الأذونات المعتمدة فقط مع تطبيق دورة الشهر (26 الشهر الماضي إلى 25 الشهر الحالي)
    approved_permissions = PermissionRequest.objects.filter(
        status='approved',
        date__range=(start_date, end_date)
    ).values_list('employee_id', 'date')

    # 2. المأموريات
    missions = MissionRequest.objects.filter(
        status='approved',
        start_date__lte=end_date, end_date__gte=start_date
    ).values('employee_id', 'start_date', 'end_date')

    missions_set = set()
    for m in missions:
        # إضافة كل الأيام الواقعة في نطاق المأمورية
        curr = max(m['start_date'], start_date)
        last = min(m['end_date'], end_date)
        while curr <= last:
            missions_set.add((m['employee_id'], curr))
            curr += timedelta(days=1)

    # 3. الإجازات
    leaves = LeaveRequest.objects.filter(
        status='approved',
        start_date__lte=end_date, end_date__gte=start_date
    ).values('employee_id', 'start_date', 'end_date')

    leaves_set = set()
    for l in leaves:
        curr = max(l['start_date'], start_date)
        last = min(l['end_date'], end_date)
        while curr <= last:
            leaves_set.add((l['employee_id'], curr))
            curr += timedelta(days=1)

    # 4. العطلات الرسمية
    holidays = PublicHoliday.objects.filter(
        start_date__lte=end_date, end_date__gte=start_date
    ).values('start_date', 'end_date')

    public_holidays_set = set()
    for h in holidays:
        curr = max(h['start_date'], start_date)
        last = min(h['end_date'], end_date)
        while curr <= last:
            public_holidays_set.add(curr)
            curr += timedelta(days=1)

    return {
        'permissions_set': set(approved_permissions), # {(emp_id, date), ...}
        'missions_set': missions_set,                 # {(emp_id, date), ...}
        'leaves_set': leaves_set,                     # {(emp_id, date), ...}
        'public_holidays_set': public_holidays_set,   # {date, ...}
    }








def employee_create_view(request):
    if request.method == 'POST':
        form = EmployeeForm(request.POST, request.FILES) # تأكد من اسم الفورم لديك
        if form.is_valid():
            form.save()
            messages.success(request, 'تم إضافة الموظف بنجاح! يمكنك الآن إضافة موظف آخر.')

            # 🟢 التعديل هنا: نجعله يعود لنفس مسار صفحة الإضافة لكي تفتح فارغة من جديد
            return redirect('hr:employee_create')
    else:
        form = EmployeeForm()

    # وهنا السطر الذي قمنا بتصحيحه في الخطوة السابقة ليفتح التصميم الصحيح
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



# 1. حساب مسيرات الرواتب الشهرية مرنة المعاملات (محدثة بالقانون الديناميكي والجزاءات)
def calculate_monthly_salary(request, employee_id, year, month):
    from calendar import monthrange
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

    # 🟢 حساب أيام الإجازة المرضية المعتمدة الواقعة داخل هذا الشهر (تُخصم من الراتب
    # يوماً بيوم تماماً مثل الغياب: يوم مرضي = خصم يوم، يومين مرضي = خصم يومين... إلخ)
    month_start = date(year, month, 1)
    month_end = date(year, month, monthrange(year, month)[1])
    sick_leaves_this_month = LeaveRequest.objects.filter(
        employee=employee,
        leave_type='sick',
        status='approved',
        start_date__lte=month_end,
        end_date__gte=month_start,
    )
    total_sick_days = 0
    for lv in sick_leaves_this_month:
        overlap_start = max(lv.start_date, month_start)
        overlap_end = min(lv.end_date, month_end)
        total_sick_days += (overlap_end - overlap_start).days + 1

    # 🔴 1. تجميع كل أيام الجزاء الصارمة التي تم توقيعها على الموظف خلال الشهر
    total_penalty_days = attendances.aggregate(Sum('administrative_penalty_days'))['administrative_penalty_days__sum'] or 0.0

    # 🟢 إضافة أيام خصم الجزاءات الإدارية الموقّعة (PenaltyRecord) لنفس الشهر
    penalty_records_this_month = PenaltyRecord.objects.filter(
        employee=employee, date__year=year, date__month=month
    )
    total_penalty_record_days = penalty_records_this_month.aggregate(
        Sum('deduction_days')
    )['deduction_days__sum'] or 0.0
    total_penalty_days += total_penalty_record_days

    base_salary = float(employee.base_salary) if employee.base_salary else 0.0

    # 1. حساب خصم الغياب المباشر (بناءً على 30 يوماً كشهر محاسبي ثابت)
    # حساب أجر اليوم بناءً على اللائحة (12 يوم أو 30 يوم)
    days_in_month_rule = 12 if (employee.attendance_rule and "12" in employee.attendance_rule.name) else 30.0
    day_rate = base_salary / days_in_month_rule
    absent_multiplier = float(employee.attendance_rule.absent_deduction_days) if employee.attendance_rule else 1.0
    absence_deduction = total_absence_days * day_rate * absent_multiplier

    # 🟢 خصم الإجازة المرضية (يوم بيوم بدون معامل مضاعف، بعكس الغياب بدون إذن)
    sick_deduction = total_sick_days * day_rate

    # 🔴 2. حساب قيمة الجزاءات الإدارية المادية (أيام الجزاء × أجر اليوم)
    penalty_deduction = total_penalty_days * day_rate

    # 3. 🟢 حساب خصم التأخير الديناميكي (تتضخم قيمة ساعة الخصم كلما زاد الغياب)
    actual_working_days = 30 - total_absence_days
    if actual_working_days > 0:
        dynamic_delay_rate = base_salary / actual_working_days
        late_deduction = total_deductions_hours * dynamic_delay_rate
    else:
        # حماية برمجية لتجنب القسمة على صفر إذا غاب الموظف طوال الشهر
        late_deduction = 0.0

    # 4. حساب قيمة الإضافي (بناءً على افتراض 240 ساعة عمل شهرياً)
    hourly_rate_standard = base_salary / 240.0
    overtime_allowance = total_overtime * hourly_rate_standard

    # 🛡️ محرك فحص واحتساب البيانات التأمينية المضافة حديثاً للموظف
    if employee.is_insured:
        ins_basic = float(employee.insurance_basic_salary or 0.0)
        ins_allowance = float(employee.insurance_variable_allowance or 0.0)
        ins_deduction = float(employee.insurance_deduction or 0.0)
        ins_number = employee.insurance_number
    else:
        ins_basic = 0.0
        ins_allowance = 0.0
        ins_deduction = 0.0
        ins_number = "غير مؤمن عليه"

    # 🔴 5. صافي الراتب النهائي بعد التسويات وخصم الاستقطاع التأميني والجزاءات الإدارية
    net_salary = base_salary + overtime_allowance - late_deduction - absence_deduction - sick_deduction - penalty_deduction - ins_deduction

    context = {
        'employee': employee,
        'base_salary': employee.base_salary,
        'overtime_allowance': round(overtime_allowance, 2),
        'late_deduction': round(late_deduction, 2),
        'absence_deduction': round(absence_deduction, 2),
        'sick_deduction': round(sick_deduction, 2),
        'total_sick_days': total_sick_days,
        'penalty_deduction': round(penalty_deduction, 2), # 👈 تمرير قيمة الجزاء للتمبلت لطباعتها في مفردات الراتب
        'penalty_records': penalty_records_this_month, # 🟢 تفاصيل كل جزاء موقّع (نوعه وسببه ويوم خصمه) لعرضها في القسيمة

        # 🛡️ إرسال المت المتغيرات التأمينية الجديدة لكي تظهر في صفحة مفردات الراتب (payroll_slip.html)
        'is_insured': employee.is_insured,
        'insurance_number': ins_number,
        'insurance_basic_salary': round(ins_basic, 2),
        'insurance_variable_allowance': round(ins_allowance, 2),
        'insurance_deduction': round(ins_deduction, 2),

        'net_salary': round(net_salary, 2),
    }
    return render(request, 'hr/payroll_slip.html', context)




# def process_daily_attendance_for_employee(employee, target_date, logs, preloaded_data=None):
#     rule = employee.attendance_rule

#     # 1. فحص وجود مأمورية، إجازة، إذن، أو عطلة رسمية في هذا اليوم
#     # 🟢 استخدام التخزين المؤقت للسرعة الصاروخية أثناء المعالجة المجمعة
#     if preloaded_data:
#         has_mission = any(m.employee == employee and m.start_date <= target_date <= m.end_date for m in preloaded_data['missions'])
#         has_leave = any(l.employee == employee and l.start_date <= target_date <= l.end_date for l in preloaded_data['leaves'])
#         has_permission = any(p.employee == employee and p.date == target_date for p in preloaded_data['permissions'])
#         is_public_holiday = any(h.start_date <= target_date <= h.end_date for h in preloaded_data['holidays'])
#     else:
#         # الوضع العادي في حالة تم استدعاء الدالة بشكل فردي
#         has_mission = MissionRequest.objects.filter(employee=employee, start_date__lte=target_date, end_date__gte=target_date, status='approved').exists()
#         has_leave = LeaveRequest.objects.filter(employee=employee, start_date__lte=target_date, end_date__gte=target_date, status='approved').exists()
#         has_permission = PermissionRequest.objects.filter(employee=employee, date=target_date, status='approved').exists()
#         is_public_holiday = PublicHoliday.objects.filter(start_date__lte=target_date, end_date__gte=target_date).exists()

#     # 2. أيام العطلات الأسبوعية لا تُعالج ما لم يبصم فيها
#     if not employee.check_is_working_day(target_date):
#         if not logs:
#             DailyAttendance.objects.update_or_create(employee=employee, date=target_date, defaults={'status': 'holiday'})
#             return

#     # 3. 🛡️ حماية المأموريات (لا تخضع لأي جزاء وتعتبر حضوراً كاملاً)
#     if has_mission:
#         DailyAttendance.objects.update_or_create(
#             employee=employee, date=target_date,
#             defaults={'status': 'mission', 'administrative_penalty_days': 0.0, 'late_minutes': 0, 'deduction_hours': 0.0, 'absence_deduction_days': 0.0}
#         )
#         return

#     # 4. معالجة الغياب (عدم وجود بصمات نهائياً)
#     if not logs:
#         if has_leave:
#             DailyAttendance.objects.update_or_create(
#                 employee=employee, date=target_date,
#                 defaults={'status': 'leave', 'administrative_penalty_days': 0.0}
#             )
#         elif is_public_holiday:
#             DailyAttendance.objects.update_or_create(
#                 employee=employee, date=target_date,
#                 defaults={'status': 'holiday', 'administrative_penalty_days': 0.0}
#             )
#         else:
#             DailyAttendance.objects.update_or_create(
#                 employee=employee, date=target_date,
#                 defaults={'status': 'absent', 'administrative_penalty_days': 3.0}
#             )
#         return

#     # 5. معالجة الحضور (تحليل البصمات)
#     check_in_dt = min(logs)
#     check_out_dt = max(logs)
#     check_in = check_in_dt.time()
#     check_out = check_out_dt.time()

#     admin_penalty = 0.0
#     late_minutes = 0
#     deduction_hours = 0.0

#     status = 'holiday' if is_public_holiday else 'present'

#     log_count = len(set([log.time().replace(second=0, microsecond=0) for log in logs]))

#     # 🟢 تعديل الدوام المرن: إذا كان الدوام مرن، يكفي بصمة واحدة لنعتبره أكمل الساعات
#     is_flexible = (getattr(rule, 'shift_type', '') == 'flexible')
#     target_hours = float(rule.target_work_hours) if getattr(rule, 'target_work_hours', None) else 8.0

#     if is_flexible and log_count >= 1:
#         # الدوام المرن: بصمة واحدة أو أكثر تعني حضور كامل المدة
#         actual_hours = target_hours
#     else:
#         # الدوام الثابت: يتطلب بصمتين لحساب الساعات الفعلية
#         actual_hours = (check_out_dt - check_in_dt).total_seconds() / 3600.0 if log_count > 1 else 0.0

#     overtime_hours = 0.0

#     # 🔴 فحص بصمة واحدة (للدوام الثابت فقط)
#     if log_count == 1:
#         if is_flexible:
#             # تم الإعفاء: الدوام المرن لا يعاقب على بصمة واحدة
#             pass
#         elif has_permission or is_public_holiday:
#             # لديه إذن معتمد أو اليوم عطلة رسمية: يُعفى من جزاء البصمة الواحدة
#             pass
#         else:
#             # الدوام الثابت وليس لديه إذن: بصمة واحدة = 3 أيام جزاء
#             admin_penalty = 3.0
#             status = 'absent'

#     # 🔴 فحص التأخيرات (للدوام الثابت فقط) - النسخة الاحترافية المعدلة
#     if not is_flexible and getattr(rule, 'shift_type', '') == 'fixed' and log_count > 1 and not is_public_holiday:
#         rule_start = rule.work_start_time
#         if check_in > rule_start:
#             diff = datetime.combine(target_date, check_in) - datetime.combine(target_date, rule_start)
#             late_minutes = int(diff.total_seconds() / 60)

#             if late_minutes > rule.grace_period:
#                 # 🟢 تحويل كل دقائق التأخير إلى كسر عشري تراكمي (مثال: 59 دقيقة = 0.98)
#                 # ليتم ضربها لاحقاً في محرك الرواتب بالمعادلة الديناميكية التي اخترتها
#                 deduction_hours = (late_minutes / 60.0) * rule.late_deduction_multiplier
#         from datetime import time
#         if check_out < time(14, 0):
#             admin_penalty = 3.0  # توقيع جزاء 3 أيام فوراً
#             status = 'absent'    # تحويل حالة اليوم إلى غياب رغم وجود بصمتين
#             deduction_hours = 0.0 # تصفير ساعات التأخير الصباحية (إن وجدت) لعدم ازدواجية الخصم    # تم إزالة شرط الـ 30 دقيقة والجزاء الإداري القاطع، ليصبح النظام أكثر مرونة وعدلاً

#     # 🔵 فحص نقص الساعات (للدوام المرن)
#     elif is_flexible and log_count > 1 and not is_public_holiday:
#         actual_hours = (check_out_dt - check_in_dt).total_seconds() / 3600.0
#         if actual_hours < target_hours:
#             shortfall_hours = target_hours - actual_hours
#             deduction_hours = shortfall_hours * rule.late_deduction_multiplier

#     # 🟢 حساب الإضافي (Overtime) لمن عمل في عطلة رسمية
#     if is_public_holiday and log_count > 1:
#         overtime_hours = (check_out_dt - check_in_dt).total_seconds() / 3600.0
#     elif is_public_holiday and is_flexible and log_count == 1:
#         overtime_hours = target_hours

#     # الحفظ النهائي في الداتابيز
#     DailyAttendance.objects.update_or_create(
#         employee=employee, date=target_date,
#         defaults={
#             'check_in': check_in,
#             'check_out': check_out,
#             'status': status,
#             'actual_work_hours': round(actual_hours, 2),
#             'overtime_hours': round(overtime_hours, 2),
#             'late_minutes': late_minutes,
#             'deduction_hours': round(deduction_hours, 2),
#             'administrative_penalty_days': admin_penalty,
#             'absence_deduction_days': 0.0
#         }
#     )




def employee_list(request):
    try:
        # 1. جلب الموظفين والأقسام في استعلام واحد محسن وترتيبهم أبجدياً
        employees_query = Employee.objects.all().select_related('department').order_by('name')
        employees = list(employees_query)  # تثبيت في الذاكرة سريعة القراءة
        departments = Department.objects.all()

        # 2. جلب طلبات الإجازات لجدول الإجازات وتثبيتها
        leave_requests_query = LeaveRequest.objects.all().select_related('employee').order_by('employee__name', '-id')
        leave_requests = list(leave_requests_query)  # تثبيت في الذاكرة

        # 3. جلب معاملات البحث والفلترة من الرابط
        date_param = request.GET.get('date')
        search_query = request.GET.get('q', '').strip()  # جلب كلمة البحث (اسم أو كود الموظف)

        # الاستعلام الأساسي (كل السجلات مرتبة تنازلياً)
        attendance_query = DailyAttendance.objects.all().select_related('employee').order_by('-date', 'employee__name')

        # 🟢 تطبيق فلتر التاريخ (إذا اختار المستخدم تاريخاً محدداً)
        if date_param:
            try:
                target_date = pd.to_datetime(date_param).date()
                attendance_query = attendance_query.filter(date=target_date)
            except:
                target_date = timezone.now().date()
        else:
            target_date = ""  # نتركها فارغة لكي يظهر Placeholder في الفلتر

        # 🔍 تطبيق فلتر البحث الذكي الفصل بين كود البصمة والاسم
        if search_query:
            if search_query.isdigit():
                # 🟢 مطابقة تامة Exact Match لكود البصمة إذا كان المدخل رقماً
                attendance_query = attendance_query.filter(employee__emp_id=search_query)
            else:
                # 🔵 بحث مرن بالهمزات والحروف المتشابهة لاسم الموظف إذا كان المدخل نصاً
                pattern = search_query
                pattern = re.sub(r'[اأإآ]', r'[اأإآ]', pattern)
                pattern = re.sub(r'[هة]', r'[هة]', pattern)
                pattern = re.sub(r'[يى]', r'[يى]', pattern)

                attendance_query = attendance_query.filter(
                    Q(employee__name__iregex=pattern)
                )

        # 4. تفعيل جلب السجلات والترقيم (Pagination) لعدم إرهاق المتصفح (50 سجل لكل صفحة)
        paginator = Paginator(attendance_query, 50)
        page_number = request.GET.get('page')
        attendance_page = paginator.get_page(page_number)

        # حساب إحصائيات اليوم الحالي للوحة القيادة (للحفاظ على دقة العدادات)
        today = timezone.now().date()
        today_attendance_count = DailyAttendance.objects.filter(date=today, status__in=['present', 'late']).count()
        today_late_count = DailyAttendance.objects.filter(date=today, late_minutes__gt=0).count()

    except Exception as e:
        print(f"🔴 خطأ داخلي في الـ View: {str(e)}")
        employees, departments, leave_requests = [], [], []
        attendance_page = []
        target_date = timezone.now().date()
        today_attendance_count, today_late_count = 0, 0

    # ⚡ الحساب الذكي الفائق السرعة داخل الذاكرة (0 استعلامات SQL إضافية)
    total_emp = len(employees)
    pending_leaves = sum(1 for l in leave_requests if l.status == 'pending')

    # تحديد التبويب النشط ذكياً (إذا بحث أو فلتر، يبقى في تبويب الحضور)
    tab_param = request.GET.get('tab')
    if tab_param:
        active_tab = tab_param
    elif request.GET.get('date') or request.GET.get('page') or request.GET.get('q'):
        active_tab = 'attendance'
    else:
        active_tab = 'dashboard'

    context = {
        'employees': employees,
        'departments': departments,
        'leave_requests': leave_requests,
        'attendance': attendance_page, # 🚀 تمرير كائن الـ Paginator
        'latest_attendance': attendance_page.object_list[:5] if attendance_page else [], # أخذ أول 5 عناصر

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
    today = timezone.localdate()

    target_month = int(request.GET.get('month', today.month))
    target_year = int(request.GET.get('year', today.year))
    search_query = request.GET.get('q', '').strip()

    prev_month = target_month - 1 if target_month > 1 else 12
    prev_year = target_year if target_month > 1 else target_year - 1

    cycle_start = date(prev_year, prev_month, 26)
    cycle_end = date(target_year, target_month, 25)

    attendance_query = DailyAttendance.objects.select_related('employee').filter(
        date__gte=cycle_start,
        date__lte=cycle_end
    )

    if search_query:
        if search_query.isdigit():
            attendance_query = attendance_query.filter(employee__emp_id=search_query)
        else:
            pattern = search_query
            pattern = re.sub(r'[اأإآ]', r'[اأإآ]', pattern)
            pattern = re.sub(r'[هة]', r'[هة]', pattern)
            pattern = re.sub(r'[يى]', r'[يى]', pattern)
            attendance_query = attendance_query.filter(Q(employee__name__iregex=pattern))

    attendance_query = attendance_query.order_by('employee__name', 'date')

    paginator = Paginator(attendance_query, 50)
    page_number = request.GET.get('page')
    attendance = paginator.get_page(page_number)

    # 🟢 جلب وقرن الجزاءات الإدارية المباشرة (PenaltyRecord) لكل يوم
    page_records = list(attendance.object_list)
    if page_records:
        emp_ids = {r.employee_id for r in page_records}
        penalties = PenaltyRecord.objects.filter(
            employee_id__in=emp_ids,
            date__gte=cycle_start,
            date__lte=cycle_end
        )

        # خريطة للجزاءات الإدارية بحسب الموظف والتاريخ
        penalties_map = {}
        for p in penalties:
            key = (p.employee_id, p.date)
            penalties_map[key] = penalties_map.get(key, 0.0) + float(p.deduction_days)

        # دمج الجزاء الإداري مع جزاء التحايل ليظهرا معاً
        for r in page_records:
            admin_p = penalties_map.get((r.employee_id, r.date), 0.0)
            r.direct_admin_penalty = admin_p
            r.total_day_penalty = float(r.administrative_penalty_days) + admin_p

    context = {
        'attendance': attendance,
        'month': target_month,
        'year': target_year,
        'cycle_start': cycle_start,
        'cycle_end': cycle_end,
        'search_query': search_query,
        'months_range': range(1, 13),
        'years_range': range(today.year - 2, today.year + 3),
    }

    return render(request, 'hr/attendance_list.html', context)


# def attendance_list(request):
#     """
#     سجل الحضور مع الدورة المحاسبية (26 إلى 25) والبحث العربي الذكي
#     """
#     today = timezone.localdate()

#     # 1. جلب الشهر والسنة المستهدفين
#     target_month = int(request.GET.get('month', today.month))
#     target_year = int(request.GET.get('year', today.year))
#     search_query = request.GET.get('q', '').strip()

#     # 2. 🟢 حساب الدورة المحاسبية (من يوم 26 الشهر السابق إلى 25 الشهر الحالي)
#     prev_month = target_month - 1 if target_month > 1 else 12
#     prev_year = target_year if target_month > 1 else target_year - 1

#     cycle_start = date(prev_year, prev_month, 26)
#     cycle_end = date(target_year, target_month, 25)

#     # تطبيق فلتر الدورة المحاسبية
#     attendance_query = DailyAttendance.objects.select_related('employee').filter(
#         date__gte=cycle_start,
#         date__lte=cycle_end
#     )

#     # 3. محرك البحث الذكي (معدل)
#     if search_query:
#         if search_query.isdigit():
#             # إذا كان الإدخال رقماً، نستخدم المطابقة التامة exact match مع كود البصمة
#             attendance_query = attendance_query.filter(employee__emp_id=search_query)
#         else:
#             # إذا كان الإدخال نصاً، نطبق البحث المرن على اسم الموظف بحالات الهمزات والألف اللينة
#             pattern = search_query
#             pattern = re.sub(r'[اأإآ]', r'[اأإآ]', pattern)
#             pattern = re.sub(r'[هة]', r'[هة]', pattern)
#             pattern = re.sub(r'[يى]', r'[يى]', pattern)

#             attendance_query = attendance_query.filter(
#                 Q(employee__name__iregex=pattern)
#             )

#     # الترتيب: الموظف أولاً، ثم تسلسل الأيام
#     attendance_query = attendance_query.order_by('employee__name', 'date')

#     # الترقيم
#     paginator = Paginator(attendance_query, 50)
#     page_number = request.GET.get('page')
#     attendance = paginator.get_page(page_number)

#     # 🟢 إثراء سجلات هذه الصفحة (50 سجل بحد أقصى) بنوع الإجازة الفعلي
#     # (سنوية/عارضة/مرضية) بدل عرض كلمة "إجازة" العامة فقط - مفيد خصوصاً
#     # لتوضيح الإجازة المرضية بشكل منفصل في سجل الحضور
#     leave_days = [r for r in attendance if r.status == 'leave']
#     if leave_days:
#         employee_ids = {r.employee_id for r in leave_days}
#         relevant_leaves = list(LeaveRequest.objects.filter(
#             employee_id__in=employee_ids,
#             status='approved',
#             start_date__lte=cycle_end,
#             end_date__gte=cycle_start,
#         ).values('employee_id', 'start_date', 'end_date', 'leave_type'))

#         for r in leave_days:
#             r.leave_type_code = None
#             for lv in relevant_leaves:
#                 if lv['employee_id'] == r.employee_id and lv['start_date'] <= r.date <= lv['end_date']:
#                     r.leave_type_code = lv['leave_type']
#                     break

#     context = {
#         'attendance': attendance,
#         'month': target_month,
#         'year': target_year,
#         'cycle_start': cycle_start,
#         'cycle_end': cycle_end,
#         'search_query': search_query,
#         'months_range': range(1, 13),
#         'years_range': range(today.year - 2, today.year + 3),
#     }

#     return render(request, 'hr/attendance_list.html', context)


def leave_list(request):
    """
    محرك إجازات Enterprise-Grade بنظام (العزل الصارم للدورة المالية):
    - يفصل الشهور تماماً لمنع تداخل الإجازات المعلقة الجديدة مع الشهور القديمة.
    - يدعم البحث المتقدم (Server-Side) وفك الكلمات مع أداء عالي.
    """
    today = timezone.localdate()

    # 1. القراءة الآمنة للمتغيرات من الرابط
    year_param = request.GET.get('year')
    month_param = request.GET.get('month')
    search_query = request.GET.get('q', '').strip()
    status_filter = request.GET.get('status', 'all')

    # 🌟 تحديد الدورة الافتراضية بدقة (26 إلى 25)
    if today.day >= 26:
        active_month = today.month + 1 if today.month < 12 else 1
        active_year = today.year if today.month < 12 else today.year + 1
    else:
        active_month = today.month
        active_year = today.year

    target_year = int(year_param) if year_param and year_param.isdigit() else active_year
    target_month = int(month_param) if month_param and month_param.isdigit() else active_month

    # 2. حساب الدورة المالية المحاسبية (26 إلى 25)
    cycle_end = date(target_year, target_month, 25)
    prev_month = target_month - 1 if target_month > 1 else 12
    prev_year = target_year if target_month > 1 else target_year - 1
    cycle_start = date(prev_year, prev_month, 26)

    # 🚀 3. بناء الاستعلام الذكي (تحميل بيانات الموظف دفعة واحدة)
    leaves_query = LeaveRequest.objects.select_related('employee')

    # 🛡️ أ) العزل الصارم: تصفية الدورة المالية أولاً
    leaves_query = leaves_query.filter(
        start_date__gte=cycle_start,
        start_date__lte=cycle_end
    )

    # 🛡️ ب) تقييد صلاحيات المستخدم العادي (غير السوبر يوزر)
    if not request.user.is_superuser:
        leaves_query = leaves_query.filter(employee__hr_managers=request.user)

    # 🔍 ج) تطبيق البحث المتقدم فقط عند وجود مدخلات (معالجة UnboundLocalError)
    if search_query:
        query_words = search_query.split()
        name_filter = Q()
        for word in query_words:
            name_filter &= Q(employee__name__icontains=word)

        leaves_query = leaves_query.filter(
            name_filter | Q(employee__emp_id__icontains=search_query)
        )

    # 🎯 د) تطبيق فلتر الحالة (أزرار الكل/مقبول/مرفوض)
    if status_filter in ['pending', 'approved', 'rejected']:
        leaves_query = leaves_query.filter(status=status_filter)

    # 4. الترتيب الأبجدي والتاريخي
    leaves_query = leaves_query.order_by('employee__name', '-start_date')

    # ⚡ 5. دمج إحصائيات الإشعارات في استعلام SQL واحد فقط (Conditional Aggregation)
    counts = LeaveRequest.objects.aggregate(
        global_pending=Count('id', filter=Q(status='pending')),
        cycle_pending=Count('id', filter=Q(
            status='pending',
            start_date__gte=cycle_start,
            start_date__lte=cycle_end
        ))
    )

    # 6. التقسيم الآمن للصفحات (50 سجل)
    paginator = Paginator(leaves_query, 50)
    page_number = request.GET.get('page')
    leaves_page = paginator.get_page(page_number)

    # 🔗 7. تجميع روابط الفلاتر لعدم ضياعها مع التنقل بين الصفحات
    query_params = request.GET.copy()
    query_params.pop('page', None)
    url_params = query_params.urlencode()

    return render(request, 'hr/leave_list.html', {
        'leaves': leaves_page,
        'notification_count': counts['global_pending'] or 0,
        'cycle_pending_count': counts['cycle_pending'] or 0,
        'cycle_start': cycle_start,
        'cycle_end': cycle_end,
        'target_month': target_month,
        'target_year': target_year,
        'now': today,
        'search_query': search_query,
        'status_filter': status_filter,
        'url_params': url_params
    })


def leave_request_view(request):
    if request.method == 'POST':
        request_type = request.POST.get('request_type')
        employee_id = request.POST.get('employee')
        employee_obj = Employee.objects.filter(id=employee_id, is_active=True).first() if employee_id else None

        if not employee_obj:
            messages.error(request, 'يجب اختيار موظف صحيح من القائمة قبل الحفظ.')

        elif request_type == 'leave':
            form = LeaveRequestForm(request.POST, instance=LeaveRequest(employee=employee_obj))
            if form.is_valid():
                form.save()
                messages.success(request, 'تم إرسال طلب الإجازة بنجاح وبانتظار الاعتماد!')
                return redirect('hr:leave_list')
            else:
                error_msg = form.non_field_errors()[0] if form.non_field_errors() else 'عذراً، يرجى مراجعة أرصدة وتواريخ الإجازة.'
                messages.error(request, error_msg)

        elif request_type == 'mission':
            form = MissionRequestForm(request.POST, instance=MissionRequest(employee=employee_obj))
            if form.is_valid():
                form.save()
                messages.success(request, 'تم تسجيل المأمورية الخارجية بنجاح!')
                return redirect('hr:leave_list')
            else:
                error_msg = form.non_field_errors()[0] if form.non_field_errors() else 'خطأ في تواريخ أو بيانات المأمورية.'
                messages.error(request, error_msg)

        elif request_type == 'permission':
            form = PermissionRequestForm(request.POST, instance=PermissionRequest(employee=employee_obj))
            if form.is_valid():
                form.save()
                messages.success(request, 'تم تسجيل طلب الإذن بنجاح!')
                return redirect('hr:leave_list')
            else:
                error_msg = form.non_field_errors()[0] if form.non_field_errors() else 'تأكد من صحة بيانات الإذن.'
                messages.error(request, error_msg)

    # 1. حساب الإشعارات المعلقة
    notification_count = (
        LeaveRequest.objects.filter(status='pending').count() +
        MissionRequest.objects.filter(status='pending').count() +
        PermissionRequest.objects.filter(status='pending').count()
    )

    # 2. جلب الموظفين النشطين
    employees = list(Employee.objects.filter(is_active=True).order_by('name'))

    # 3. ⚡ جلب كل الإجازات المعتمدة ابتداءً من تاريخ بداية السنة 26/08/2026
    start_year_date = date(2026, 8, 26)
    year_leaves = LeaveRequest.objects.filter(
        status='approved',
        start_date__gte=start_year_date
    )

    # تجميع الإجازات داخل الذاكرة (Memory Grouping) لتفادي استعلامات الداتابيز المتكررة
    leaves_by_emp = {}
    for leave in year_leaves:
        leaves_by_emp.setdefault(leave.employee_id, []).append(leave)

    emp_balances = {}
    for emp in employees:
        emp_leaves = leaves_by_emp.get(emp.id, [])
        casual_taken = sum((l.end_date - l.start_date).days + 1 for l in emp_leaves if l.leave_type == 'casual')
        annual_taken = sum((l.end_date - l.start_date).days + 1 for l in emp_leaves if l.leave_type == 'annual')

        emp_balances[str(emp.id)] = {
            'annual_balance': float(getattr(emp, 'annual_balance', 0) or 0),
            'casual_balance': float(getattr(emp, 'casual_balance', 0) or 0),
            'taken_casual_month': float(casual_taken),
            'taken_annual_month': float(annual_taken),
        }

    emp_balances_json = json.dumps(emp_balances, cls=DjangoJSONEncoder)

    return render(request, 'hr/leave_form.html', {
        'employees': employees,
        'notification_count': notification_count,
        'emp_balances_json': emp_balances_json,
    })



@transaction.atomic
def leave_approve(request, leave_id):
    try:
        leave = get_object_or_404(LeaveRequest.objects.select_related('employee'), id=leave_id)
        emp = leave.employee
        deduct_days = leave.duration_days

        # 🛡️ 1. التحقق من الرصيد فقط (بدون إجراء عملية خصم هنا)
        if leave.leave_type == 'casual':
            if emp.casual_balance < deduct_days:
                error_msg = f'عفواً، رصيد العارضة المتبقي ({emp.casual_balance} يوم) لا يكفي لخصم ({deduct_days} يوم).'
                if request.headers.get('x-requested-with') == 'XMLHttpRequest':
                    return JsonResponse({'status': 'error', 'message': error_msg}, status=400)
                messages.error(request, error_msg)
                return redirect('hr:leave_list')

        elif leave.leave_type == 'annual':
            if emp.annual_balance < deduct_days:
                error_msg = f'عفواً، رصيد السنوية المتبقي ({emp.annual_balance} يوم) لا يكفي لخصم ({deduct_days} يوم شاملة العطلات المتصلة).'
                if request.headers.get('x-requested-with') == 'XMLHttpRequest':
                    return JsonResponse({'status': 'error', 'message': error_msg}, status=400)
                messages.error(request, error_msg)
                return redirect('hr:leave_list')

        # 🛑 تم مسح أسطر emp.casual_balance -= deduct_days و emp.save() من هنا لتفادي الخصم المزدوج

        # 2. تغيير الحالة والحفظ (الـ Model أو الـ Signal هيخصم الرصيد تلقائياً عند الحفظ)
        leave.status = 'approved'
        leave.save()

        # 3. تحديث سجلات الحضور
        DailyAttendance.objects.filter(
            employee=emp,
            date__range=[leave.start_date, leave.end_date]
        ).update(
            status='leave',
            administrative_penalty_days=0.0,
            absence_deduction_days=0.0
        )

        if request.headers.get('x-requested-with') == 'XMLHttpRequest':
            return JsonResponse({'status': 'success', 'message': f'تم اعتماد إجازة {emp.name} وخصم {deduct_days} يوم من الرصيد بنجاح'})

        messages.success(request, f"تم اعتماد إجازة الموظف {emp.name} وخصم {deduct_days} يوم من الرصيد بنجاح.")

    except Exception as e:
        if request.headers.get('x-requested-with') == 'XMLHttpRequest':
            return JsonResponse({'status': 'error', 'message': str(e)}, status=400)

        messages.error(request, f"خطأ أثناء الاعتماد: {str(e)}")

    return redirect('hr:leave_list')



def leave_reject(request, leave_id):
    """
    رفض طلب الإجازة المعلق (يدعم AJAX السريع)
    """
    try:
        leave = get_object_or_404(LeaveRequest, id=leave_id)
        leave.status = 'rejected'
        leave.save()

        # 🟢 إذا كان الطلب من كروت الموبايل السريعة (AJAX)
        if request.headers.get('x-requested-with') == 'XMLHttpRequest':
            return JsonResponse({'status': 'success', 'message': f'تم رفض إجازة {leave.employee.name}'})

        messages.warning(request, f"تم رفض طلب إجازة الموظف {leave.employee.name}.")
    except Exception as e:
        # 🔴 معالجة الخطأ في حالة الـ AJAX
        if request.headers.get('x-requested-with') == 'XMLHttpRequest':
            return JsonResponse({'status': 'error', 'message': str(e)}, status=400)

        messages.error(request, f"خطأ أثناء الرفض: {str(e)}")

    return redirect('hr:leave_list')


def employee_update_view(request, employee_id):
    employee = get_object_or_404(Employee, id=employee_id)
    if request.method == 'POST':
        form = EmployeeForm(request.POST, request.FILES, instance=employee)
        if form.is_valid():
            form.save()
            # 👈 التعديل: التوجيه لصفحة قائمة الموظفين بعد الحفظ
            return redirect('hr:employee_list')
        else:
            # 👇 أضف هذا السطر لطباعة الخطأ الفعلي في شاشة الـ Console
            print("Errors:", form.errors)
    else:
        form = EmployeeForm(instance=employee)

    # تعديل المسار ليكون مسبوقاً باسم المجلد hr/
    return render(request, 'hr/employee_form.html', {'form': form, 'employee': employee})


# أضف هذه الدالة في نهاية ملف views.py تماماً لكي تقرأ بيانات الموظف وتفتح له الفورم المخصص
# def employee_update_view(request, employee_id):
#     employee = Employee.objects.get(id=employee_id)
#     if request.method == 'POST':
#         # تمرير instance=employee يضمن التعديل على نفس الموظف بدلاً من إنشاء واحد جديد
#         form = EmployeeForm(request.POST, request.FILES, instance=employee)
#         if form.is_valid():
#             form.save()
#             messages.success(request, f'تم تحديث بيانات الموظف "{employee.name}" بنجاح!')
#             return redirect('hr:employee_list')
#         else:
#             messages.error(request, 'عذراً، يرجى مراجعة البيانات وتصحيح الأخطاء.')
#     else:
#         form = EmployeeForm(instance=employee)

#     return render(request, 'hr/employee_form.html', {'form': form, 'employee': employee})

    # ---------------------------------------------------------
# دوال إدارة المأموريات الخارجية
# ---------------------------------------------------------
def mission_list(request):
    missions = MissionRequest.objects.all().order_by('-start_date')
    if request.method == 'POST':
        form = MissionRequestForm(request.POST)
        if form.is_valid():
            form.save()
            messages.success(request, 'تم تسجيل المأمورية بنجاح!')
            return redirect('hr:mission_list')
    else:
        form = MissionRequestForm()

    return render(request, 'hr/mission_list.html', {'missions': missions, 'form': form})

def update_mission_status(request, req_id, status):
    mission = get_object_or_404(MissionRequest, id=req_id)
    if status in ['approved', 'rejected']:
        mission.status = status
        mission.save()
        messages.success(request, f'تم تحديث حالة المأمورية إلى: {mission.get_status_display()}')
    return redirect('hr:mission_list')

# ---------------------------------------------------------
# دوال إدارة الأذونات الرسمية
# ---------------------------------------------------------
def permission_list(request):
    permissions = PermissionRequest.objects.all().order_by('-date')
    if request.method == 'POST':
        form = PermissionRequestForm(request.POST)
        if form.is_valid():
            form.save()
            messages.success(request, 'تم تسجيل الإذن بنجاح!')
            return redirect('hr:permission_list')
    else:
        form = PermissionRequestForm()

    return render(request, 'hr/permission_list.html', {'permissions': permissions, 'form': form})

def update_permission_status(request, req_id, status):
    permission = get_object_or_404(PermissionRequest, id=req_id)
    if status in ['approved', 'rejected']:
        permission.status = status
        permission.save()
        messages.success(request, f'تم تحديث حالة الإذن إلى: {permission.get_status_display()}')
    return redirect('hr:permission_list')

# ---------------------------------------------------------
# دوال التسويات والاستثناءات المالية
# ---------------------------------------------------------
def adjustment_list(request):
    adjustments = FinancialAdjustment.objects.all().order_by('-date')
    if request.method == 'POST':
        form = FinancialAdjustmentForm(request.POST)
        if form.is_valid():
            form.save()
            messages.success(request, 'تم تسجيل الحركة المالية بنجاح!')
            return redirect('hr:adjustment_list')
    else:
        form = FinancialAdjustmentForm()

    return render(request, 'hr/adjustment_list.html', {'adjustments': adjustments, 'form': form})




def export_insurance_excel(request, year, month):
    response = HttpResponse(content_type='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet')
    response['Content-Disposition'] = f'attachment; filename="Insurance_Talaat_Harb_{year}_{month}.xlsx"'

    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = f"تأمينات {month}-{year}"
    ws.sheet_view.rightToLeft = True

    title_font = Font(name='Arial', size=14, bold=True)
    header_font = Font(name='Arial', size=11, bold=True)
    normal_font = Font(name='Arial', size=11, bold=True)
    center_aligned = Alignment(horizontal='center', vertical='center', wrap_text=True)
    thin_border = Border(left=Side(style='thin'), right=Side(style='thin'), top=Side(style='thin'), bottom=Side(style='thin'))
    header_fill = PatternFill(start_color='E2EFDA', end_color='E2EFDA', fill_type='solid')

    # الترويسة الرئيسية
    ws.merge_cells('A1:C2')
    cell_a1 = ws['A1']
    cell_a1.value = "محافظة القاهرة\nإدارة عين شمس التعليمية\nمدارس طلعت حرب الثانوية الفندقية"
    cell_a1.font = header_font
    cell_a1.alignment = center_aligned

    ws.merge_cells('D1:J2')
    cell_d1 = ws['D1']
    cell_d1.value = f"كشف استقطاعات التأمينات والضرائب بالمدرسة عن شهر {month} لعام {year}"
    cell_d1.font = title_font
    cell_d1.alignment = center_aligned

    # دمج وتصميم رؤوس الأعمدة كما في الملف الأصلي
    ws.merge_cells('A3:A5'); ws['A3'] = 'م'
    ws.merge_cells('B3:B5'); ws['B3'] = 'الاسم'
    ws.merge_cells('C3:C5'); ws['C3'] = 'الوظيفــــة'
    ws.merge_cells('D3:D5'); ws['D3'] = 'الأجر التأمينى'

    ws.merge_cells('E3:G3'); ws['E3'] = 'الاستـقـطـاعـــــــــات'

    ws.merge_cells('E4:E4'); ws['E4'] = 'حصة العامل'
    ws['E5'] = '11%'

    ws.merge_cells('F4:F4'); ws['F4'] = 'صندوق الطوارئ'
    ws['F5'] = '1%'

    ws.merge_cells('G4:G4'); ws['G4'] = 'ضريبة كسب عمل'
    ws['G5'] = '20%'

    ws.merge_cells('H3:H5'); ws['H3'] = 'جملة الاستقطاعات'
    ws.merge_cells('I3:I5'); ws['I3'] = 'صافى الأجر'
    ws.merge_cells('J3:J5'); ws['J3'] = 'التوقيـــــــــع'

    # تطبيق التنسيق والحدود على خلايا العناوين
    for row in range(3, 6):
        for col in ['A','B','C','D','E','F','G','H','I','J']:
            cell = ws[f'{col}{row}']
            cell.font = header_font
            cell.alignment = center_aligned
            cell.fill = header_fill
            cell.border = thin_border

    # ضبط عرض الأعمدة
    ws.column_dimensions['B'].width = 30
    for col in ['C', 'D', 'E', 'F', 'I']: ws.column_dimensions[col].width = 15
    for col in ['G', 'H']: ws.column_dimensions[col].width = 18
    ws.column_dimensions['J'].width = 25

    # جلب البيانات وإجراء الحسابات العكسية
    employees = Employee.objects.filter(is_active=True)
    row_num = 6
    total_insurable = total_ins = total_emg = total_tax = total_ded = total_net = 0

    for index, emp in enumerate(employees, 1):
        # المعادلة المحاسبية العكسية لاستخراج الأجر التأميني
        insurable_wage = float(emp.base_salary) / 0.68

        ins_share = insurable_wage * 0.11
        emg_share = insurable_wage * 0.01
        tax_share = insurable_wage * 0.20
        total_deductions = ins_share + emg_share + tax_share
        net_wage = float(emp.base_salary)

        # تجميع الإجماليات
        total_insurable += insurable_wage
        total_ins += ins_share
        total_emg += emg_share
        total_tax += tax_share
        total_ded += total_deductions
        total_net += net_wage

        row_data = [
            index, emp.name, emp.department.name if emp.department else '-',
            round(insurable_wage, 2), round(ins_share, 2), round(emg_share, 2),
            round(tax_share, 2), round(total_deductions, 2), round(net_wage, 2), ''
        ]

        for col_idx, value in enumerate(row_data, 1):
            cell = ws.cell(row=row_num, column=col_idx)
            cell.value = value
            cell.font = normal_font
            cell.alignment = center_aligned
            cell.border = thin_border

        row_num += 1

    # صف الإجماليات النهائي
    ws.merge_cells(start_row=row_num, start_column=1, end_row=row_num, end_column=3)
    total_label = ws.cell(row=row_num, column=1)
    total_label.value = "إجمالــى الكشف"
    total_label.font = title_font
    total_label.alignment = center_aligned
    total_label.border = thin_border
    total_label.fill = header_fill

    ws.cell(row=row_num, column=2).border = thin_border
    ws.cell(row=row_num, column=3).border = thin_border

    totals_data = [(4, total_insurable), (5, total_ins), (6, total_emg), (7, total_tax), (8, total_ded), (9, total_net)]
    for col_idx, total_val in totals_data:
        cell = ws.cell(row=row_num, column=col_idx)
        cell.value = round(total_val, 2)
        cell.font = Font(name='Arial', size=11, bold=True, color='FF0000')
        cell.alignment = center_aligned
        cell.border = thin_border
        cell.fill = header_fill

    ws.cell(row=row_num, column=10).border = thin_border; ws.cell(row=row_num, column=10).fill = header_fill

    wb.save(response)
    return response

# ---------------------------------------------------------
# دالة إدارة أجندة العطلات الرسمية والاستثنائية
# ---------------------------------------------------------
def public_holiday_list(request):
    holidays = PublicHoliday.objects.all().order_by('-start_date')
    if request.method == 'POST':
        form = PublicHolidayForm(request.POST)
        if form.is_valid():
            form.save()
            messages.success(request, 'تم تسجيل العطلة الرسمية بنجاح! لن يتم احتساب غياب للموظفين في هذه الفترة.')
            return redirect('hr:public_holiday_list')
    else:
        form = PublicHolidayForm()

    return render(request, 'hr/public_holiday_list.html', {'holidays': holidays, 'form': form})
