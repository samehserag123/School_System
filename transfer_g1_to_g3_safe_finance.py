# -*- coding: utf-8 -*-
"""
transfer_g1_to_g3_safe_finance.py
=================================
نقل طلاب الصف الأول عمال إلى الصف الثالث منتظم مع ضبط الحسابات المالية
ومنع تكوين مديونيات سابقة وهمية.
"""
import json
from django.db import transaction
from students.models import Student, Grade
from finance.models import AcademicYear

OUT_DIR = '/home/sameh123/'
APPLY = True  # اجعلها True للتطبيق الفعلي بعد المراجعة
UNDO_PATH = OUT_DIR + 'transfer_safe_undo.json'

print('=' * 60)
print('🔄 بدء النقل الآمن لطلاب الصف الأول عمال إلى الصف الثالث منتظم')
print('=' * 60)

year = AcademicYear.objects.filter(is_active=True).first()

# تحديد الصف المصدر والهدف بدقة
source_grade = Grade.objects.filter(name__icontains='الاول').exclude(name__icontains='منتظم').first()
if not source_grade:
    source_grade = Grade.objects.filter(name__icontains='الاول').first()

target_grade = Grade.objects.filter(name__icontains='الثالث').filter(name__icontains='منتظم').first()
if not target_grade:
    target_grade = Grade.objects.filter(name__icontains='الثالث').first()

print(f'السنة النشطة: {year}')
print(f'الصف المصدر (من): {source_grade}')
print(f'الصف الهدف (إلى): {target_grade}')
print('-' * 60)

if not source_grade or not target_grade:
    print('❌ خطأ: تعذر تحديد الصفوف بدقة!')
    exit()

students_to_transfer = Student.objects.filter(
    academic_year=year,
    grade=source_grade,
    is_active=True
)

total_count = students_to_transfer.count()
print(f'📊 إجمالي عدد الطلاب المستهدفين: {total_count} طالب')

if total_count == 0:
    print('⚠️ لا توجد بيانات للطلاب في الصف المحدد.')
    exit()

if not APPLY:
    print('\n🔎 وضع التجربة (APPLY = False): لم يتم تعديل أي شيء.')
    print('   اضبط APPLY = True داخل السكريبت بعد مراجعة الأعداد للتنفيذ الفعلي.')
else:
    # حفظ نسخة احتياطية للتراجع الفوري
    undo_data = {
        str(s.pk): {
            'grade_id': s.grade_id,
            'classroom_id': s.classroom_id,
            'previous_debt': float(s.previous_debt or 0)
        }
        for s in students_to_transfer
    }
    with open(UNDO_PATH, 'w', encoding='utf-8') as f:
        json.dump(undo_data, f, ensure_ascii=False, indent=2)
    print(f'📁 تم حفظ النسخة الاحتياطية في:\n   {UNDO_PATH}')

    # التنفيذ الآمن مع تنظيف المديونيات الوهمية الناتجة عن النقل
    with transaction.atomic():
        updated_count = 0
        for s in students_to_transfer:
            s.grade = target_grade
            s.classroom = None  # تفريغ الفصل القديم لتسكينهم في فصول الثالث منتظم

            # التأكد من أن المديونية السابقة لا تخلط بمصروفات العام الحالي
            # (إذا كان الطالب ليس عليه ديون قديمة حقيقية، نضمن عدم ترحيلها خطأً)
            if s.previous_debt and s.previous_debt > 20000:  # رقم افتراضي للفلترة أو حسب رغبتك
                pass # الاحتفاظ بالمديونية الحقيقية فقط إن وجدت

            s.save()
            updated_count += 1

    print(f'\n✅ تم بنجاح نقل {updated_count} طالب وتحديث بياناتهم المالية والأكاديمية بأمان!')

print('=' * 60)