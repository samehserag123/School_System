# -*- coding: utf-8 -*-
"""
fix_grade1_fake_debt.py
========================
إصلاح أزمة المديونيات الوهمية لطلاب الصف الأول:
- تصفير حقل المديونية القديمة (previous_debt = 0) لأنها ناتجة عن خطأ الترحيل.
- الحفاظ على التسكين، المحصل، والمتبقي الشامل دون أي تأثير على بيانات الكاونتر.
"""
import json
from django.db import transaction
from students.models import Student, Grade
from finance.models import AcademicYear

OUT_DIR = '/home/sameh123/'
APPLY = True  # اجعلها True لتطبيق التعديل الفعلي بعد المراجعة
UNDO_PATH = OUT_DIR + 'fix_fake_debt_undo.json'

print('=' * 60)
print('🔧 فحص وإصلاح المديونيات الوهمية لطلاب الصف الأول')
print('=' * 60)

year = AcademicYear.objects.filter(is_active=True).first()
grades = list(Grade.objects.order_by('id'))
first_grade = grades[0] if grades else None

if not year or not first_grade:
    print('❌ تعذر العثور على السنة النشطة أو الصف الأول!')
    exit()

# حصر طلاب الصف الأول الذين لديهم مديونية سابقة وهمية (greater than 0)
target_students = Student.objects.filter(
    academic_year=year,
    grade=first_grade,
    previous_debt__gt=0
)

total_count = target_students.count()
print(f'📊 عدد الطلاب المتأثرين بالمديونية الوهمية: {total_count} طالب')

if not APPLY:
    print('🔎 وضع التجربة (APPLY = False): لم يتم تعديل أي شيء في قاعدة البيانات.')
    print('   ملاحظة: تصفير previous_debt سيجعل خانة "مديونية قديمة" تساوي صفر، وتستقر بقية خانات الكاونتر.')
else:
    # 1) أخذ نسخة احتياطية للتراجع الفوري
    undo_data = {str(s.pk): float(s.previous_debt) for s in target_students}
    with open(UNDO_PATH, 'w', encoding='utf-8') as f:
        json.dump(undo_data, f, ensure_ascii=False, indent=2)
    print(f'📁 تم حفظ النسخة الاحتياطية في: {UNDO_PATH}')

    # 2) التعديل والتنفيذ الآمن
    with transaction.atomic():
        updated_count = 0
        for s in target_students:
            # تصفير المديونية الوهمية القديمة فقط مع الحفاظ على التسكين والمحصل وبقية الحقول
            s.previous_debt = 0
            s.save()
            updated_count += 1

    print(f'✅ تم بنجاح تصحيح وإزالة المديونية الوهمية لـ {updated_count} طالب!')

print('=' * 60)