# -*- coding: utf-8 -*-
from hr.models import DailyAttendance

APPLY = False

ZERO = dict(
    status='holiday',
    actual_work_hours=0.0,
    overtime_hours=0.0,
    late_minutes=0,
    deduction_hours=0.0,
    administrative_penalty_days=0.0,
    absence_deduction_days=0.0,
)

fridays = DailyAttendance.objects.filter(
    date__week_day=6,
    status__in=['absent', 'present'],
)

dirty_holidays = DailyAttendance.objects.filter(status='holiday').exclude(
    actual_work_hours=0, overtime_hours=0, deduction_hours=0,
    late_minutes=0, administrative_penalty_days=0, absence_deduction_days=0,
)

print("سجلات الجمعة (حاضر/غائب) التي ستتحول لعطلة:", fridays.count())
print("  منها غياب:", fridays.filter(status='absent').count(),
      "| بجزاء:", fridays.filter(administrative_penalty_days__gt=0).count(),
      "| بإضافي:", fridays.filter(overtime_hours__gt=0).count())
print("سجلات عطلة فيها قيم قديمة سيتم تصفيرها:", dirty_holidays.count())
for r in fridays.order_by('date')[:10]:
    print("  ", r.date, r.employee.name, r.status, r.check_in, r.check_out)

if APPLY:
    n1 = fridays.update(**ZERO)
    n2 = dirty_holidays.update(**ZERO)
    print("تم تعديل", n1, "سجل جمعة و", n2, "سجل عطلة")
else:
    print("معاينة فقط. غيّر APPLY = True للتنفيذ.")