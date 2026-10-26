"""
كشف وحذف الطلاب المكررين (افتراضياً: الطلاب العمال فقط).

القواعد:
  - المكرر = نفس الاسم (بعد توحيد الحروف) في نفس السنة الدراسية. وبـ --by regno: نفس رقم القيد.
  - يُحذف السجل الذي ليس له أي معاملات (أقساط/حساب/مدفوعات/أي علاقة أخرى) وليس عليه مديونية قديمة.
  - أي سجل له معاملات أو مسكّن لا يُحذف أبداً.
  - لو كل سجلات المجموعة فارغة: يُبقى الأقدم (أصغر id) ويُحذف الباقي.
  - لو أكثر من سجل في المجموعة له معاملات: لا يُحذف شيء منها ويُعلَّم "مراجعة يدوية".

الاستخدام (من مجلد المشروع):
  python manage.py dedupe_students                      # تقرير فقط (لا يحذف شيئاً) + ملف CSV يُفتح في Excel
  python manage.py dedupe_students --by regno           # التكرار برقم القيد بدل الاسم
  python manage.py dedupe_students --all-types          # كل أنواع الدراسة وليس العمال فقط
  python manage.py dedupe_students --year-id 3          # سنة محددة (الافتراضي: السنة النشطة)
  python manage.py dedupe_students --apply              # الحذف الفعلي (نسخة احتياطية JSON + تأكيد بكتابة DELETE)

للتراجع بعد الحذف:  python manage.py loaddata <ملف النسخة الاحتياطية .json>
"""
import csv
import os
import time
from collections import defaultdict
from decimal import Decimal

from django.core import serializers
from django.core.cache import cache
from django.core.exceptions import ObjectDoesNotExist
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from django.db.models import Count, Sum

from finance.models import AcademicYear, Payment, StudentAccount, StudentInstallment
from students.models import Student

CHUNK = 500


def decide_group(members):
    """
    members: قائمة dict لكل منها id و busy (له معاملات أو مديونية).
    ترجع (القرارات {id: 'KEEP'|'DELETE'}, ملاحظة المجموعة).
    """
    members = sorted(members, key=lambda m: m['id'])
    busy = [m for m in members if m['busy']]
    if not busy:                                   # الكل فارغ: نُبقي الأقدم فقط
        d = {m['id']: 'DELETE' for m in members}
        d[members[0]['id']] = 'KEEP'
        return d, 'كل السجلات بلا معاملات: يُبقى الأقدم'
    d = {m['id']: ('KEEP' if m['busy'] else 'DELETE') for m in members}
    note = 'مراجعة يدوية: أكثر من سجل عليه معاملات (لن يُحذف أي منها)' if len(busy) > 1 else ''
    return d, note


def _chunks(seq, n=CHUNK):
    seq = list(seq)
    for i in range(0, len(seq), n):
        yield seq[i:i + n]


def relation_counts(student):
    """عدد السجلات المرتبطة بالطالب في كل العلاقات العكسية (يلتقط أي جدول يرتبط به حتى لو لم أعرفه)."""
    out = {}
    for rel in Student._meta.related_objects:
        name = rel.get_accessor_name()
        try:
            obj = getattr(student, name)
        except ObjectDoesNotExist:
            continue
        n = 1 if rel.one_to_one else obj.count()
        if n:
            out[name] = n
    return out


class Command(BaseCommand):
    help = "كشف الطلاب المكررين (العمال افتراضياً) وحذف الفارغ منهم بعد المراجعة"

    def add_arguments(self, parser):
        parser.add_argument('--apply', action='store_true', help='حذف فعلي (الافتراضي: تقرير فقط)')
        parser.add_argument('--by', choices=['name', 'regno'], default='name', help='معيار التكرار')
        parser.add_argument('--year-id', type=int, help='السنة الدراسية (الافتراضي: النشطة)')
        parser.add_argument('--all-types', action='store_true', help='كل أنواع الدراسة وليس العمال فقط')

    def handle(self, *args, **o):
        year = (AcademicYear.objects.filter(id=o['year_id']).first() if o['year_id']
                else AcademicYear.objects.filter(is_active=True).first())
        if not year:
            raise CommandError('لم يتم العثور على السنة الدراسية.')

        qs = Student.objects.filter(academic_year=year).select_related('grade', 'classroom')
        if not o['all_types']:
            qs = qs.filter(study_type='Workers')

        # ---------- 1) تجميع المكررين ----------
        groups = defaultdict(list)
        for s in qs:
            if o['by'] == 'regno':
                key = (s.registration_number or '').strip()
            else:
                key = (s.search_name or f"{s.first_name} {s.last_name}").strip()
            if key:
                groups[key].append(s)
        dup_groups = {k: v for k, v in groups.items() if len(v) > 1}
        if not dup_groups:
            self.stdout.write(self.style.SUCCESS('لا توجد سجلات مكررة بهذا المعيار.'))
            return

        ids = [s.pk for v in dup_groups.values() for s in v]

        # ---------- 2) حسابات كل طالب (استعلامات مجمّعة) ----------
        inst, acct, pays = {}, {}, {}
        for part in _chunks(ids):
            for sid, n, t in (StudentInstallment.objects.filter(student_id__in=part).values('student')
                              .annotate(n=Count('id'), t=Sum('amount_due')).values_list('student', 'n', 't')):
                inst[sid] = (n, t or Decimal('0'))
            for sid, t, d in (StudentAccount.objects.filter(student_id__in=part).values('student')
                              .annotate(t=Sum('total_fees'), d=Sum('discount')).values_list('student', 't', 'd')):
                acct[sid] = (t or Decimal('0'), d or Decimal('0'))
            for sid, n in (Payment.objects.filter(student_id__in=part).values('student')
                           .annotate(n=Count('id')).values_list('student', 'n')):
                pays.setdefault(sid, [0, Decimal('0')])[0] = n
            for sid, t in (Payment.objects.filter(student_id__in=part, is_cancelled=False).values('student')
                           .annotate(t=Sum('amount_paid')).values_list('student', 't')):
                pays.setdefault(sid, [0, Decimal('0')])[1] = t or Decimal('0')

        # ---------- 3) القرار لكل مجموعة ----------
        rows, to_delete = [], []
        review_groups = 0
        for key, members in sorted(dup_groups.items()):
            infos = []
            for s in members:
                rel = relation_counts(s)
                debt = s.previous_debt or Decimal('0')
                busy = bool(rel) or debt > 0
                infos.append({'id': s.pk, 'busy': busy, 's': s, 'rel': rel, 'debt': debt})
            decisions, note = decide_group([{'id': i['id'], 'busy': i['busy']} for i in infos])
            review_groups += bool(note.startswith('مراجعة'))
            for i in sorted(infos, key=lambda x: x['id']):
                s = i['s']
                n_inst, fees = inst.get(s.pk, (0, Decimal('0')))
                acc_fees, disc = acct.get(s.pk, (Decimal('0'), Decimal('0')))
                n_pay, paid = pays.get(s.pk, [0, Decimal('0')])
                dec = decisions[s.pk]
                if dec == 'DELETE':
                    to_delete.append(s)
                rows.append({
                    'المجموعة': key, 'القرار': dec, 'ملاحظة': note,
                    'id': s.pk, 'الكود': s.student_code or '', 'رقم القيد': s.registration_number or '',
                    'الاسم': s.get_full_name(), 'الرقم القومي': s.national_id or '',
                    'الصف': s.grade.name if s.grade_id and hasattr(s.grade, 'name') else str(s.grade or ''),
                    'مسكن': 'نعم' if n_inst else 'لا', 'عدد الأقساط': n_inst, 'المطلوب': fees,
                    'إجمالي الحساب': acc_fees, 'الخصم': disc, 'عدد الإيصالات': n_pay, 'المحصل': paid,
                    'مديونية قديمة': i['debt'],
                    'علاقات أخرى': '، '.join(f'{k}:{v}' for k, v in i['rel'].items()),
                    'الحالة': s.get_enrollment_status_display() if hasattr(s, 'get_enrollment_status_display') else '',
                })

        # ---------- 4) التقرير ----------
        stamp = time.strftime('%Y%m%d_%H%M%S')
        report = os.path.join(os.path.expanduser('~'), f'duplicate_students_report_{stamp}.csv')
        with open(report, 'w', newline='', encoding='utf-8-sig') as f:
            w = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
            w.writeheader()
            w.writerows(rows)

        self.stdout.write(f"السنة: {year} | المعيار: {'رقم القيد' if o['by'] == 'regno' else 'الاسم'} | "
                          f"{'كل الأنواع' if o['all_types'] else 'العمال فقط'}")
        self.stdout.write(f"مجموعات مكررة: {len(dup_groups)} | سجلات: {len(ids)} | "
                          f"سيُحذف: {len(to_delete)} | مجموعات تحتاج مراجعة يدوية: {review_groups}\n")
        last = None
        for r in rows:
            if r['المجموعة'] != last:
                last = r['المجموعة']
                self.stdout.write(f"\n== {last}  {('[' + r['ملاحظة'] + ']') if r['ملاحظة'] else ''}")
            mark = '❌ حذف ' if r['القرار'] == 'DELETE' else '✅ إبقاء'
            self.stdout.write(
                f"  {mark} #{r['id']} كود:{r['الكود']} قيد:{r['رقم القيد']} قومي:{r['الرقم القومي']} | {r['الاسم']} | "
                f"مسكن:{r['مسكن']} مطلوب:{r['المطلوب']} محصل:{r['المحصل']} إيصالات:{r['عدد الإيصالات']} "
                f"قديمة:{r['مديونية قديمة']} {('علاقات:' + r['علاقات أخرى']) if r['علاقات أخرى'] else ''}")
        self.stdout.write(f"\nملف التقرير (افتحه في Excel): {report}")

        if not o['apply']:
            self.stdout.write(self.style.WARNING('\nتقرير فقط ولم يُحذف شيء. راجعه جيداً، ثم للتنفيذ أضف --apply'))
            return
        if not to_delete:
            self.stdout.write('لا يوجد ما يُحذف.')
            return

        if input(f"\nسيتم حذف {len(to_delete)} سجل نهائياً. اكتب DELETE (بحروف كبيرة) للتأكيد: ").strip() != 'DELETE':
            self.stdout.write('تم الإلغاء، لم يُحذف شيء.')
            return

        # ---------- 5) نسخة احتياطية ثم الحذف داخل معاملة واحدة ----------
        backup = os.path.join(os.path.expanduser('~'), f'duplicate_students_backup_{stamp}.json')
        with open(backup, 'w', encoding='utf-8') as f:
            serializers.serialize('json', to_delete, stream=f, ensure_ascii=False)

        with transaction.atomic():
            for s in to_delete:
                # حماية أخيرة: نتأكد لحظة الحذف أنه لا زال بلا أي معاملة
                if relation_counts(s) or (s.previous_debt or 0) > 0:
                    raise CommandError(f'توقف الحذف: الطالب #{s.pk} أصبح له معاملات. لم يُحذف شيء.')
                s.delete()

        cache.set('student_stats_ver', int(time.time() * 1000), None)
        self.stdout.write(self.style.SUCCESS(f'\nتم حذف {len(to_delete)} سجل.'))
        self.stdout.write(f'النسخة الاحتياطية: {backup}')
        self.stdout.write(f'للتراجع: python manage.py loaddata {backup}')