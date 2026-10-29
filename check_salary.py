from hr.models import Employee, DailyAttendance
from datetime import date

emp = Employee.objects.filter(name__icontains="مصطفى محمود").first()
if emp:
    start_date = date(2026, 9, 26)
    end_date = date(2026, 10, 25)
    
    records = DailyAttendance.objects.filter(employee=emp, date__gte=start_date, date__lte=end_date).order_by('date')
    
    print("==========================================================")
    print(f"تفاصيل السجلات اليومية للموظف: {emp.name} (الكود: {emp.emp_id})")
    print(f"فترة الدورة المحاسبية: من {start_date} إلى {end_date}")
    print("==========================================================")
    print(f"{'التاريخ':<12} | {'الحالة':<10} | {'دقائق التأخير':<13} | {'ساعات الخصم':<12} | {'الجزاء'}")
    print("-" * 65)
    
    total_late_mins = 0
    total_deduct_hrs = 0
    absence_count = 0
    
    for r in records:
        status = r.status or '-'
        late_m = r.late_minutes or 0
        ded_h = float(r.deduction_hours or 0)
        pen = float(r.administrative_penalty_days or 0)
        
        total_late_mins += late_m
        total_deduct_hrs += ded_h
        if status == 'absence':
            absence_count += 1
            
        print(f"{str(r.date):<12} | {status:<10} | {late_m:<13} | {ded_h:<12.2f} | {pen}")
    
    print("-" * 65)
    print(f"إجمالي أيام الغياب: {absence_count}")
    print(f"إجمالي دقائق التأخير المسجلة: {total_late_mins} دقيقة")
    print(f"إجمالي ساعات الخصم (`deduction_hours`): {total_deduct_hrs:.2f} ساعة")
    print("==========================================================")
else:
    print("لم يتم العثور على الموظف")

from hr.models import Employee, DailyAttendance
from datetime import date

# جلب بيانات الموظف
emp = Employee.objects.filter(name__icontains="مصطفى محمود").first()
if emp:
    start_date = date(2026, 9, 26)
    end_date = date(2026, 10, 25)
    
    records = DailyAttendance.objects.filter(employee=emp, date__gte=start_date, date__lte=end_date)
    
    absence_days = sum(1 for r in records if r.status == 'absence')
    total_late_mins = sum((r.late_minutes or 0) for r in records)
    total_deduct_hrs = sum(float(r.deduction_hours or 0) for r in records)
    admin_penalty_days = sum(float(r.administrative_penalty_days or 0) for r in records)
    
    base_salary = float(emp.base_salary)
    D = 30.0
    standard_day_rate = base_salary / D
    
    # حساب معامل الدورة (Multiplier) ونسبة الحضور
    attended_days = D - absence_days
    attendance_ratio = attended_days / D if D > 0 else 1.0
    multiplier = 1.0 / attendance_ratio if attendance_ratio > 0 else 1.0
    
    effective_day_rate = standard_day_rate * multiplier
    
    absence_deduction = absence_days * standard_day_rate
    late_deduction = total_deduct_hrs * effective_day_rate
    total_deductions = absence_deduction + late_deduction
    net_salary = base_salary - total_deductions
    
    print("==========================================")
    print(f"الموظف: {emp.name} | الكود: {emp.emp_id}")
    print(f"الراتب الأساسي: {base_salary:,.2f} ج.م")
    print(f"أيام الغياب: {absence_days}")
    print(f"إجمالي دقائق التأخير: {total_late_mins} دقيقة")
    print(f"إجمالي ساعات الخصم (deduction_hours): {total_deduct_hrs:.2f} ساعة")
    print(f"معامل الدورة (Multiplier): {multiplier:.4f}")
    print("------------------------------------------")
    print(f"خصم الغياب: {absence_deduction:,.2f} ج.م")
    print(f"خصم التأخير: {late_deduction:,.2f} ج.م")
    print(f"إجمالي الاستقطاعات: {total_deductions:,.2f} ج.م")
    print(f"الصافي المستحق للقبض: {net_salary:,.2f} ج.م")
    print("==========================================")
else:
    print("لم يتم العثور على الموظف")


