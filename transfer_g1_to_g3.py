# -*- coding: utf-8 -*-
"""
transfer_g1_to_g3.py
====================
تحويل طلاب الصف الأول عمال إلى الصف الثالث منتظم بدون أي مشاكل مالية.
"""
import json
from django.db import transaction
from students.models import Student, Grade
from finance.models import AcademicYear

OUT_DIR = '/home/sameh123/'
APPLY = True  # اجعلها True للتطبيق الفعلي بعد المراجعة
UNDO_PATH = OUT_DIR + 'transfer_g1_to_g3_undo.json'

print('=' * 60)
print('🔄 بدء عملية نقل طلاب الصف الأول عمال إلى الصف الثالث منتظم')
print('=' * 60)

year = AcademicYear.objects.filter(is_active=True).first()

# البحث عن الصف المصدر والهدف
source_grade = Grade.objects.filter(name__icontains='الاول').exclude(name__icontains='منتظم').first()
if not source_grade:
    source_grade = Grade.objects.filter(name__icontains='الاول').first()

target_grade = Grade.objects.filter(name__icontains='الثالث').first()

print(f'السنة النشطة: {year}')
print(f'الصف المصدر (من): {source_grade}')
print(f'الصف الهدف (إلى): {target_grade}')
print('-' * 60)

if not source_grade or not target_grade:
    print('❌ خطأ: تعذر العثور على الصف المصدر أو الصف الهدف بدقة!')
    exit()

students_to_transfer = Student.objects.filter(
    academic_year=year,
    grade=source_grade,
    is_active=True
)

total_count = students_to_transfer.count()
print(f'📊 إجمالي عدد الطلاب المستهدفين بالنقل: {total_count} طالب')

if total_count == 0:
    print('⚠️ لا يوجد طلاب حالياً في الصف المحدد.')
    exit()

if not APPLY:
    print('\n🔎 وضع التجربة (APPLY = False): لم يتم تعديل أي شيء في قاعدة البيانات.')
    print('   اضبط APPLY = True داخل السكريبت بعد مراجعة الأعداد ثم أعد تشغيله للتنفيذ الفعلي.')
else:
    # حفظ نسخة احتياطية للتراجع الفوري
    undo_data = {
        str(s.pk): {
            'grade_id': s.grade_id,
            'classroom_id': s.classroom_id
        }
        for s in students_to_transfer
    }
    with open(UNDO_PATH, 'w', encoding='utf-8') as f:
        json.dump(undo_data, f, ensure_ascii=False, indent=2)
    print(f'📁 تم حفظ النسخة الاحتياطية للتراجع في:\n   {UNDO_PATH}')

    # التنفيذ الآمن
    with transaction.atomic():
        updated_count = 0
        for s in students_to_transfer:
            s.grade = target_grade
            s.classroom = None  # تفريغ الفصل القديم لتسكينهم في فصول الصف الثالث الجديدة
            # الحفاظ التام على المديونيات، الأقساط، والمُحصل دون المساس بها
            s.save()
            updated_count += 1

    print(f'\n✅ تم بنجاح نقل {updated_count} طالب إلى الصف الثالث منتظم!')
    print('💡 ملحوظة: لم يتم المساس بالحسابات المالية أو الترحيلات، لضمان استقرار الشاشات تماماً.')

print('=' * 60)
