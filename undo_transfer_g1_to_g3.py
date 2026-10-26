# -*- coding: utf-8 -*-
"""
undo_transfer_g1_to_g3.py
=========================
التراجع الفوري عن عملية نقل الطلاب واستعادة صفوفهم وفصولهم الأصلية
من واقع ملف النسخة الاحتياطية transfer_g1_to_g3_undo.json
"""
import os
import json
from django.db import transaction
from students.models import Student

UNDO_PATH = '/home/sameh123/transfer_g1_to_g3_undo.json'

# إذا لم يكن في المسار المطلق، ابحث في المجلد الحالي
if not os.path.exists(UNDO_PATH):
    UNDO_PATH = 'transfer_g1_to_g3_undo.json'

print('=' * 60)
print('🚨 بدء التراجع الفوري عن عملية النقل لطلاب الصف الأول')
print('=' * 60)

if not os.path.exists(UNDO_PATH):
    print(f'❌ خطأ: ملف النسخة الاحتياطية غير موجود في المسار:\n   {UNDO_PATH}')
    exit()

with open(UNDO_PATH, 'r', encoding='utf-8') as f:
    undo_data = json.load(f)

print(f'📊 تم العثور على سجلات احتياطية لـ {len(undo_data)} طالب.')

restored_count = 0
with transaction.atomic():
    for student_id_str, data in undo_data.items():
        updated = Student.objects.filter(pk=int(student_id_str)).update(
            grade_id=data['grade_id'],
            classroom_id=data['classroom_id']
        )
        restored_count += updated

print(f'✅ تم التراجع بنجاح وإعادة {restored_count} طالب إلى صفوفهم وفصولهم الأصلية تماماً!')
print('=' * 60)