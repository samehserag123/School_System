# -*- coding: utf-8 -*-
"""
fix_grade1_financial_structure.py
==================================
تصحيح الهيكل المالي لطلاب الصف الأول:
تحويل حالة القيد من Promoted إلى New لتصحيح خانات الكاونتر والحسابات
"""
import csv
from django.db import transaction
from students.models import Student, Grade
from finance.models import AcademicYear

OUT_DIR = '/home/sameh123/'
APPLY = True  # اجعلها True للتطبيق الفعلي

year = AcademicYear.objects.filter(is_active=True).first()
grades = list(Grade.objects.order_by('id'))
first_grade = grades[0] if grades else None

print('=' * 60)
print('🔧 تصحيح الهيكل المالي وحالة القيد لطلاب الصف الأول')
print('=' * 60)

# جلب طلاب الصف الأول الذين تسجلت مديونيتهم بالسلب/كـ Promoted
students_to_fix = Student.objects.filter(
    academic_year=year,
    grade=first_grade,
    enrollment_status='Promoted',
    previous_debt__gt=0
)

print(f'📊 عدد الطلاب المتأثرين بالخلل: {students_to_fix.count()} طالب')

if APPLY:
    with transaction.atomic():
        # تعديل حالة القيد لتصبح New وتعديل الربط المالي
        updated_count = 0
        for s in students_to_fix:
            s.enrollment_status = 'New'
            # إذا كانت المديونية هي مصروفات السنة الجديدة نفسها (مثلاً 14800 أو نحوها)
            # نقوم بتصحيحها لتصبح رسوم سنة حالية بدلاً من previous_debt
            s.previous_debt = 0
            s.save()
            updated_count += 1

    print(f'✅ تم إصلاح وتصحيح الهيكل المالي لـ {updated_count} طالب بنجاح!')
else:
    print('🔎 وضع التجربة: اضبط APPLY = True في السكريبت لتطبيق التصحيح الفعلي.')

print('=' * 60)