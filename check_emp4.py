# -*- coding: utf-8 -*-
# تشغيل:  python manage.py shell -c "exec(open('check_emp4.py', encoding='utf-8').read())"
from calendar import monthrange
from datetime import date
from django.db.models import Sum
from django.http import HttpResponse
from django.test import RequestFactory
from hr import views
from hr.models import Employee, DailyAttendance, PenaltyRecord

EMP_CODE = '4'          # رقم البصمة
YEAR, MONTH = 2026, 9

cycle_start = date(YEAR, MONTH - 1, 26) if MONTH > 1 else date(YEAR - 1, 12, 26)
cycle_end = date(YEAR, MONTH, 25)
month_start = date(YEAR, MONTH, 1)
month_end = date(YEAR, MONTH, monthrange(YEAR, MONTH)[1])

emp = Employee.objects.filter(emp_id=EMP_CODE).first()
if not emp:
    print("لا يوجد موظف برقم البصمة", EMP_CODE)
    raise SystemExit

rule = emp.attendance_rule
print("=" * 70)
print("الموظف:", emp.id, "|", emp.name, "| بصمة:", emp.emp_id)
print("الأساسي:", emp.base_salary, "| تاريخ التعيين:", emp.hire_date, "| نشط:", emp.is_active)
print("اللائحة:", rule, "| نوع الشفت:", getattr(rule, 'shift_type', None),
      "| معامل الغياب بالائحة:", getattr(rule, 'absent_deduction_days', None))


def show_days(start, end, title):
    print("\n" + "=" * 70)
    print(title, ":", start, "->", end)
    qs = DailyAttendance.objects.filter(employee=emp, date__range=(start, end)).order_by('date')
    absent = qs.filter(status='absent').count()
    raw_pen = qs.aggregate(s=Sum('administrative_penalty_days'))['s'] or 0
    hrs = qs.aggregate(s=Sum('deduction_hours'))['s'] or 0
    print("عدد السجلات:", qs.count(), "| أيام الغياب:", absent,
          "| مجموع الجزاء الخام:", raw_pen, "| ساعات الخصم:", round(hrs, 2))
    for r in qs:
        if r.status == 'absent' or (r.administrative_penalty_days or 0) > 0 or (r.deduction_hours or 0) > 0:
            print("  ", r.date, r.date.strftime('%a'), "|", r.status, "| دخول:", r.check_in, "| خروج:", r.check_out,
                  "| تأخير(د):", r.late_minutes, "| خصم(س):", r.deduction_hours,
                  "| جزاء:", r.administrative_penalty_days, "| غياب:", r.absence_deduction_days)
    # الجزاءات بعد طرح يوم الغياب (القاعدة: الغياب = 3 أيام إجمالاً)
    net_pen = 0.0
    for r in qs:
        p = float(r.administrative_penalty_days or 0)
        net_pen += (p - 1.0) if (r.status == 'absent' and p >= 1.0) else p
    prs = PenaltyRecord.objects.filter(employee=emp, date__range=(start, end))
    pr_days = float(prs.aggregate(s=Sum('deduction_days'))['s'] or 0)
    for p in prs:
        print("   جزاء إداري:", p.date, p.deduction_days, "يوم")
    print("=> غياب:", absent, "يوم | جزاء حضور بعد الطرح:", net_pen, "| جزاء إداري:", pr_days,
          "| إجمالي أيام الخصم المتوقعة:", absent + net_pen + pr_days)


show_days(cycle_start, cycle_end, "دورة الكشف المجمّع (26 -> 25)")
show_days(month_start, month_end, "الشهر الميلادي (مفردات الراتب الفردية)")

# ---------- ناتج الكشف المجمّع الفعلي ----------
print("\n" + "=" * 70)
print("ناتج الكشف المجمّع (get_payroll_data)")
data = views.get_payroll_data(YEAR, MONTH)
rec = next((r for r in data['records'] if r['employee'].id == emp.id), None)
if rec:
    for k in ['base_salary', 'absence_days', 'absence_deduction', 'penalty_days', 'penalty_deduction',
              'late_hours', 'late_deduction', 'overtime_allowance', 'insurance_deduction',
              'admin_deductions', 'deductions', 'net_salary']:
        print("  ", k, "=", rec.get(k))
else:
    print("   الموظف غير موجود في الكشف (غير نشط؟)")

# ---------- ناتج مفردات الراتب الفردية ----------
print("\n" + "=" * 70)
print("ناتج مفردات الراتب (calculate_monthly_salary)")
captured = {}
orig_render = views.render
views.render = lambda request, template, context=None, *a, **k: (captured.update(context or {}), HttpResponse(''))[1]
try:
    views.calculate_monthly_salary(RequestFactory().get('/'), emp.id, YEAR, MONTH)
finally:
    views.render = orig_render
for k in ['base_salary', 'late_deduction', 'absence_deduction', 'sick_deduction',
          'penalty_deduction', 'overtime_allowance', 'insurance_deduction', 'net_salary']:
    print("  ", k, "=", captured.get(k))