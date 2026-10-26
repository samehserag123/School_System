# -*- coding: utf-8 -*-
"""
undo_fix_from_csv.py
====================
التراجع عن تعديلات الهيكل المالي باستخدام ملف الـ CSV الأصلي
لإعادة حالة القيد إلى وضعها الأصلي (Promoted) واستعادة المديونية القديمة.
"""
import csv
from django.db import transaction
from students.models import Student

CSV_PATH = '/home/sameh123/debt_causes_analysis.csv'

print('=' * 60)
print('🚨 بدء التراجع الشامل واستعادة البيانات الأصلية لطلاب الصف الأول')
print('=' * 60)

restored_count = 0
try:
    with open(CSV_PATH, 'r', encoding='utf-8-sig') as f:
        reader = csv.DictReader(f)
        with transaction.atomic():
            for row in reader:
                s_id = int(row['student_id'])
                orig_status = row['status']        # Promoted أو Retained
                orig_debt = float(row['previous_debt'])
                
                # استعادة الحالة والمديونية الأصلية
                updated = Student.objects.filter(pk=s_id).update(
                    enrollment_status=orig_status,
                    previous_debt=orig_debt
                )
                restored_count += updated

    print(f'✅ تم التراجع بنجاح وإعادة حالة القيد والمديونيات لـ {restored_count} طالب إلى وضعهم الأصلي!')
except Exception as e:
    print(f'❌ حدث خطأ أثناء التراجع: {e}')

print('=' * 60)