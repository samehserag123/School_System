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



def filter_by_employment_period(qs):
    """يستبعد أي سجل حضور قبل تاريخ التعيين أو بعد تاريخ انتهاء العمل."""
    return qs.filter(
        Q(employee__hire_date__isnull=True) | Q(date__gte=F('employee__hire_date'))
    ).filter(
        Q(employee__end_date__isnull=True) | Q(date__lte=F('employee__end_date'))
    )


def export_attendance_excel(request):
    search_query = request.GET.get('q', '').strip()
    month = request.GET.get('month', '')
    year = request.GET.get('year', '')

    # 1. الترتيب أبجدياً حسب اسم الموظف ثم تاريخ الحضور
    queryset = DailyAttendance.objects.select_related('employee__attendance_rule').all().order_by('employee__name', 'date')

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

    # 🟢 استبعاد الأيام قبل التعيين أو بعد انتهاء العمل (يُطبَّق دائماً)
    queryset = filter_by_employment_period(queryset)

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

        # اسم لائحة العمل (الشفت) للموظف
        rule = getattr(employee, 'attendance_rule', None) if employee else None
        shift_label = rule.name if rule else 'تابع السجل'

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
                shift_label,
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
    # 🟢 استبعاد الأيام قبل التعيين أو بعد انتهاء العمل
    attendance_query = filter_by_employment_period(attendance_query)

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
        # (يُعرض فقط على سجلات الصفحة، وهي مفلترة مسبقاً بفترة التوظيف)
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
        'all_employees': Employee.objects.filter(is_active=True).order_by('name'),
        'today': today,
    }

    return render(request, 'hr/attendance_list.html', context)


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
@login_required
def manual_attendance_entry(request):
    """
    🟢 إدخال حضور/انصراف يدوي عند تعطل جهاز البصمة.
    يمرّر الأوقات على نفس دالة الحساب التلقائي (calculate_daily_attendance)
    فتُطبَّق قواعد التأخير والانصراف المبكر والعطلات والإجازات كما لو كانت بصمة حقيقية.
    """
    import logging
    if not request.user.is_staff:
        return JsonResponse({'status': 'error', 'message': 'غير مصرح لك باتخاذ هذا الإجراء.'}, status=403)

    employee_id = request.POST.get('employee_id', '').strip()
    date_str = request.POST.get('date', '').strip()
    in_str = request.POST.get('check_in', '').strip()
    out_str = request.POST.get('check_out', '').strip()
    reason = request.POST.get('reason', '').strip()

    employee = Employee.objects.select_related('attendance_rule').filter(id=employee_id).first() if employee_id.isdigit() else None
    if not employee:
        return JsonResponse({'status': 'error', 'message': 'يرجى اختيار الموظف.'}, status=400)

    target_date = parse_date(date_str)
    if not target_date:
        return JsonResponse({'status': 'error', 'message': 'يرجى تحديد تاريخ صحيح.'}, status=400)
    if target_date > timezone.localdate():
        return JsonResponse({'status': 'error', 'message': 'لا يمكن إدخال حضور ليوم لم يأتِ بعد.'}, status=400)
    if not reason:
        return JsonResponse({'status': 'error', 'message': 'يرجى كتابة سبب الإدخال اليدوي (مثلاً: تعطل جهاز البصمة).'}, status=400)

    try:
        in_time = datetime.strptime(in_str, '%H:%M').time() if in_str else None
        out_time = datetime.strptime(out_str, '%H:%M').time() if out_str else None
    except ValueError:
        return JsonResponse({'status': 'error', 'message': 'صيغة الوقت غير صحيحة.'}, status=400)

    existing = DailyAttendance.objects.filter(employee=employee, date=target_date).first()
    # لو أُدخل وقت واحد فقط نكمل الوقت الآخر من السجل الموجود
    final_in = in_time or (existing.check_in if existing else None)
    final_out = out_time or (existing.check_out if existing else None)
    if not final_in and not final_out:
        return JsonResponse({'status': 'error', 'message': 'يرجى إدخال وقت الحضور أو الانصراف.'}, status=400)

    in_dt = datetime.combine(target_date, final_in) if final_in else None
    out_dt = datetime.combine(target_date, final_out) if final_out else None
    if in_dt and out_dt and out_dt <= in_dt:
        rule = employee.attendance_rule
        is_night = bool(rule and rule.work_start_time and rule.work_end_time and rule.work_end_time <= rule.work_start_time)
        if is_night:
            out_dt += timedelta(days=1)   # شفت ليلي: الانصراف في اليوم التالي
        else:
            return JsonResponse({'status': 'error', 'message': 'وقت الانصراف يجب أن يكون بعد وقت الحضور.'}, status=400)
    logs = [x for x in (in_dt, out_dt) if x]

    # بيانات الإجازات/المأموريات/العطلات + أيام العمل من لائحة الموظف
    pre = prepare_preloaded_data(target_date, target_date)
    DAY_FLAGS = ['monday', 'tuesday', 'wednesday', 'thursday', 'friday', 'saturday', 'sunday']
    rule = employee.attendance_rule
    if rule:
        is_work_day = bool(getattr(rule, DAY_FLAGS[target_date.weekday()], False))
    else:
        is_work_day = target_date.weekday() in [6, 0, 1, 2, 3]
    pre['working_days_map'] = {(employee.id, target_date): is_work_day}

    result = calculate_daily_attendance(employee, target_date, logs, pre)
    if result['status'] == 'not_hired':
        return JsonResponse({'status': 'error', 'message': 'التاريخ قبل تعيين الموظف.'}, status=400)

    fields = ['check_in', 'check_out', 'status', 'actual_work_hours', 'overtime_hours',
              'late_minutes', 'deduction_hours', 'administrative_penalty_days', 'absence_deduction_days']
    defaults = {k: result[k] for k in fields}
    if any(f.name == 'is_manual_override' for f in DailyAttendance._meta.fields):
        defaults['is_manual_override'] = True

    with transaction.atomic():
        DailyAttendance.objects.update_or_create(employee=employee, date=target_date, defaults=defaults)

    logging.getLogger(__name__).info(
        'MANUAL ATTENDANCE by=%s emp=%s date=%s in=%s out=%s result=%s reason=%s',
        request.user, employee.id, target_date, final_in, final_out, result['status'], reason
    )

    labels = {'present': 'حاضر', 'absent': 'غائب', 'holiday': 'عطلة (لا تُحتسب)',
              'leave': 'إجازة', 'mission': 'مأمورية'}
    msg = f"تم الحفظ. الحالة: {labels.get(result['status'], result['status'])}"
    if result['late_minutes']:
        msg += f" | تأخير {result['late_minutes']} دقيقة"
    if result['deduction_hours']:
        msg += f" | خصم {result['deduction_hours']} ساعة"
    if result['administrative_penalty_days']:
        msg += f" | جزاء {result['administrative_penalty_days']} يوم"
    return JsonResponse({'status': 'success', 'message': msg})


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
            # 🟢 العودة لنفس صفحة سجل الحضور (إن وُجد next آمن)
            from django.utils.http import url_has_allowed_host_and_scheme
            next_url = request.POST.get('next') or request.GET.get('next') or ''
            if next_url and url_has_allowed_host_and_scheme(
                    next_url, allowed_hosts={request.get_host()}, require_https=request.is_secure()):
                return redirect(next_url)
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

@transaction.atomic
def leave_cancel(request, leave_id):
    try:
        leave = get_object_or_404(LeaveRequest.objects.select_related('employee'), id=leave_id)

        # التأكد أن الإجازة معتمدة بالفعل قبل الإلغاء
        if leave.status == 'approved':
            emp = leave.employee

            # 🟢 الحل القاطع: استرداد الرصيد صراحةً فوراً قبل تغيير الحالة
            leave._update_employee_balance(leave.duration_days, operation='refund')

            # 1. تغيير حالة الطلب إلى مرفوض/ملغي
            leave.status = 'rejected'
            leave.save(update_fields=['status'])  # تحديث حقل الحالة فقط لتجنب أي تداخل

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



def compute_salary_components(emp, cycle_start, cycle_end, effective_start, absence_days, late_hours,
                              attendance_penalty_days, admin_penalty_days, sick_days, overtime_hours,
                              effective_end=None):
    """
    🧮 المعادلات الموحّدة للراتب (تستخدمها كل الشاشات: الكشف المجمّع / مفردات الراتب / الإكسيل).

    D  = أيام الشهر المرجعية (30، أو 12 للائحة 12 يوم)
    S  = أيام الخدمة المكافئة داخل الدورة = D × (أيام الخدمة ÷ أيام الدورة)   (تساوي D للموظف طوال الدورة)
    الحضور الفعلي = S − أيام الغياب
    معامل التضخيم M = D ÷ الحضور الفعلي

    - جزاءات الحضور (غياب/بصمة واحدة/تحايل...) والتأخير والانصراف المبكر: تُضرب في M
    - الجزاء الإداري (PenaltyRecord): بأجر اليوم القياسي بدون تضخيم
    - يوم الغياب نفسه والإجازة المرضية: بأجر اليوم القياسي بدون تضخيم
    """
    base_salary = float(emp.base_salary) if emp.base_salary else 0.0
    D = 12.0 if (emp.attendance_rule and "12" in emp.attendance_rule.name) else 30.0

    effective_end = effective_end or cycle_end   # 🟢 نهاية الخدمة داخل الدورة (الاستقالة)
    cycle_days = max(1, (cycle_end - cycle_start).days + 1)
    service_days = (effective_end - effective_start).days + 1
    service_fraction = min(1.0, max(0.0, service_days / cycle_days))
    service_equiv_days = D * service_fraction

    attended_days = max(0.0, service_equiv_days - absence_days)
    attendance_ratio = (attended_days / D) if attended_days > 0 else 1.0
    multiplier = 1.0 / attendance_ratio

    standard_day_rate = base_salary / D
    standard_hourly_rate = base_salary / 240.0
    effective_day_rate = standard_day_rate * multiplier
    earned_base_salary = base_salary * service_fraction
    effective_hourly_rate = standard_hourly_rate * multiplier

    absence_deduction = absence_days * standard_day_rate
    sick_deduction = sick_days * standard_day_rate
    penalty_deduction = (attendance_penalty_days * effective_day_rate) + (admin_penalty_days * standard_day_rate)
    # خصم التأخير: ساعات الخصم × الأجر اليومي القياسي (الراتب ÷ 30) — مطابق للنظام الآخر
    late_deduction = late_hours * effective_day_rate
    overtime_allowance = overtime_hours * standard_hourly_rate

    return {
        'base_salary': base_salary,
        'multiplier': multiplier,
        'absence_deduction': absence_deduction,
        'sick_deduction': sick_deduction,
        'penalty_deduction': penalty_deduction,
        'late_deduction': late_deduction,
        'overtime_allowance': overtime_allowance,
        'base_salary': base_salary,                  # التعاقدي
        'earned_base_salary': earned_base_salary,    # المستحق فعلياً
    }


def count_sick_leave_days(employee_id, start, end):
    """
    عدد أيام الإجازة المرضية المعتمدة الواقعة داخل [start, end].
    القاعدة: كل يوم مرضي = خصم يوم واحد من الراتب (بأجر اليوم العادي).
    الأيام تُحسب بالتقويم وبدون تكرار لو تداخلت طلبات.
    """
    leaves = LeaveRequest.objects.filter(
        employee_id=employee_id, leave_type='sick', status='approved',
        start_date__lte=end, end_date__gte=start
    ).values_list('start_date', 'end_date')
    days = set()
    for lv_start, lv_end in leaves:
        cur = max(lv_start, start)
        last = min(lv_end, end)
        while cur <= last:
            days.add(cur)
            cur += timedelta(days=1)
    return len(days)


def get_payroll_data(year, month):
    cycle_end = date(year, month, 25)
    cycle_start = date(year - 1, 12, 26) if month == 1 else date(year, month - 1, 26)

    # جلب جميع الموظفين النشطين
    employees = (
        Employee.objects
        .filter(Q(hire_date__isnull=True) | Q(hire_date__lte=cycle_end))                      # لم يُعيَّن بعد نهاية الدورة؟ استبعد
        .filter(Q(is_active=True, end_date__isnull=True) | Q(end_date__gte=cycle_start))      # المستقيل يظهر في دورة استقالته
        .select_related('department', 'attendance_rule')
        .order_by('name')
    )

    records = []
    totals = {
        'base': 0.0, 'overtime': 0.0, 'deductions': 0.0, 'net': 0.0,
        'abs_days': 0.0, 'abs_amt': 0.0, 'pen_days': 0.0, 'pen_amt': 0.0,
        'late_hrs': 0.0, 'late_amt': 0.0, 'sick_days': 0.0, 'sick_amt': 0.0
    }

    for emp in employees:
        # 🟢 تحديد بداية فترة الحساب الفعلية للموظف (تاريخ تعيينه أو بداية الدورة أيهما أحدث)
        emp_effective_start = emp.hire_date if (emp.hire_date and emp.hire_date > cycle_start) else cycle_start
        # 🟢 نهاية فترة الحساب الفعلية (تاريخ انتهاء العمل أو نهاية الدورة أيهما أقدم)
        emp_effective_end = emp.end_date if (emp.end_date and emp.end_date < cycle_end) else cycle_end
        if emp_effective_end < emp_effective_start:
            continue

        # جلب سجلات حضور الموظف من تاريخ التعيين وحتى انتهاء عمله (أو نهاية الدورة)
        attendance_qs = emp.daily_attendance_records.filter(
            date__gte=emp_effective_start,
            date__lte=emp_effective_end
        )

        # حساب الساعات والأيام من السجلات المفلترة فقط
        overtime_hours = attendance_qs.exclude(status='holiday').aggregate(
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
            date__lte=emp_effective_end      # كانت cycle_end

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
        sick_days = count_sick_leave_days(emp.id, emp_effective_start, emp_effective_end)   # 🟢 إجازة مرضية

        comp = compute_salary_components(
            emp, cycle_start, cycle_end, emp_effective_start,
            absence_days, late_hours, attendance_penalties, admin_penalties, sick_days, overtime_hours,
            effective_end=emp_effective_end
        )
        base_salary = comp['earned_base_salary']
        absence_deduction = comp['absence_deduction']
        sick_deduction = comp['sick_deduction']
        penalty_deduction = comp['penalty_deduction']
        late_deduction = comp['late_deduction']
        overtime_allowance = comp['overtime_allowance']
        insurance_deduction = float(emp.insurance_deduction) if (getattr(emp, 'is_insured', False) and emp.insurance_deduction) else 0.0

        admin_deductions = late_deduction + absence_deduction + sick_deduction + penalty_deduction
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
        totals['sick_days'] += sick_days
        totals['sick_amt'] += sick_deduction

        records.append({
            'employee': emp,
            'base_salary': round(base_salary, 2),
            'absence_days': absence_days,
            'absence_deduction': round(absence_deduction, 2),
            'penalty_days': round(penalty_days, 2),
            'penalty_deduction': round(penalty_deduction, 2),
            'late_hours': round(late_hours, 2),
            'late_deduction': round(late_deduction, 2),
            'sick_days': sick_days,
            'sick_deduction': round(sick_deduction, 2),
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


# ============================================================
# 📊 تقرير الشهر الشامل (Excel متعدد الشيتات)
# ============================================================
AR_WEEKDAYS = ['الاثنين', 'الثلاثاء', 'الأربعاء', 'الخميس', 'الجمعة', 'السبت', 'الأحد']


def _write_report_sheet(wb, title, period_text, headers, rows, widths, sum_cols=(), date_cols=(), is_first=False):
    """ينشئ شيت منسّقاً (RTL) بعنوان وترويسة وصفوف وإجمالي اختياري."""
    ws = wb.active if is_first else wb.create_sheet()
    ws.title = title
    ws.sheet_view.rightToLeft = True

    title_font = Font(name='Arial', size=13, bold=True)
    header_font = Font(name='Arial', size=11, bold=True, color='FFFFFF')
    body_font = Font(name='Arial', size=11)
    bold_font = Font(name='Arial', size=11, bold=True)
    center = Alignment(horizontal='center', vertical='center', wrap_text=True)
    border = Border(left=Side(style='thin'), right=Side(style='thin'),
                    top=Side(style='thin'), bottom=Side(style='thin'))
    header_fill = PatternFill(start_color='1F4E78', end_color='1F4E78', fill_type='solid')
    total_fill = PatternFill(start_color='FFF2CC', end_color='FFF2CC', fill_type='solid')

    n = len(headers)
    last_col = openpyxl.utils.get_column_letter(n)
    ws.merge_cells(f'A1:{last_col}1')
    ws['A1'].value = f"{title} - {period_text}"
    ws['A1'].font = title_font
    ws['A1'].alignment = center
    ws.row_dimensions[1].height = 28

    for c, h in enumerate(headers, 1):
        cell = ws.cell(row=2, column=c, value=h)
        cell.font = header_font
        cell.fill = header_fill
        cell.alignment = center
        cell.border = border
    ws.row_dimensions[2].height = 24

    row_num = 3
    for r in rows:
        for c, val in enumerate(r, 1):
            cell = ws.cell(row=row_num, column=c, value=val)
            cell.font = body_font
            cell.alignment = center
            cell.border = border
            if (c - 1) in date_cols and val:
                cell.number_format = 'YYYY-MM-DD'
        row_num += 1

    if not rows:
        ws.merge_cells(start_row=3, start_column=1, end_row=3, end_column=n)
        ws.cell(row=3, column=1, value='لا توجد بيانات في هذه الفترة').alignment = center
        ws.cell(row=3, column=1).font = bold_font
    else:
        ws.cell(row=row_num, column=1, value='الإجمالي / العدد').font = bold_font
        ws.cell(row=row_num, column=2, value=len(rows)).font = bold_font
        for c in range(1, n + 1):
            cell = ws.cell(row=row_num, column=c)
            cell.fill = total_fill
            cell.border = border
            cell.alignment = center
        for ci in sum_cols:
            total = sum((r[ci] or 0) for r in rows if isinstance(r[ci], (int, float)))
            ws.cell(row=row_num, column=ci + 1, value=round(total, 2)).font = bold_font
        ws.auto_filter.ref = f"A2:{last_col}{row_num - 1}"

    for i, w in enumerate(widths, 1):
        ws.column_dimensions[openpyxl.utils.get_column_letter(i)].width = w
    ws.freeze_panes = 'A3'
    return ws


@login_required
def export_monthly_report_excel(request, year, month):
    """
    ملف Excel واحد بعدة شيتات عن دورة الشهر (26 -> 25):
    المأموريات / الاستئذانات / الجزاءات / الإجازات / الغيابات / التأخيرات
    """
    year, month = int(year), int(month)
    cycle_end = date(year, month, 25)
    cycle_start = date(year - 1, 12, 26) if month == 1 else date(year, month - 1, 26)
    period_text = f"دورة شهر {month}/{year} (من {cycle_start.strftime('%d/%m/%Y')} إلى {cycle_end.strftime('%d/%m/%Y')})"

    def overlap_days(start, end):
        return (min(end, cycle_end) - max(start, cycle_start)).days + 1

    wb = openpyxl.Workbook()

    # ---------- 1) المأموريات ----------
    missions = MissionRequest.objects.select_related('employee').filter(
        start_date__lte=cycle_end, end_date__gte=cycle_start
    ).order_by('employee__name', 'start_date')
    rows = []
    for i, m in enumerate(missions, 1):
        rows.append([i, m.employee.name, m.employee.emp_id, m.start_date, m.end_date,
                     overlap_days(m.start_date, m.end_date), m.reason, m.get_status_display()])
    _write_report_sheet(wb, 'المأموريات', period_text,
                        ['م', 'الموظف', 'الكود', 'من تاريخ', 'إلى تاريخ', 'عدد الأيام بالدورة', 'الوجهة / التفاصيل', 'الحالة'],
                        rows, [6, 30, 10, 14, 14, 14, 45, 14], sum_cols=[5], date_cols=[3, 4], is_first=True)

    # ---------- 2) الاستئذانات ----------
    perms = PermissionRequest.objects.select_related('employee').filter(
        date__range=(cycle_start, cycle_end)
    ).order_by('employee__name', 'date')
    rows = []
    for i, p in enumerate(perms, 1):
        rows.append([i, p.employee.name, p.employee.emp_id, p.date, AR_WEEKDAYS[p.date.weekday()],
                     p.departure_time.strftime('%H:%M') if p.departure_time else '-', p.reason, p.get_status_display()])
    _write_report_sheet(wb, 'الاستئذانات', period_text,
                        ['م', 'الموظف', 'الكود', 'التاريخ', 'اليوم', 'وقت الخروج', 'السبب', 'الحالة'],
                        rows, [6, 30, 10, 14, 12, 12, 45, 14], date_cols=[3])

    # ---------- 3) الجزاءات (إدارية + جزاءات الحضور) ----------
    rows_raw = []
    for pr in PenaltyRecord.objects.select_related('employee').filter(date__range=(cycle_start, cycle_end)):
        pdate = pr.date.date() if hasattr(pr.date, 'date') else pr.date
        rows_raw.append((pr.employee.name, pdate, [pr.employee.name, pr.employee.emp_id, pdate,
                         'جزاء إداري - ' + pr.get_penalty_type_display(), float(pr.deduction_days), pr.reason, '']))
    att_pen = DailyAttendance.objects.select_related('employee').filter(
        date__range=(cycle_start, cycle_end), administrative_penalty_days__gt=0
    ).exclude(status='holiday')
    for a in att_pen:
        if a.status == 'absent' and not a.check_in:
            kind, why = 'جزاء حضور - غياب', 'غياب بدون بصمة'
        elif a.status == 'absent' and a.check_in and not a.check_out:
            kind, why = 'جزاء حضور - بصمة واحدة', 'بصمة واحدة فقط'
        elif a.status == 'absent':
            kind, why = 'جزاء حضور - تحايل / انصراف مبكر', 'خروج بدون إذن أو انصراف مبكر'
        else:
            kind, why = 'جزاء حضور', ''
        note = 'يشمل يوم الغياب' if a.status == 'absent' else ''
        rows_raw.append((a.employee.name, a.date, [a.employee.name, a.employee.emp_id, a.date, kind,
                         float(a.administrative_penalty_days), why, note]))
    rows_raw.sort(key=lambda x: (x[0], x[1]))
    rows = [[i] + r[2] for i, r in enumerate(rows_raw, 1)]
    _write_report_sheet(wb, 'الجزاءات', period_text,
                        ['م', 'الموظف', 'الكود', 'التاريخ', 'نوع الجزاء', 'أيام الخصم', 'السبب / التفاصيل', 'ملاحظة'],
                        rows, [6, 30, 10, 14, 34, 12, 45, 18], sum_cols=[5], date_cols=[3])

    # ---------- 4) الإجازات ----------
    leaves = LeaveRequest.objects.select_related('employee').filter(
        start_date__lte=cycle_end, end_date__gte=cycle_start
    ).order_by('employee__name', 'start_date')
    rows = []
    for i, l in enumerate(leaves, 1):
        rows.append([i, l.employee.name, l.employee.emp_id, l.get_leave_type_display(), l.start_date, l.end_date,
                     overlap_days(l.start_date, l.end_date), l.reason or '', l.get_status_display()])
    _write_report_sheet(wb, 'الإجازات', period_text,
                        ['م', 'الموظف', 'الكود', 'نوع الإجازة', 'من تاريخ', 'إلى تاريخ', 'عدد الأيام بالدورة', 'السبب', 'الحالة'],
                        rows, [6, 30, 10, 24, 14, 14, 14, 40, 18], sum_cols=[6], date_cols=[4, 5])

    # ---------- 5) الغيابات ----------
    absences = DailyAttendance.objects.select_related('employee').filter(
        date__range=(cycle_start, cycle_end), status='absent'
    ).order_by('employee__name', 'date')
    rows = []
    for i, a in enumerate(absences, 1):
        if not a.check_in:
            why = 'غياب بدون بصمة'
        elif not a.check_out:
            why = 'بصمة واحدة فقط'
        else:
            why = 'جزاء تحايل / انصراف مبكر'
        rows.append([i, a.employee.name, a.employee.emp_id, a.date, AR_WEEKDAYS[a.date.weekday()], why,
                     a.check_in.strftime('%H:%M') if a.check_in else '-',
                     a.check_out.strftime('%H:%M') if a.check_out else '-',
                     float(a.administrative_penalty_days or 0)])
    _write_report_sheet(wb, 'الغيابات', period_text,
                        ['م', 'الموظف', 'الكود', 'التاريخ', 'اليوم', 'سبب الغياب', 'الحضور', 'الانصراف', 'إجمالي أيام الخصم'],
                        rows, [6, 30, 10, 14, 12, 28, 10, 10, 16], sum_cols=[8], date_cols=[3])

    # ---------- 6) التأخيرات ----------
    lates = DailyAttendance.objects.select_related('employee').filter(
        date__range=(cycle_start, cycle_end)
    ).exclude(status='holiday').filter(Q(late_minutes__gt=0) | Q(deduction_hours__gt=0)).order_by('employee__name', 'date')
    rows = []
    for i, a in enumerate(lates, 1):
        rows.append([i, a.employee.name, a.employee.emp_id, a.date, AR_WEEKDAYS[a.date.weekday()],
                     a.check_in.strftime('%H:%M') if a.check_in else '-',
                     int(a.late_minutes or 0), round(float(a.deduction_hours or 0), 2)])
    _write_report_sheet(wb, 'التأخيرات', period_text,
                        ['م', 'الموظف', 'الكود', 'التاريخ', 'اليوم', 'وقت الحضور', 'دقائق التأخير', 'ساعات الخصم'],
                        rows, [6, 30, 10, 14, 12, 12, 14, 14], sum_cols=[6, 7], date_cols=[3])

    response = HttpResponse(content_type='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet')
    response['Content-Disposition'] = f'attachment; filename="Monthly_Report_{year}_{month}.xlsx"'
    wb.save(response)
    return response


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
            rec['net_salary'], '',
            (f"إجازة مرضية {rec['sick_days']} يوم (-{rec['sick_deduction']})" if rec.get('sick_days') else '')
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




def calculate_daily_attendance(employee, target_date, logs, preloaded_data):
    """
    دالة نقية (Pure Function) تُنفّذ في الذاكرة بزمن تنفيذ O(1) لحساب الحضور اليومي.
    """
    emp_id = employee.id
    rule = getattr(employee, 'attendance_rule', None)
    shift_type = getattr(rule, 'shift_type', 'fixed') if rule else 'fixed'

    # 0. حماية: تجاهل أي يوم قبل التعيين أو بعد انتهاء العمل / الاستقالة
    if not employee.is_employed_on(target_date):
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
    # أي بصمة في يوم عطلة لا تُحسب إطلاقاً: لا ساعات عمل ولا إضافي ولا خصم ولا جزاء.
    # نحتفظ بأوقات البصمة للاطلاع فقط.
    if not is_working_day or is_public_holiday:
        return {
            'check_in': min(logs).time() if logs else None,
            'check_out': max(logs).time() if logs else None,
            'status': 'holiday',
            'actual_work_hours': 0.0,
            'overtime_hours': 0.0,
            'late_minutes': 0,
            'deduction_hours': 0.0,
            'administrative_penalty_days': 0.0,
            'absence_deduction_days': 0.0
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

    if log_count == 1 and shift_type == 'flexible':
        # 🟢 الدوام المرن: بصمة واحدة تكفي ليكون الموظف حاضراً (لا غياب ولا جزاء ولا خصم)
        return {
            'check_in': check_in_dt.time(), 'check_out': None, 'status': 'present',
            'actual_work_hours': target_hours, 'overtime_hours': 0.0, 'late_minutes': 0,
            'deduction_hours': 0.0, 'administrative_penalty_days': 0.0, 'absence_deduction_days': 0.0
        }

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

            # 🟢 يشمل النشطين + من انتهى عمله (أيامه الأخيرة قد تكون داخل الملف). الفلترة بالتاريخ داخل calculate_daily_attendance
            active_emps = list(
                Employee.objects.filter(
                    Q(is_active=True) | Q(end_date__isnull=False)
                ).select_related('attendance_rule')
            )
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
            DAY_FLAGS = ['monday', 'tuesday', 'wednesday', 'thursday', 'friday', 'saturday', 'sunday']
            for emp in active_emps:
                rule = getattr(emp, 'attendance_rule', None)
                for d in distinct_dates:
                    if rule:
                        # أيام العمل تُقرأ من لائحة الموظف نفسها (الاثنين..الأحد في AttendanceRule)
                        working_days_map[(emp.id, d)] = bool(getattr(rule, DAY_FLAGS[d.weekday()], False))
                    else:
                        # بدون لائحة: الأحد..الخميس
                        working_days_map[(emp.id, d)] = d.weekday() in [6, 0, 1, 2, 3]

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

    # 🟢 دورة الراتب (26 من الشهر السابق -> 25 من الشهر الحالي) مثل الكشف المجمّع تماماً
    cycle_end = date(year, month, 25)
    cycle_start = date(year - 1, 12, 26) if month == 1 else date(year, month - 1, 26)
    emp_effective_start = employee.hire_date if (employee.hire_date and employee.hire_date > cycle_start) else cycle_start
    emp_effective_end = employee.end_date if (employee.end_date and employee.end_date < cycle_end) else cycle_end   # 🟢 الاستقالة

    # جلب جميع أيام حضور وغياب الموظف خلال دورة الراتب (حتى انتهاء عمله)
    attendances = DailyAttendance.objects.filter(
        employee=employee,
        date__gte=emp_effective_start,
        date__lte=emp_effective_end
    )

    counted_days = attendances.exclude(status='holiday')   # أيام العطلة لا تدخل في أي حساب
    total_overtime = counted_days.aggregate(Sum('overtime_hours'))['overtime_hours__sum'] or 0.0
    total_deductions_hours = counted_days.aggregate(Sum('deduction_hours'))['deduction_hours__sum'] or 0.0
    total_absence_days = attendances.filter(status='absent').count()

    # 🟢 حساب أيام الإجازة المرضية المعتمدة الواقعة داخل هذا الشهر (تُخصم من الراتب
    # يوماً بيوم تماماً مثل الغياب: يوم مرضي = خصم يوم، يومين مرضي = خصم يومين... إلخ)
    month_start = emp_effective_start
    month_end = emp_effective_end
    total_sick_days = count_sick_leave_days(employee.id, month_start, month_end)

    # 🔴 1. تجميع أيام الجزاء (يوم الغياب بدون إذن = 3 أيام إجمالاً: يوم الغياب نفسه + يومان جزاء)
    # لذلك نطرح 1 من جزاء السجلات الغائبة لأن اليوم نفسه يُحسب في total_absence_days
    total_penalty_days = counted_days.aggregate(
        total=Coalesce(
            Sum(
                Case(
                    When(status='absent', administrative_penalty_days__gte=1.0,
                         then=F('administrative_penalty_days') - 1.0),
                    default=F('administrative_penalty_days'),
                    output_field=FloatField()
                )
            ),
            Value(0.0), output_field=FloatField()
        )
    )['total']

    # 🟢 إضافة أيام خصم الجزاءات الإدارية الموقّعة (PenaltyRecord) لنفس الشهر
    penalty_records_this_month = PenaltyRecord.objects.filter(
        employee=employee, date__gte=emp_effective_start, date__lte=emp_effective_end
    )
    total_penalty_record_days = penalty_records_this_month.aggregate(
        Sum('deduction_days')
    )['deduction_days__sum'] or 0.0

    # 🧮 نفس المعادلات الموحّدة المستخدمة في الكشف المجمّع (تضخيم الجزاءات والتأخير، والإداري بدون تضخيم)
    comp = compute_salary_components(
        employee, cycle_start, cycle_end, emp_effective_start,
        total_absence_days, total_deductions_hours, total_penalty_days, total_penalty_record_days,
        total_sick_days, total_overtime,
        effective_end=emp_effective_end
    )
    base_salary = comp['earned_base_salary']
    absence_deduction = comp['absence_deduction']
    sick_deduction = comp['sick_deduction']
    penalty_deduction = comp['penalty_deduction']
    late_deduction = comp['late_deduction']
    overtime_allowance = comp['overtime_allowance']

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
    total_deductions_combined = late_deduction + absence_deduction + sick_deduction + penalty_deduction + ins_deduction
    actual_total_deductions = min(total_deductions_combined, base_salary + overtime_allowance)   # نفس سقف الكشف المجمّع
    net_salary = max(0.0, base_salary + overtime_allowance - actual_total_deductions)

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
        'base_salary': round(base_salary, 2),
        # 🛡️ إرسال المت المتغيرات التأمينية الجديدة لكي تظهر في صفحة مفردات الراتب (payroll_slip.html)
        'is_insured': employee.is_insured,
        'insurance_number': ins_number,
        'insurance_basic_salary': round(ins_basic, 2),
        'insurance_variable_allowance': round(ins_allowance, 2),
        'insurance_deduction': round(ins_deduction, 2),

        'net_salary': round(net_salary, 2),
    }
    return render(request, 'hr/payroll_slip.html', context)



def employee_list(request):
    # 1. جلب معاملات البحث والفلترة من الرابط
    date_param = request.GET.get('date', '').strip()
    search_query = request.GET.get('q', '').strip()
    tab_param = request.GET.get('tab', '').strip()

    # 2. تحديد التبويب النشط
    if tab_param:
        active_tab = tab_param
    elif date_param or request.GET.get('page') or search_query:
        active_tab = 'attendance'
    else:
        active_tab = 'dashboard'

    try:
        # 3. جلب البيانات الأساسية (تركها كـ QuerySet لتوليد Lazy Loading)
        employees = Employee.objects.all().select_related('department').order_by('name')
        departments = Department.objects.all()

        # جلب آخر الإجازات فقط للجدول لتجنب إغراق الذاكرة
        leave_requests = LeaveRequest.objects.all().select_related('employee').order_by('-id')[:50]

        # 4. استعلام الحضور والغياب الأساسي
        attendance_query = DailyAttendance.objects.all().select_related('employee').order_by('-date', 'employee__name')

        # 🟢 تطبيق فلتر التاريخ
        target_date = ""
        if date_param:
            parsed_date = parse_date(date_param)
            if parsed_date:
                target_date = parsed_date
                attendance_query = attendance_query.filter(date=target_date)
            else:
                target_date = timezone.now().date()

        # 🔍 تطبيق فلتر البحث الذكي
        if search_query:
            if search_query.isdigit():
                attendance_query = attendance_query.filter(employee__emp_id=search_query)
            else:
                pattern = search_query
                pattern = re.sub(r'[اأإآ]', r'[اأإآ]', pattern)
                pattern = re.sub(r'[هة]', r'[هة]', pattern)
                pattern = re.sub(r'[يى]', r'[يى]', pattern)

                attendance_query = attendance_query.filter(employee__name__iregex=pattern)

        # 5. الترقيم (Pagination)
        paginator = Paginator(attendance_query, 50)
        page_number = request.GET.get('page')
        attendance_page = paginator.get_page(page_number)

        # 6. إحصائيات سريعة ومباشرة عبر قاعدة البيانات (SQL Count)
        today = timezone.now().date()
        today_attendance_count = DailyAttendance.objects.filter(date=today, status__in=['present', 'late']).count()
        today_late_count = DailyAttendance.objects.filter(date=today, late_minutes__gt=0).count()
        total_emp = Employee.objects.count()
        pending_leaves = LeaveRequest.objects.filter(status='pending').count()

    except Exception as e:
        print(f"🔴 خطأ داخلي في الـ View: {str(e)}")
        employees, departments, leave_requests = [], [], []
        attendance_page = None
        target_date = timezone.now().date()
        today_attendance_count, today_late_count, total_emp, pending_leaves = 0, 0, 0, 0

    context = {
        'employees': employees,
        'departments': departments,
        'leave_requests': leave_requests,
        'attendance': attendance_page,
        'latest_attendance': attendance_page.object_list[:5] if attendance_page else [],

        # العدادات الإحصائية
        'total_employees': total_emp,
        'today_attendance_count': today_attendance_count,
        'today_late_count': today_late_count,
        'notification_count': pending_leaves,
        'current_date': target_date,
        'active_tab': active_tab,
    }

    return render(request, 'hr/employee_list.html', context)





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
            'annual_balance': float(emp.remaining_annual_balance),  # 👈 استخدام الرصيد الديناميكي الفعلي

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



# ---------------------------------------------------------
# دوال إدارة المأموريات الخارجية (محسنة بالفلتر التلقائي والباجنيشن)
# ---------------------------------------------------------
def mission_list(request):
    today = timezone.localdate()

    # تحديد الدورة المالية الحالية افتراضياً (من 26 إلى 25) لضمان السرعة وعدم جلب كل البيانات
    if today.day >= 26:
        default_y = today.year if today.month < 12 else today.year + 1
        default_m = today.month + 1 if today.month < 12 else 1
    else:
        default_y = today.year
        default_m = today.month

    selected_period = request.GET.get('salary_period', '').strip()

    if not selected_period:
        y, m = default_y, default_m
        selected_period = f"{y:04d}-{m:02d}"
    else:
        try:
            parts = selected_period.split('-')
            y, m = int(parts[0]), int(parts[1])
        except Exception:
            y, m = default_y, default_m

    # حساب نطاق الدورة المالية بدقة
    cycle_end = date(y, m, 25)
    prev_m = m - 1 if m > 1 else 12
    prev_y = y if m > 1 else y - 1
    cycle_start = date(prev_y, prev_m, 26)

    # الاستعلام مع التحسين (select_related) وتصفية النطاق المالي
    missions_qs = MissionRequest.objects.select_related('employee').filter(
        start_date__gte=cycle_start,
        start_date__lte=cycle_end
    ).order_by('-start_date')

    # 📄 إعداد الباجنيشن (عرض 25 سجل لكل صفحة)
    paginator = Paginator(missions_qs, 25)
    page_number = request.GET.get('page')
    missions = paginator.get_page(page_number)

    if request.method == 'POST':
        form = MissionRequestForm(request.POST)
        if form.is_valid():
            form.save()
            messages.success(request, 'تم تسجيل المأمورية بنجاح!')
            return redirect('hr:mission_list')
    else:
        form = MissionRequestForm()

    return render(request, 'hr/mission_list.html', {
        'missions': missions,
        'form': form,
        'selected_period': selected_period
    })


# ---------------------------------------------------------
# دوال إدارة الأذونات الرسمية (محسنة بالفلتر التلقائي والباجنيشن)
# ---------------------------------------------------------
def permission_list(request):
    today = timezone.localdate()

    # تحديد الدورة المالية الحالية افتراضياً
    if today.day >= 26:
        default_y = today.year if today.month < 12 else today.year + 1
        default_m = today.month + 1 if today.month < 12 else 1
    else:
        default_y = today.year
        default_m = today.month

    selected_period = request.GET.get('salary_period', '').strip()

    if not selected_period:
        y, m = default_y, default_m
        selected_period = f"{y:04d}-{m:02d}"
    else:
        try:
            parts = selected_period.split('-')
            y, m = int(parts[0]), int(parts[1])
        except Exception:
            y, m = default_y, default_m

    # حساب نطاق الدورة المالية
    cycle_end = date(y, m, 25)
    prev_m = m - 1 if m > 1 else 12
    prev_y = y if m > 1 else y - 1
    cycle_start = date(prev_y, prev_m, 26)

    # الاستعلام مع التحسين وتصفية النطاق المالي
    permissions_qs = PermissionRequest.objects.select_related('employee').filter(
        date__gte=cycle_start,
        date__lte=cycle_end
    ).order_by('-date')

    # 📄 إعداد الباجنيشن (عرض 25 سجل لكل صفحة)
    paginator = Paginator(permissions_qs, 25)
    page_number = request.GET.get('page')
    permissions = paginator.get_page(page_number)

    if request.method == 'POST':
        form = PermissionRequestForm(request.POST)
        if form.is_valid():
            form.save()
            messages.success(request, 'تم تسجيل الإذن بنجاح!')
            return redirect('hr:permission_list')
    else:
        form = PermissionRequestForm()

    return render(request, 'hr/permission_list.html', {
        'permissions': permissions,
        'form': form,
        'selected_period': selected_period
    })


def update_mission_status(request, req_id, status):
    mission = get_object_or_404(MissionRequest, id=req_id)
    if status in ['approved', 'rejected']:
        mission.status = status
        mission.save()
        messages.success(request, f'تم تحديث حالة المأمورية إلى: {mission.get_status_display()}')
    return redirect('hr:mission_list')



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