# -*- coding: utf-8 -*-
"""
reactivate_students.py
======================
إعادة تنشيط الطلاب الذين أُلغي تنشيطهم بسبب الترحيل الخاطئ (التخريج الآلي).

لماذا لا نُنشّط "كل غير النشطين"؟
  لأن بينهم خريجي الأعوام السابقة وغيرهم ممن يجب أن يبقوا غير نشطين.

التوقيع الذي نبحث عنه (كما يكتبه promote_student_action في حالة "لا يوجد صف أعلى"):
  • السنة = السنة النشطة (التخريج الآلي لا يغيّر السنة ولا الصف ولا الفصل)
  • is_active = False
  • enrollment_status = 'Graduated'
  • الصف = أعلى صف في النظام حسب الـ id (هو الذي يُعتبر "لا يوجد صف أعلى منه")
أي طالب غير نشط ولا يطابق هذا التوقيع يظهر في تقرير منفصل **ولا يُلمس**.

⚠️ الوضع الافتراضي: تجربة فقط (APPLY = False) — لا يكتب شيئاً في قاعدة البيانات.

التشغيل (من Bash console داخل مجلد المشروع بعد تفعيل الـ virtualenv):
    python manage.py shell
    exec(open('/home/sameh123/reactivate_students.py', encoding='utf-8').read())

للتطبيق: خذ نسخة احتياطية → CONFIRM_BACKUP=True و APPLY=True → أعد التشغيل.
للتراجع:  undo_reactivate()
"""
import csv
import datetime
import json
from collections import Counter

from django.db import transaction
from students.models import Student, Grade
from finance.models import AcademicYear

# =========================== الإعدادات ===========================
OUT_DIR = '/home/sameh123/'
YEAR_NAME = None                 # None = السنة النشطة
APPLY = True                    # ← False = تجربة فقط
CONFIRM_BACKUP = True           # ← لا يُسمح بالتطبيق قبل أن تضعها True (بعد أخذ نسخة احتياطية)

# الحالة الجديدة بعد التنشيط. في نظامك: 'New' (مستجد) هي حالة طالب العام الجاري بعد الترقية،
# و'Graduated' لا تُعطى إلا في نهاية العام. ضع None لو تريد ترك الحالة كما هي.
NEW_STATUS = 'New'

REACTIVATE_STATUSES = ['Graduated']      # الحالات التي تُعتبر أثر التخريج الآلي
USE_TOP_GRADE_FILTER = True              # True = فقط من هم في أعلى صف (الأدق)
INCLUDE_ALL_INACTIVE_IN_YEAR = False     # ⚠️ True = كل غير النشطين في السنة (لا تستخدمه إلا بعد مراجعة التقرير)
EXTRA_IDS = []                           # طلاب تريد تنشيطهم يدوياً (ids) حتى لو لم يطابقوا التوقيع
EXCLUDE_IDS = []                         # طلاب لا تريد تنشيطهم أبداً (ids)

UNDO_PATH = OUT_DIR + 'reactivate_undo.json'


def hr(t):
    print('\n' + '=' * 10, t, '=' * 10)


def undo_reactivate(path=UNDO_PATH):
    """يرجّع is_active والحالة القديمة لمن نُشّطوا في آخر تطبيق."""
    data = json.load(open(path, encoding='utf-8'))
    with transaction.atomic():
        for pk, old in data.items():
            Student.objects.filter(pk=int(pk)).update(**old)
    print('تم التراجع عن', len(data), 'طالباً من', path)


# =========================== 1) السنة والصفوف ===========================
hr('1) السنة وأعلى صف')
year = (AcademicYear.objects.filter(name=YEAR_NAME).first() if YEAR_NAME
        else AcademicYear.objects.filter(is_active=True).first())
print('السنة:', year)
grades = list(Grade.objects.order_by('id').values_list('id', 'name'))
top_id, top_name = (grades[-1] if grades else (None, None))
print('الصفوف (id | الاسم):')
for gid, nm in grades:
    print('  ', gid, '|', nm, '   ← أعلى صف بالـ id (يُخرَّج آلياً)' if gid == top_id else '')

# =========================== 2) الصورة الكاملة لغير النشطين ===========================
hr('2) كل غير النشطين في السنة (للمراجعة)')
inactive = list(Student.objects.filter(academic_year=year, is_active=False).select_related('grade', 'classroom'))
print('إجمالي غير النشطين في %s: %d' % (year, len(inactive)))
print('حسب (الصف، الحالة)  [العدد]:')
for (g, st), n in Counter((s.grade.name if s.grade else '؟', s.enrollment_status) for s in inactive).most_common():
    print('   ', g, '|', st, ':', n)
print('منهم عليهم مديونية سابقة:', sum(1 for s in inactive if (s.previous_debt or 0) > 0))

print('\nللمقارنة — توزيع حالات الطلاب النشطين في نفس السنة:')
active_stat = Counter(Student.objects.filter(academic_year=year, is_active=True).values_list('enrollment_status', flat=True))
print('  ', dict(active_stat))
print('خيارات الحالة المتاحة في النظام:', [v for v, _ in (Student._meta.get_field('enrollment_status').choices or [])])

# =========================== 3) المرشحون ===========================
hr('3) المرشحون للتنشيط')
cands, others = [], []
for s in inactive:
    if s.pk in EXCLUDE_IDS:
        others.append((s, 'مستبعد يدوياً (EXCLUDE_IDS)'))
        continue
    if s.pk in EXTRA_IDS or INCLUDE_ALL_INACTIVE_IN_YEAR:
        cands.append(s)
        continue
    reasons = []
    if s.enrollment_status not in REACTIVATE_STATUSES:
        reasons.append('حالته "%s" ليست ضمن %s' % (s.enrollment_status, REACTIVATE_STATUSES))
    if USE_TOP_GRADE_FILTER and s.grade_id != top_id:
        reasons.append('ليس في أعلى صف (%s)' % top_name)
    (others if reasons else cands).append((s, '؛ '.join(reasons)) if reasons else s)

cands = [c for c in cands if not isinstance(c, tuple)]
print('سيُنشَّط:', len(cands), '| لن يُلمس:', len(others))
print('المرشحون حسب الصف:', dict(Counter(c.grade.name if c.grade else '؟' for c in cands)))
print('منهم عليهم مديونية سابقة:', sum(1 for c in cands if (c.previous_debt or 0) > 0),
      '(قيمتها كُتبت وقت الترحيل الخاطئ — لا يغيّرها هذا السكريبت)')
print('بدون فصل:', sum(1 for c in cands if c.classroom_id is None), '| بفصل:', sum(1 for c in cands if c.classroom_id))
print('عيّنة (id | الاسم | الصف | الفصل):')
for c in cands[:12]:
    print('   ', c.pk, '|', ('%s %s' % (c.first_name, c.last_name or '')).strip(), '|',
          c.grade.name if c.grade else '؟', '|', c.classroom or '-')
if NEW_STATUS:
    print('\nالحالة الجديدة: %s (كانت Graduated)' % NEW_STATUS)
else:
    print('\nلن تُغيَّر الحالة (NEW_STATUS=None) — سيبقى الطالب نشطاً بحالة Graduated')

# =========================== 4) التقارير ===========================
hr('4) كتابة التقارير')
with open(OUT_DIR + 'reactivate_plan.csv', 'w', newline='', encoding='utf-8-sig') as f:
    w = csv.writer(f)
    w.writerow(['student_id', 'code', 'name', 'grade', 'classroom', 'is_active_old', 'is_active_new',
                'status_old', 'status_new', 'previous_debt'])
    for c in cands:
        w.writerow([c.pk, getattr(c, 'student_code', ''), ('%s %s' % (c.first_name, c.last_name or '')).strip(),
                    c.grade.name if c.grade else '', c.classroom or '', False, True,
                    c.enrollment_status, NEW_STATUS or c.enrollment_status, c.previous_debt])
with open(OUT_DIR + 'reactivate_not_touched.csv', 'w', newline='', encoding='utf-8-sig') as f:
    w = csv.writer(f)
    w.writerow(['student_id', 'code', 'name', 'grade', 'status', 'why_not'])
    for s, why in others:
        w.writerow([s.pk, getattr(s, 'student_code', ''), ('%s %s' % (s.first_name, s.last_name or '')).strip(),
                    s.grade.name if s.grade else '', s.enrollment_status, why])
print('reactivate_plan.csv         (من سيُنشَّط: القديم ← الجديد)')
print('reactivate_not_touched.csv  (غير النشطين الذين لن يُلمسوا وسبب ذلك)')
print('في:', OUT_DIR)

# =========================== 5) التطبيق ===========================
hr('5) التطبيق')
if not APPLY:
    print('🔎 وضع التجربة: لم يُكتب أي شيء في قاعدة البيانات.')
    print('   راجع الملفين، ثم: نسخة احتياطية → CONFIRM_BACKUP=True و APPLY=True → أعد التشغيل.')
elif not CONFIRM_BACKUP:
    print('⛔ APPLY=True لكن CONFIRM_BACKUP=False — تم الإيقاف. خذ نسخة احتياطية أولاً.')
else:
    undo = {str(c.pk): {'is_active': False, 'enrollment_status': c.enrollment_status} for c in cands}
    json.dump(undo, open(UNDO_PATH, 'w', encoding='utf-8'), ensure_ascii=False)   # يُكتب قبل أي تعديل
    with transaction.atomic():
        for c in cands:
            vals = {'is_active': True}
            if NEW_STATUS:
                vals['enrollment_status'] = NEW_STATUS
            Student.objects.filter(pk=c.pk).update(**vals)
    print('✅ تم تنشيط %d طالباً. ملف التراجع: %s' % (len(cands), UNDO_PATH))
    print('   للتراجع: undo_reactivate()')