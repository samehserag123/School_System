"""
تصفير المديونية القديمة (previous_debt) للطلاب المسكّنين فقط.

القاعدة:
  - الطالب "مسكّن" = مجموع أقساطه في السنة المختارة (خانة المطلوب) أكبر من صفر  => تُصفَّر مديونيته القديمة.
  - الطالب غير المسكّن (المطلوب = 0)                                               => لا يُمس.

الاستخدام (من مجلد المشروع):
  python manage.py zero_old_debt                      # تجربة فقط: يعرض ما سيحدث دون أي تعديل
  python manage.py zero_old_debt --apply              # تنفيذ فعلي (ينشئ نسخة احتياطية CSV أولاً ويطلب تأكيداً)
  python manage.py zero_old_debt --restore FILE.csv   # التراجع: يعيد القيم من ملف النسخة الاحتياطية
  python manage.py zero_old_debt --year-id 3          # سنة محددة بدل السنة النشطة
"""
import csv
import os
import time
from decimal import Decimal

from django.core.cache import cache
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from django.db.models import DecimalField, OuterRef, Subquery, Sum, Value
from django.db.models.functions import Coalesce

from finance.models import AcademicYear, StudentInstallment
from students.models import Student

CHUNK = 500


def _chunks(seq, n=CHUNK):
    for i in range(0, len(seq), n):
        yield seq[i:i + n]


class Command(BaseCommand):
    help = "تصفير المديونية القديمة للطلاب المسكّنين فقط (مع تجربة ونسخة احتياطية وتراجع)"

    def add_arguments(self, parser):
        parser.add_argument('--apply', action='store_true', help='تنفيذ فعلي (الافتراضي: تجربة فقط)')
        parser.add_argument('--year-id', type=int, help='رقم السنة الدراسية (الافتراضي: السنة النشطة)')
        parser.add_argument('--restore', type=str, help='مسار ملف CSV للنسخة الاحتياطية لاسترجاع القيم')

    # ------------------------------------------------------------------
    def handle(self, *args, **opts):
        if opts['restore']:
            return self._restore(opts['restore'])

        year = (AcademicYear.objects.filter(id=opts['year_id']).first() if opts['year_id']
                else AcademicYear.objects.filter(is_active=True).first())
        if not year:
            raise CommandError("لم يتم العثور على السنة الدراسية.")

        required_sq = (StudentInstallment.objects
                       .filter(student=OuterRef('pk'), academic_year=year)
                       .order_by().values('student')
                       .annotate(t=Sum('amount_due')).values('t'))
        dec0 = Value(0, output_field=DecimalField())
        with_debt = (Student.objects.filter(academic_year=year, previous_debt__gt=0)
                     .annotate(required=Coalesce(Subquery(required_sq, output_field=DecimalField()), dec0)))

        targets = list(with_debt.filter(required__gt=0)
                       .values_list('pk', 'student_code', 'first_name', 'last_name', 'previous_debt', 'required')
                       .order_by('first_name', 'id'))
        skipped = with_debt.filter(required__lte=0).count()
        total_amount = sum((t[4] for t in targets), Decimal('0.00'))

        self.stdout.write(f"السنة الدراسية: {year}")
        self.stdout.write(f"سيتم تصفير مديونية  : {len(targets)} طالب مسكّن  (إجمالي {total_amount} ج.م)")
        self.stdout.write(f"لن يُمس (غير مسكّن)  : {skipped} طالب عليهم مديونية قديمة والمطلوب = 0")
        for pk, code, fn, ln, debt, req in targets[:15]:
            self.stdout.write(f"   #{pk} {code or ''} {fn} {ln}  | قديمة: {debt}  | المطلوب: {req}")
        if len(targets) > 15:
            self.stdout.write(f"   ... و{len(targets) - 15} آخرين")

        if not opts['apply']:
            self.stdout.write(self.style.WARNING("\nهذه تجربة فقط ولم يتغير شيء. للتنفيذ أضف --apply"))
            return
        if not targets:
            self.stdout.write("لا يوجد ما يُصفَّر.")
            return

        if input("\nاكتب ZERO (بحروف كبيرة) لتأكيد التصفير: ").strip() != 'ZERO':
            self.stdout.write("تم الإلغاء، لم يتغير شيء.")
            return

        # 1) نسخة احتياطية قبل أي تعديل
        backup = os.path.join(os.path.expanduser('~'), f"zero_old_debt_backup_{time.strftime('%Y%m%d_%H%M%S')}.csv")
        with open(backup, 'w', newline='', encoding='utf-8-sig') as f:
            w = csv.writer(f)
            w.writerow(['student_id', 'student_code', 'name', 'previous_debt', 'required'])
            for pk, code, fn, ln, debt, req in targets:
                w.writerow([pk, code or '', f"{fn} {ln}".strip(), debt, req])

        # 2) التصفير داخل معاملة واحدة (إما ينجح الكل أو لا شيء)
        ids = [t[0] for t in targets]
        with transaction.atomic():
            updated = 0
            for part in _chunks(ids):
                updated += Student.objects.filter(pk__in=part, previous_debt__gt=0).update(previous_debt=Decimal('0.00'))

        cache.set('student_stats_ver', int(time.time() * 1000), None)   # تجديد عدادات صفحة الطلاب
        self.stdout.write(self.style.SUCCESS(f"\nتم تصفير {updated} طالب."))
        self.stdout.write(f"النسخة الاحتياطية: {backup}")
        self.stdout.write(f"للتراجع: python manage.py zero_old_debt --restore {backup}")

    # ------------------------------------------------------------------
    def _restore(self, path):
        if not os.path.exists(path):
            raise CommandError(f"الملف غير موجود: {path}")
        restored = skipped = 0
        with open(path, newline='', encoding='utf-8-sig') as f, transaction.atomic():
            for row in csv.DictReader(f):
                # لا نكتب فوق قيمة عُدّلت يدوياً بعد التصفير (نسترجع فقط إن كانت القيمة الحالية صفراً)
                n = Student.objects.filter(pk=int(row['student_id']), previous_debt=0)\
                                   .update(previous_debt=Decimal(row['previous_debt']))
                restored += n
                skipped += (1 - n)
        cache.set('student_stats_ver', int(time.time() * 1000), None)
        self.stdout.write(self.style.SUCCESS(f"تم استرجاع {restored} طالب (تخطّي {skipped} لأن قيمتهم تغيرت بعد التصفير)."))