# -*- coding: utf-8 -*-
"""
audit_grade1_debtors.py
=======================
حصر طلاب الصف الأول (أو أول صف) وعليهم مديونية سابقة (previous_debt > 0)
للكشف عن أي أخطاء محتملة في الترحيل أو تعيين الصفوف.
"""
import csv
from students.models import Student, Grade
from finance.models import AcademicYear

OUT_DIR = '/home/sameh123/'

# 1) جلب السنة النشطة
year = AcademicYear.objects.filter(is_active=True).first()
print('=' * 50)
print('السنة النشطة الحالية:', year)

# 2) تحديد الصف الأول (أول صف حسب الـ id)
grades = list(Grade.objects.order_by('id'))
if not grades:
    print('❌ لا توجد صفوف معرّفة في النظام!')
else:
    first_grade = grades[0]
    print(f'الصف المستهدف بالفحص (الأول): {first_grade.name} (ID: {first_grade.id})')
    print('=' * 50)

    # 3) جلب الطلاب في الصف الأول وعليهم مديونية سابقة
    students = Student.objects.filter(
        academic_year=year,
        grade=first_grade,
        previous_debt__gt=0
    ).select_related('classroom')

    total_count = students.count()
    print(f'📊 إجمالي طلاب الصف الأول وعليهم مديونية سابقة: {total_count} طالب')
    print('-' * 50)

    # 4) طباعة عينة في الـ Console للمراجعة السريعة
    print('عينة من الطلاب (id | الكود | الاسم | الفصل | المديونية السابقة):')
    for s in students[:15]:
        name = f"{s.first_name} {s.last_name or ''}".strip()
        print(f"  {s.pk} | {getattr(s, 'student_code', '')} | {name} | {s.classroom or '-'} | {s.previous_debt}")

    if total_count > 15:
        print(f"  ... ولفحص الباقي بالكامل، تم تصديرهم في ملف الـ CSV.")

    # 5) تصدير تقرير مفصل بصيغة CSV للمراجعة الكاملة
    report_path = OUT_DIR + 'audit_grade1_debtors.csv'
    with open(report_path, 'w', newline='', encoding='utf-8-sig') as f:
        w = csv.writer(f)
        w.writerow(['student_id', 'code', 'name', 'grade', 'classroom', 'enrollment_status', 'previous_debt', 'is_active'])
        for s in students:
            name = f"{s.first_name} {s.last_name or ''}".strip()
            w.writerow([
                s.pk,
                getattr(s, 'student_code', ''),
                name,
                first_grade.name,
                str(s.classroom or ''),
                s.enrollment_status,
                s.previous_debt,
                s.is_active
            ])
            
    print('=' * 50)
    print(f'✅ تم حفظ التقرير المفصل بنجاح في المسار:\n   {report_path}')
    print('يمكنك فتحه ومراجعة أسماء الطلاب للتأكد من صحتهم.')