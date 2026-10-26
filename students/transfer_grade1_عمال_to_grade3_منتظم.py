# -*- coding: utf-8 -*-
"""
transfer_grade1_عمال_to_grade3_منتظم.py
======================================
تحويل طلاب "الصف الأول عمال" إلى "الصف الثالث منتظم"
بدون التسبب في أي خلل أو مشاكل مالية أو ترحيل خاطئ.
"""
import json
from django.db import transaction
from students.models import Student, Grade, Classroom
from finance.models import AcademicYear

OUT_DIR = '/home/sameh123/'
APPLY = False  # اجعلها True للتطبيق الفعلي بعد المراجعة
UNDO_PATH = OUT_DIR + 'transfer_grade1_to_grade3_undo.json'

print('=' * 60)
print('🔄 بدء عملية نقل طلاب (الصف الأول عمال) إلى (الصف الثالث منتظم)')
print('=' * 60)

year = AcademicYear.objects.filter(is_active=True).first()

# 1. تحديد الصفوف المستهدفة
source_grade = Grade.objects.filter(name__icontains='الاول', name__icontains='عمال').first()
target_grade = Grade.objects.filter(name__icontains='الثالث', name__icontains='منتظم').first()

if not source_grade:
    # محاولة البديل إذا كان الاسم مختلفاً قليلاً
    source_grade = Grade.objects.filter(name__icontains='الاول').exclude(name__icontains='منتظم').first()

if not target_grade:
    target_grade = Grade.objects.filter(name__icontains='الثالث').first()

print(f'السنة النشطة: {year}')
print(f'الصف المصدر (من): {source_grade}')
print(f'الصف الهدف (إلى): {target_grade}')
print('-' * 60)

if not source_grade or not target_grade:
    print('❌ خطأ: تعذر العثور على الصف المصدر أو الصف الهدف! يرجى مراجعة أسماء الصفوف في النظام.')
    exit()

# 2. حصر الطلاب
students_to_transfer = Student.objects.filter(
    academic_year=year,
    grade=source_grade,
    is_active=True
)

total_count = students_to_transfer.count()
print(f'📊 إجمالي عدد الطلاب المستهدفين بالنقل: {total_count} طالب')

if total_count == 0:
    print('⚠️ لا يوجد طلاب حالياً في الصف المحدد للنقل.')
    exit()

if not APPLY:
    print('\n🔎 وضع التجربة (APPLY = False):')
    print('   لم يتم تعديل أي شيء في قاعدة البيانات.')
    print('   للتطبيق الفعلي: افتح السكريبت واضبط APPLY = True ثم أعد التشغيل.')
else:
    # 3. حفظ نسخة احتياطية للتراجع
    undo_data = {
        str(s.pk): {
            'grade_id': s.grade_id,
            'classroom_id': s.classroom_id,
            'enrollment_status': s.enrollment_status
        }
        for s in students_to_transfer
    }
    with open(UNDO_PATH, 'w', encoding='utf-8') as f:
        json.dump(undo_data, f, ensure_ascii=False, indent=2)
    print(f'📁 تم حفظ سجل النسخة الاحتياطية في:\n   {UNDO_PATH}')

    # 4. التنفيذ الآمن داخل معاملة ذرية (Transaction)
    with transaction.atomic():
        updated_count = 0
        for s in students_to_transfer:
            s.grade = target_grade
            s.classroom = None  # تفريغ الفصل القديم ليتم تسكينهم في فصول الصف الثالث الجديدة
            # الحفاظ التام على المديونية السابقة والأقساط والمُحصل كما هي بدون تعديل
            s.save()
            updated_count += 1

    print(f'\n✅ تم بنجاح نقل {updated_count} طالب من {source_grade.name} إلى {target_grade.name}!')
    print('💡 ملحوظة: لم يتم المساس بالحسابات أو المديونيات أو السجلات المالية إطلاقاً.')

print('=' * 60)