from hr.models import Employee, DailyAttendance, PenaltyRecord
from datetime import date

# البحث عن الموظف بالاسم أو الكود
emp = Employee.objects.filter(name__icontains="مصطفى محمود").first()
if emp:
    print(f"==========================================")
    print(f"الموظف: {emp.name} | الكود: {emp.emp_id} | الأساسي: {emp.base_salary}")
    print(f"==========================================")

    start_date = date(2026, 9, 26)
    end_date = date(2026, 10, 25)

    records = DailyAttendance.objects.filter(employee=emp, date__gte=start_date, date__lte=end_date).order_by('date')
    print(f"\n--- سجلات الحضور والانصراف ({records.count()} يوم) ---")
    total_late_mins = 0
    total_deduct_hrs = 0.0
    total_pen_days = 0.0

    for r in records:
        total_late_mins += (r.late_minutes or 0)
        total_deduct_hrs += float(r.deduction_hours or 0)
        total_pen_days += float(r.administrative_penalty_days or 0)
        print(f"التاريخ: {r.date} | الحالة: {r.status} | حضور: {r.check_in} | انصراف: {r.check_out} | تأخير: {r.late_minutes}د | خصم: {r.deduction_hours}س | جزاء: {r.administrative_penalty_days} يوم")

    print(f"\n[الإجماليات]: إجمالي دقائق التأخير = {total_late_mins} دقيقة | إجمالي ساعات الخصم = {total_deduct_hrs} ساعة | إجمالي أيام الجزاء = {total_pen_days} يوم")

    penalties = PenaltyRecord.objects.filter(employee=emp, date__gte=start_date, date__lte=end_date)
    print(f"\n--- الجزاءات الإدارية المباشرة ({penalties.count()}) ---")
    for p in penalties:
        print(f"التاريخ: {p.date} | النوع: {p.penalty_type} | الأيام: {p.deduction_days} | السبب: {p.reason}")
else:
    print("لم يتم العثور على الموظف بهذا الاسم.")

