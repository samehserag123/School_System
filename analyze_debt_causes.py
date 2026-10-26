# -*- coding: utf-8 -*-
"""
analyze_debt_causes.py
======================
تحليل أسباب المديونيات السابقة لطلاب الصف الأول بدقة.
"""
import csv
from collections import Counter
from django.db.models import Sum, Count, Min, Max
from students.models import Student, Grade
from finance.models import AcademicYear

OUT_DIR = '/home/sameh123/'

year = AcademicYear.objects.filter(is_active=True).first()
grades = list(Grade.objects.order_by('id'))
first_grade = grades[0] if grades else None

print('=' * 60)
print(f'🔍 تحليل أسباب المديونيات لطلاب الصف الأول ({first_grade.name}) - سنة {year}')
print('=' * 60)

# جلب الطلاب المستهدفين
debtors = Student.objects.filter(
    academic_year=year,
    grade=first_grade,
    previous_debt__gt=0
).select_related('classroom')

total_count = debtors.count()
total_sum = debtors.aggregate(Sum('previous_debt'))['previous_debt__sum'] or 0

print(f'📌 عدد الطلاب: {total_count} طالب')
print(f'💰 إجمالي المديونيات السابقة: {total_sum:,.2f} جنيه')
print('-' * 60)

# 1) التحليل حسب حالة القيد (Enrollment Status)
print('1️⃣ توزيع الطلاب حسب حالة القيد (enrollment_status):')
status_counts = Counter(debtors.values_list('enrollment_status', flat=True))
for st, count in status_counts.most_common():
    sub_sum = debtors.filter(enrollment_status=st).aggregate(Sum('previous_debt'))['previous_debt__sum'] or 0
    print(f'   • {st:<15}: {count:3d} طالب | مجموع المديونية: {sub_sum:10,.2f} جنيه')

print('-' * 60)

# 2) التحليل حسب فئات المبالغ (تحديد المبالغ النمطية أو المكررة)
print('2️⃣ أكثر مبالغ المديونيات تكراراً (Top Recurring Debt Amounts):')
debt_amounts = Counter(debtors.values_list('previous_debt', flat=True))
for amt, count in debt_amounts.most_common(10):
    print(f'   • قيمة المديونية {amt:10,.2f} جنيه : مكررة عند {count} طالب')

print('-' * 60)

# 3) التحليل حسب وجود فصل موزع عليه الطالب أم بدون فصل
print('3️⃣ توزيع الطلاب حسب التسكين في الفصول:')
with_class = debtors.filter(classroom__isnull=False).count()
no_class = debtors.filter(classroom__isnull=True).count()
print(f'   • بدون فصل (غير مسكنين) : {no_class} طالب (احتمالية أخطاء ترحيل أو تسجيل غير مكتمل)')
print(f'   • مسكنين بفصول          : {with_class} طالب')

print('-' * 60)

# 4) تصدير التقرير التحليلي التفصيلي
report_path = OUT_DIR + 'debt_causes_analysis.csv'
with open(report_path, 'w', newline='', encoding='utf-8-sig') as f:
    w = csv.writer(f)
    w.writerow(['student_id', 'code', 'name', 'classroom', 'status', 'previous_debt', 'is_active', 'notes'])
    for s in debtors:
        name = f"{s.first_name} {s.last_name or ''}".strip()
        
        # ملاحظات تحليلية تلقائية
        notes = []
        if s.enrollment_status == 'New':
            notes.append('مستجد بمديونية سابقة (يحتاج مراجعة)')
        elif s.enrollment_status == 'Retained':
            notes.append('راسب/باقٍ للإعادة في الصف الأول')
        if not s.classroom:
            notes.append('بدون فصل')
            
        w.writerow([
            s.pk,
            getattr(s, 'student_code', ''),
            name,
            str(s.classroom or '-'),
            s.enrollment_status,
            s.previous_debt,
            s.is_active,
            ' | '.join(notes) if notes else 'طبيعي'
        ])

print(f'✅ تم تصدير التحليل التفصيلي إلى:\n   {report_path}')
print('=' * 60)