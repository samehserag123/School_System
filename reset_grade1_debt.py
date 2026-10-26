# -*- coding: utf-8 -*-
"""
reset_grade1_debt.py
====================
إسقاط وتصفير المديونية السابقة (previous_debt = 0) لطلاب الصف الأول فقط
الذين تم ترحيلهم أو تسكير مديونيتهم الخاطئة.

⚠️ الوضع الافتراضي: تجربة فقط (APPLY = False) — لا يكتب شيئاً في قاعدة البيانات.
"""
import csv
import json
from django.db import transaction
from students.models import Student, Grade
from finance.models import AcademicYear

# =========================== الإعدادات ===========================
OUT_DIR = '/home/sameh123/'
APPLY = True            # ← اجعلها True لتطبيق التعديل الفعلي
CONFIRM_BACKUP = True  # ← اجعلها True بعد التأكد وأخذ نسخة احتياطية

UNDO_PATH = OUT_DIR + 'reset_grade1_debt_undo.json'

# =========================== 1) تحديد السنة والصف الأول ===========================
print('=' * 60)
print('🔄 بدء عملية إسقاط المديونية السابقة لطلاب الصف الأول')
print('=' * 60)

year = AcademicYear.objects.filter(is_active=True).first()
grades = list(Grade.objects.order_by('id'))

if not year or not grades:
    print('❌ تعذر العثور على السنة النشطة أو الصفوف!')
    exit()

first_grade = grades[0]  # أول صف في النظام (الصف الأول)
print(f'السنة النشطة: {year}')
print(f'الصف المستهدف: {first_grade.name} (ID: {first_grade.id})')
print('-' * 60)

# =========================== 2) حصر الطلاب المستهدفين ===========================
target_students = Student.objects.filter(
    academic_year=year,
    grade=first_grade,
    previous_debt__gt=0
)

total_count = target_students.count()
total_debt = sum(s.previous_debt or 0 for s in target_students)

print(f'📊 إجمالي عدد الطلاب المستهدفين بالإسقاط: {total_count} طالب')
print(f'💰 إجمالي قيمة المديونيات المقرر إسقاطها: {total_debt:,.2f} جنيه')
print('-' * 60)

# =========================== 3) كتابة تقرير المراجعة ===========================
report_path = OUT_DIR + 'reset_grade1_debt_plan.csv'
with open(report_path, 'w', newline='', encoding='utf-8-sig') as f:
    w = csv.writer(f)
    w.writerow(['student_id', 'code', 'name', 'grade', 'status', 'old_previous_debt', 'new_previous_debt'])
    for s in target_students:
        name = f"{s.first_name} {s.last_name or ''}".strip()
        w.writerow([s.pk, getattr(s, 'student_code', ''), name, first_grade.name, s.enrollment_status, s.previous_debt, 0])

print(f'📄 تم حفظ تقرير الطلاب المستهدفين في:\n   {report_path}')
print('-' * 60)

# =========================== 4) التنفيذ والتطبيق ===========================
if not APPLY:
    print('🔎 وضع التجربة (APPLY = False): لم يتم تعديل أي شيء في قاعدة البيانات.')
    print('   المراجعة: راجع التقرير أعلاه، ثم اضبط APPLY=True و CONFIRM_BACKUP=True في الملف لتنفيذ التعديل.')
elif not CONFIRM_BACKUP:
    print('⛔ تم الإيقاف: APPLY=True لكن CONFIRM_BACKUP=False. يرجى تأكيد النسخ الاحتياطي أولاً.')
else:
    # إنشاء ملف التراجع Undo
    undo_data = {str(s.pk): float(s.previous_debt) for s in target_students}
    with open(UNDO_PATH, 'w', encoding='utf-8') as f:
        json.dump(undo_data, f, ensure_ascii=False, indent=2)

    # تحديث قاعدة البيانات داخل المعاملة (Transaction)
    with transaction.atomic():
        updated = target_students.update(previous_debt=0)

    print(f'✅ تم بنجاح إسقاط وتصفير المديونية القديمة لـ {updated} طالب في الصف الأول!')
    print(f'📁 تم حفظ سجل التراجع في: {UNDO_PATH}')
    print('   للتراجع عند الحاجة: أعد استيراد القيم من ملف json الأخير.')

print('=' * 60)