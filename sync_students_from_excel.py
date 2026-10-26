# -*- coding: utf-8 -*-
"""
sync_students_from_excel.py
===========================
يطابق أسماء ملف الإكسيل مع الطلاب في قاعدة البيانات، وللمطابِق فقط يحدّث:
  • الفصل (classroom)         ← من عنوان الفصل في الإكسيل (مثل: فصل 1 / 3)
  • الشعبة (specialization)    ← من عنوان الفصل (شعبة عامة)
  • الديانة (religion)         ← من عمود الديانة
  • النوع (gender)             ← من الرقم القومي (ويُتحقق منه بعنوان الفصل بنات/بنين)
  • تاريخ الميلاد (date_of_birth) ← من الرقم القومي (فقط إذا كان فارغاً)
  • محل الميلاد (birth_place)   ← المحافظة من الرقم القومي (فقط إذا كان فارغاً)
الأسماء غير الموجودة في قاعدة البيانات تُتجاهل وتظهر في التقرير فقط.

⚠️ الوضع الافتراضي: تجربة فقط (APPLY = False) — لا يكتب شيئاً في قاعدة البيانات.
   يكتب فقط ملفات تقارير CSV في OUT_DIR.

التشغيل (من Bash console داخل مجلد المشروع بعد تفعيل الـ virtualenv):
    python manage.py shell
    exec(open('/home/sameh123/sync_students_from_excel.py', encoding='utf-8').read())

للتطبيق الفعلي بعد مراجعة التقارير: غيّر APPLY و CONFIRM_BACKUP إلى True (بعد أخذ نسخة احتياطية).
للتراجع عن آخر تطبيق:  undo_sync('/home/sameh123/sync_undo.json')
"""
import csv
import datetime
import difflib
import json
import re
from collections import Counter, defaultdict

from django.db import transaction
from students.models import Student, Grade, Classroom
from finance.models import AcademicYear

# =========================== الإعدادات ===========================
INPUT_PATH = '/home/sameh123/smart_school_2026/grade1.xlsx.csv'
SHEET_NAME = 'قائمة'                           # اسم الورقة التي فيها الفصول
OUT_DIR = '/home/sameh123/'                    # مكان حفظ التقارير
GRADE_KEYWORD = 'الاول'                        # الصف المقصود (يُطابَق مع اسم الصف في النظام)
YEAR_NAME = None                               # None = السنة النشطة، أو مثلاً '2026/2027'

APPLY = True                                  # ← False = تجربة فقط. True = تطبيق فعلي
CONFIRM_BACKUP = True                         # ← لا يُسمح بالتطبيق إلا بعد أن تضعها True (بعد النسخة الاحتياطية)
OVERWRITE_BIRTH = False                        # False = لا نغيّر تاريخ/محل ميلاد موجود
FUZZY_CUTOFF = 0.90                            # حساسية اقتراحات الأسماء المتشابهة (تظهر في التقرير فقط)

CLASSROOM_MAP = {}     # لو أسماء الفصول في النظام مختلفة. مثال: {(1, 1): 'فصل أ', (1, 2): 'فصل ب'}
MANUAL_MATCH = {}      # مطابقة يدوية لاحقاً. مثال: {'اسم كما في الإكسيل': 1234}  (الرقم = id الطالب)
BIRTH_PLACE_OVERRIDE = {}   # لو صيغة محل الميلاد في نظامك مختلفة. مثال: {'12': 'Dakahlia'}

UNDO_PATH = OUT_DIR + 'sync_undo.json'

# =========================== أدوات ===========================
_TASH = re.compile(r'[\u0610-\u061A\u064B-\u065F\u0670\u06D6-\u06ED\u0640]')
_MAP = str.maketrans({'أ': 'ا', 'إ': 'ا', 'آ': 'ا', 'ٱ': 'ا', 'ى': 'ي', 'ئ': 'ي',
                      'ؤ': 'و', 'ة': 'ه', 'ک': 'ك', 'ی': 'ي'})
_DIG = str.maketrans('٠١٢٣٤٥٦٧٨٩۰۱۲۳۴۵۶۷۸۹', '0123456789' * 2)

GOV = {'01': 'القاهرة', '02': 'الإسكندرية', '03': 'بورسعيد', '04': 'السويس', '11': 'دمياط',
       '12': 'الدقهلية', '13': 'الشرقية', '14': 'القليوبية', '15': 'كفر الشيخ', '16': 'الغربية',
       '17': 'المنوفية', '18': 'البحيرة', '19': 'الإسماعيلية', '21': 'الجيزة', '22': 'بني سويف',
       '23': 'الفيوم', '24': 'المنيا', '25': 'أسيوط', '26': 'سوهاج', '27': 'قنا', '28': 'أسوان',
       '29': 'الأقصر', '31': 'البحر الأحمر', '32': 'الوادي الجديد', '33': 'مطروح',
       '34': 'شمال سيناء', '35': 'جنوب سيناء', '88': 'خارج الجمهورية'}


def norm(s):
    """توحيد الحروف المتشابهة والمسافات (عبد الله = عبدالله، أحمد = احمد، ...)."""
    s = str(s or '').translate(_DIG)
    s = _TASH.sub('', s).translate(_MAP)
    s = re.sub(r'[^\w\s]', ' ', s)
    s = re.sub(r'\s+', ' ', s).strip()
    s = re.sub(r'\bعبد (?=\S)', 'عبد', s)
    return s


def parse_nid(nid):
    """الرقم القومي المصري: خانة القرن + YYMMDD + كود المحافظة + 4 أرقام (الثالثة عشرة: فردي ذكر/زوجي أنثى)."""
    d = re.sub(r'\D', '', str(nid or '').translate(_DIG))
    if len(d) != 14 or d[0] not in '23':
        return None
    try:
        dob = datetime.date((1900 if d[0] == '2' else 2000) + int(d[1:3]), int(d[3:5]), int(d[5:7]))
    except ValueError:
        return None
    return {'dob': dob, 'code': d[7:9], 'gov': GOV.get(d[7:9]),
            'gender': 'Male' if int(d[12]) % 2 == 1 else 'Female'}


def nid_reason(nid):
    d = re.sub(r'\D', '', str(nid or '').translate(_DIG))
    if not d:
        return 'الرقم القومي فارغ'
    if len(d) != 14:
        return 'طول الرقم القومي %d (المطلوب 14)' % len(d)
    if d[0] not in '23':
        return 'خانة القرن %s (المتوقع 2 أو 3)' % d[0]
    return 'تاريخ الميلاد داخل الرقم القومي غير صالح'


def read_input(path):
    rows = []
    if path.lower().endswith('.csv'):
        with open(path, newline='', encoding='utf-8-sig') as f:
            for r in csv.DictReader(f):
                rows.append(dict(name=' '.join(r['name'].split()), religion=r['religion'].strip(),
                                 grade_no=int(r['grade_no']), class_no=int(r['class_no']),
                                 spec=r['specialization'].strip(), gender=r['gender'].strip()))
        return rows
    import openpyxl
    ws = openpyxl.load_workbook(path, data_only=True)[SHEET_NAME]
    cls = None
    for r in ws.iter_rows(values_only=True):
        txt = ' '.join(str(v).strip() for v in r if v not in (None, ''))
        m = re.search(r'فصل\s*(\d+)\s*/\s*(\d+)', txt)
        if m:
            sp = re.search(r'شعبة\s*\(\s*(.*?)\s*\)', txt)
            g = 'بنات' if 'بنات' in txt else ('بنين' if 'بنين' in txt else '')
            cls = (int(m.group(1)), int(m.group(2)), sp.group(1) if sp else '', g)
            continue
        if cls is None:
            continue
        for a, b in ((0, 1), (2, 3)):
            nm = r[a] if a < len(r) else None
            if isinstance(nm, str) and nm.strip() and 'اسم الطالب' not in nm:
                rel = r[b].strip() if b < len(r) and isinstance(r[b], str) else ''
                rows.append(dict(name=' '.join(nm.split()), religion=rel, grade_no=cls[0],
                                 class_no=cls[1], spec=cls[2], gender=cls[3]))
    return rows


def hr(t):
    print('\n' + '=' * 10, t, '=' * 10)


def _ser(v):
    return v.isoformat() if isinstance(v, (datetime.date, datetime.datetime)) else v


def undo_sync(path=UNDO_PATH):
    """يرجّع القيم القديمة التي سجّلها آخر تطبيق."""
    data = json.load(open(path, encoding='utf-8'))
    date_fields = {'date_of_birth'}
    with transaction.atomic():
        for pk, old in data.items():
            vals = {f: (datetime.date.fromisoformat(v) if f in date_fields and v else v) for f, v in old.items()}
            Student.objects.filter(pk=int(pk)).update(**vals)
    print('تم التراجع عن', len(data), 'طالباً من', path)


# =========================== 1) قراءة الإكسيل ===========================
hr('1) قراءة الإكسيل')
xrows = read_input(INPUT_PATH)
print('عدد الأسماء في الإكسيل:', len(xrows))
print('الفصول:', dict(Counter((r['grade_no'], r['class_no'], r['spec'], r['gender']) for r in xrows)))

# =========================== 2) طلاب قاعدة البيانات ===========================
hr('2) طلاب النظام')
year = (AcademicYear.objects.filter(name=YEAR_NAME).first() if YEAR_NAME
        else AcademicYear.objects.filter(is_active=True).first())
print('السنة:', year)
all_students = list(Student.objects.filter(academic_year=year).select_related('grade', 'classroom'))


def mk(s):
    full = ('%s %s' % (s.first_name or '', s.last_name or '')).strip()
    nid = parse_nid(getattr(s, 'national_id', None))
    return {'obj': s, 'tokens': norm(full).split(), 'full': full, 'nid': nid,
            'gender': getattr(s, 'gender', None) or (nid['gender'] if nid else None)}


recs = {s.pk: mk(s) for s in all_students}
kw = norm(GRADE_KEYWORD)
pool = [r for r in recs.values() if r['obj'].grade and kw in norm(r['obj'].grade.name)]
print('كل طلاب السنة:', len(recs), '| طلاب الصف المقصود:', len(pool))
print('الصفوف:', dict(Counter(r['obj'].grade.name for r in pool)))
if not pool:
    print('⚠️ لا يوجد طلاب في هذا الصف/السنة. تأكد من YEAR_NAME و GRADE_KEYWORD ومن أن الطلاب عادوا للسنة الصحيحة.')

# الفصول المتاحة
classrooms = defaultdict(list)
for c in Classroom.objects.all():
    classrooms[c.grade_id].append(c)
print('الفصول المسجلة للصف (id | grade_id | الاسم):')
for _g in sorted({r['obj'].grade_id for r in pool}):
    _gn = next(r['obj'].grade.name for r in pool if r['obj'].grade_id == _g)
    print('  grade_id=%s  %s  (طلاب الإكسيل/النظام في هذا الصف: %d)' % (_g, _gn, sum(1 for r in pool if r['obj'].grade_id == _g)))
    for c in classrooms.get(_g, []):
        print('    ', c.id, '|', c.grade_id, '|', repr(c.name))
    if not classrooms.get(_g):
        print('     (لا توجد فصول مسجلة لهذا الصف)')


def find_classroom(grade_id, grade_no, class_no):
    """يطابق اسم الفصل في النظام مع (صف/فصل) من الإكسيل. يفهم: 1/3 ، 1 / 3 ، فصل 1/3 ، فصل 3 ."""
    cands = []
    for c in classrooms.get(grade_id, []):
        if (grade_no, class_no) in CLASSROOM_MAP:
            if norm(c.name) == norm(CLASSROOM_MAP[(grade_no, class_no)]):
                cands.append(c)
            continue
        raw = str(c.name or '').translate(_DIG)
        m = re.search(r'(\d+)\s*[/\\\-]\s*(\d+)', raw)
        if m:
            ok = (int(m.group(1)), int(m.group(2))) == (grade_no, class_no)
        else:
            nums = re.findall(r'\d+', raw)
            ok = len(nums) == 1 and int(nums[0]) == class_no
        if ok:
            cands.append(c)
    return cands[0] if len(cands) == 1 else None


# الشعبة
spec_field = Student._meta.get_field('specialization')
spec_choices = list(spec_field.choices or [])


def spec_value(text):
    n = norm(text)
    hits = [v for v, l in spec_choices if n and n in norm(l)]
    return hits[0] if len(hits) == 1 else None


print('خيارات الشعبة في النظام:', spec_choices)

# محل الميلاد
field_names = {f.name for f in Student._meta.get_fields()}
HAS_DOB = 'date_of_birth' in field_names
HAS_BP = 'birth_place' in field_names
bp_choices = list(Student._meta.get_field('birth_place').choices or []) if HAS_BP else []
if HAS_BP:
    print('أكثر قيم محل الميلاد استخداماً الآن (لمعرفة الصيغة المعتمدة):',
          Counter(s.birth_place for s in all_students if s.birth_place).most_common(12))
if not HAS_DOB or not HAS_BP:
    print('⚠️ حقول غير موجودة في النموذج: date_of_birth=%s birth_place=%s' % (HAS_DOB, HAS_BP))


existing_places = defaultdict(Counter)
for _s in all_students:
    if getattr(_s, 'birth_place', None):
        existing_places[norm(_s.birth_place)][_s.birth_place] += 1


def fmt_place(code, gov):
    if code in BIRTH_PLACE_OVERRIDE:
        return BIRTH_PLACE_OVERRIDE[code]
    if not gov:
        return None
    if bp_choices:
        n = norm(gov)
        for v, l in bp_choices:
            if norm(v) == n or norm(l) == n:
                return v
        for v, l in bp_choices:
            if norm(l) and (n in norm(l) or norm(l) in n):
                return v
        return None
    ex = existing_places.get(norm(gov))
    return ex.most_common(1)[0][0] if ex else gov     # نفس إملاء القيم الموجودة (مثل الإسكندرية/الاسكندرية)


# =========================== 3) المطابقة ===========================
hr('3) المطابقة بالأسماء')
SHEET_GENDER = {'بنات': 'Female', 'بنين': 'Male'}


def find(xt, sheet_gender, candidates):
    cands = [r for r in candidates if r['tokens'] == xt]
    mtype = 'exact'
    if cands:
        # الإكسيل يقطع بعض الأسماء: لو وُجد في النظام أيضاً اسم أطول يبدأ بنفس المقاطع فالمطابقة غامضة
        cands += [r for r in candidates if len(r['tokens']) > len(xt) and r['tokens'][:len(xt)] == xt]
    if not cands and len(xt) >= 3:
        cands = [r for r in candidates if len(r['tokens']) >= 3 and
                 (r['tokens'][:len(xt)] == xt or xt[:len(r['tokens'])] == r['tokens'])]
        mtype = 'prefix'
    if len(cands) > 1:
        g = [r for r in cands if r['gender'] in (None, sheet_gender)]
        cands = g or cands
    return cands, mtype


report, matched = [], {}
for x in xrows:
    xt = norm(x['name']).split()
    sg = SHEET_GENDER.get(x['gender'])
    row = {'excel_name': x['name'], 'class': '%s/%s' % (x['grade_no'], x['class_no']), 'status': '',
           'db_id': '', 'db_name': '', 'match': '', 'suggestion': '', 'note': ''}
    if x['name'] in MANUAL_MATCH and MANUAL_MATCH[x['name']] in recs:
        cands, mtype = [recs[MANUAL_MATCH[x['name']]]], 'manual'
    else:
        cands, mtype = find(xt, sg, pool)
    if len(cands) == 1:
        r = cands[0]
        row.update(status='MATCHED', db_id=r['obj'].pk, db_name=r['full'], match=mtype)
        matched.setdefault(r['obj'].pk, []).append((x, row))
    elif len(cands) > 1:
        row.update(status='AMBIGUOUS', note='؛ '.join('%s (id=%s)' % (r['full'], r['obj'].pk) for r in cands[:4]))
    else:
        other, mtype2 = find(xt, sg, list(recs.values()))
        if len(other) == 1:
            r = other[0]
            row.update(status='OTHER_GRADE', db_id=r['obj'].pk, db_name=r['full'], match=mtype2,
                       note='موجود لكن صفه في النظام: %s — لم يُطبّق عليه شيء' % (r['obj'].grade.name if r['obj'].grade else '؟'))
        else:
            joined = ' '.join(xt)
            best, ratio = None, 0.0
            for r in pool:
                sm = difflib.SequenceMatcher(None, joined, ' '.join(r['tokens'][:len(xt)]))
                if sm.quick_ratio() >= FUZZY_CUTOFF:
                    q = sm.ratio()
                    if q > ratio:
                        best, ratio = r, q
            row['status'] = 'NOT_FOUND'
            if best and ratio >= FUZZY_CUTOFF:
                row['suggestion'] = '%s (id=%s, تشابه %.0f%%)' % (best['full'], best['obj'].pk, ratio * 100)
    report.append(row)

# طالب في النظام طابق أكثر من اسم في الإكسيل = تعارض
for pk, lst in list(matched.items()):
    if len(lst) > 1:
        for _, row in lst:
            row['status'] = 'DUP_CONFLICT'
            row['note'] = 'نفس الطالب طابق أكثر من اسم في الإكسيل — لم يُطبّق'
        del matched[pk]

cnt = Counter(r['status'] for r in report)
print('النتيجة:', dict(cnt))
print('  MATCHED     = تطابق وسيُحدَّث')
print('  NOT_FOUND   = غير موجود في النظام (يُتجاهل)')
print('  OTHER_GRADE = موجود لكن في صف آخر في النظام (لا يُحدَّث، راجعه)')
print('  AMBIGUOUS   = أكثر من طالب بنفس الاسم (لا يُحدَّث، راجعه)')

# =========================== 4) خطة التحديث ===========================
hr('4) خطة التحديث')
plan, notes = {}, defaultdict(list)
missing_cls = Counter()
for pk, lst in matched.items():
    x, row = lst[0]
    r = recs[pk]
    s = r['obj']
    ch = {}

    # الفصل
    cl = find_classroom(s.grade_id, x['grade_no'], x['class_no'])
    if cl is None:
        notes[pk].append('لا يوجد فصل %s/%s ضمن فصول صف الطالب' % (x['grade_no'], x['class_no']))
        missing_cls[(s.grade.name if s.grade else '؟', '%s/%s' % (x['grade_no'], x['class_no']))] += 1
    elif s.classroom_id != cl.pk:
        ch['classroom_id'] = (s.classroom_id, cl.pk)

    # الشعبة
    sv = spec_value(x['spec'])
    if sv is None:
        notes[pk].append('الشعبة "%s" غير مطابقة لخيارات النظام' % x['spec'])
    elif s.specialization != sv:
        ch['specialization'] = (s.specialization, sv)

    # الديانة
    rel = 'Muslim' if x['religion'].startswith('مسلم') else ('Christian' if x['religion'].startswith('مسيح') else None)
    if rel is None:
        notes[pk].append('ديانة غير مفهومة: "%s"' % x['religion'])
    elif s.religion != rel:
        ch['religion'] = (s.religion, rel)

    # من الرقم القومي
    nid = r['nid']
    sheet_g = SHEET_GENDER.get(x['gender'])
    if nid is None:
        notes[pk].append(nid_reason(getattr(s, 'national_id', None)) + ' — تخطي النوع وتاريخ ومحل الميلاد')
    else:
        if sheet_g and sheet_g != nid['gender']:
            notes[pk].append('تعارض: النوع من الرقم القومي (%s) ≠ عنوان الفصل (%s) — لم يُحدَّث النوع' % (nid['gender'], sheet_g))
        elif getattr(s, 'gender', None) != nid['gender']:
            ch['gender'] = (getattr(s, 'gender', None), nid['gender'])
        if HAS_DOB and (OVERWRITE_BIRTH or not s.date_of_birth) and s.date_of_birth != nid['dob']:
            ch['date_of_birth'] = (s.date_of_birth, nid['dob'])
        if HAS_BP and (OVERWRITE_BIRTH or not s.birth_place):
            place = fmt_place(nid['code'], nid['gov'])
            if place is None:
                notes[pk].append('محافظة كود %s لا تطابق صيغة النظام' % nid['code'])
            elif s.birth_place != place:
                ch['birth_place'] = (s.birth_place, place)
    if ch:
        plan[pk] = ch
    for n in notes[pk]:
        row['note'] = (row['note'] + '؛ ' if row['note'] else '') + n

fc = Counter(f for ch in plan.values() for f in ch)
print('طلاب سيتغير فيهم شيء:', len(plan), 'من', len(matched), 'مطابقاً')
print('عدد التغييرات لكل حقل:', dict(fc))
print('فصول غير موجودة في النظام  [(الصف، الفصل): عدد الطلاب]:', dict(missing_cls))
for _f in ('religion', 'specialization'):
    print('تفصيل %s  [(القديم، الجديد): العدد]:' % _f,
          Counter((repr(o), n) for ch in plan.values() for f, (o, n) in ch.items() if f == _f).most_common(8))
print('طلاب عليهم ملاحظات (راجع التقرير):', sum(1 for v in notes.values() if v))
print('ملاحظات حسب النوع:', dict(Counter(n.split(':')[0].split(' —')[0][:40] for v in notes.values() for n in v)))

# =========================== 5) التقارير ===========================
hr('5) كتابة التقارير')
with open(OUT_DIR + 'sync_report.csv', 'w', newline='', encoding='utf-8-sig') as f:
    w = csv.DictWriter(f, fieldnames=list(report[0].keys()) if report else ['excel_name'])
    w.writeheader()
    w.writerows(report)
with open(OUT_DIR + 'sync_changes.csv', 'w', newline='', encoding='utf-8-sig') as f:
    w = csv.writer(f)
    w.writerow(['student_id', 'name', 'field', 'old', 'new'])
    for pk, ch in plan.items():
        for fld, (old, new) in ch.items():
            w.writerow([pk, recs[pk]['full'], fld, old, new])
matched_ids = set(matched)
with open(OUT_DIR + 'sync_db_not_in_excel.csv', 'w', newline='', encoding='utf-8-sig') as f:
    w = csv.writer(f)
    w.writerow(['student_id', 'name', 'grade', 'classroom_now'])
    for r in pool:
        if r['obj'].pk not in matched_ids:
            w.writerow([r['obj'].pk, r['full'], r['obj'].grade.name, r['obj'].classroom or ''])
print('sync_report.csv  (كل اسم في الإكسيل وحالته)')
print('sync_changes.csv (كل تغيير سيحدث: القديم ← الجديد)')
print('sync_db_not_in_excel.csv (طلاب الصف في النظام ولم يرد اسمهم في الإكسيل)')
print('في:', OUT_DIR)

# =========================== 6) التطبيق ===========================
hr('6) التطبيق')
if not APPLY:
    print('🔎 وضع التجربة: لم يُكتب أي شيء في قاعدة البيانات.')
    print('   راجع الملفات، ثم عند الجاهزية: خذ نسخة احتياطية → ضع CONFIRM_BACKUP=True و APPLY=True → أعد التشغيل.')
elif not CONFIRM_BACKUP:
    print('⛔ APPLY=True لكن CONFIRM_BACKUP=False — تم الإيقاف. خذ نسخة احتياطية أولاً ثم ضعها True.')
else:
    undo = {str(pk): {f: _ser(old) for f, (old, new) in ch.items()} for pk, ch in plan.items()}
    json.dump(undo, open(UNDO_PATH, 'w', encoding='utf-8'), ensure_ascii=False)   # ملف التراجع يُكتب قبل أي تعديل
    with transaction.atomic():
        for pk, ch in plan.items():
            Student.objects.filter(pk=pk).update(**{f: new for f, (old, new) in ch.items()})
    print('✅ تم تحديث %d طالباً. ملف التراجع: %s' % (len(plan), UNDO_PATH))
    print('   للتراجع: undo_sync()')
