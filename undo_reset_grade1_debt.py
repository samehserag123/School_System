# -*- coding: utf-8 -*-
"""
undo_reset_grade1_debt.py
=========================
تراجع فوري عن عملية إسقاط المديونيات وإعادة القيم الأصليّة
من واقع ملف النسخة الاحتياطية reset_grade1_debt_undo.json
"""
import os
import json
from django.db import transaction
from students.models import Student

OUT_DIR = '/home/sameh123/'
UNDO_PATH = OUT_DIR + 'reset_grade1_debt_undo.json'

print('=' * 60)
print('🚨 بدء عملية التراجع الفوري عن تصفير مديونيات الصف الأول')
print('=' * 60)

if not os.path.exists(UNDO_PATH):
    print(f'❌ خطأ: ملف التراجع غير موجود في المسار:\n   {UNDO_PATH}')
    exit()

# 1) قراءة بيانات التراجع الاحتياطية
with open(UNDO_PATH, 'r', encoding='utf-8') as f:
    undo_data = json.load(f)

total_students = len(undo_data)
total_restored_debt = sum(undo_data.values())

print(f'📊 تم العثور على سجلات احتياطية لـ {total_students} طالب.')
print(f'💰 إجمالي المديونيات المطلوبة إعادتها: {total_restored_debt:,.2f} جنيه.')
print('-' * 60)

# 2) تطبيق التراجع وإعادة المديونيات في قاعدة البيانات
restored_count = 0
with transaction.atomic():
    for student_id_str, old_debt in undo_data.items():
        s_id = int(student_id_str)
        updated = Student.objects.filter(pk=s_id).update(previous_debt=old_debt)
        restored_count += updated

print(f'✅ تم التراجع بنجاح وإعادة المديونيات السابقة لـ {restored_count} طالب إلى وضعهم الأصلي!')
print('=' * 60)