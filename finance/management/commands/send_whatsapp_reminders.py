import datetime
import re
from decimal import Decimal
import requests
from django.core.management.base import BaseCommand
from django.utils import timezone
from django.db.models import F
from students.models import Student
from finance.models import StudentInstallment


class Command(BaseCommand):
    help = 'إرسال رسائل تذكيرية بالواتساب للأقساط المستحقة قبل موعدها بأسبوع'

    def handle(self, *args, **options):
        today = timezone.localtime().date()
        target_date = today + datetime.timedelta(days=7)  # الاستحقاق بعد 7 أيام بالضبط

        self.stdout.write(self.style.NOTICE(f"🔍 جاري الفحص للأقساط المستحقة يوم: {target_date}..."))

        installments = StudentInstallment.objects.filter(
            due_date=target_date,
            paid_amount__lt=F('amount_due')
        ).select_related('student')

        students_map = {}

        for inst in installments:
            st = inst.student
            if not st or not st.is_active:
                continue

            phone = getattr(st, 'whatsapp_number', None) or getattr(st, 'parent_phone', None) or getattr(st, 'phone', None)
            if not phone or phone == '---':
                continue

            remaining = inst.amount_due - inst.paid_amount
            if remaining <= 0:
                continue

            if st.id not in students_map:
                students_map[st.id] = {
                    'student_name': st.get_full_name(),
                    'phone': phone,
                    'total_due': Decimal('0.00'),
                    'due_date': target_date.strftime('%Y-%m-%d')
                }
            students_map[st.id]['total_due'] += remaining

        sent_count = 0

        for st_id, data in students_map.items():
            student_name = data['student_name']
            raw_phone = str(data['phone']).strip()

            # فصل الأرقام المركبة (مثل 01142982863/01121462662) وأخذ الرقم الأول الصريح
            phone_parts = re.split(r'[/,;\s]+', raw_phone)
            primary_phone = phone_parts[0] if phone_parts else raw_phone
            clean_phone = ''.join(filter(str.isdigit, primary_phone))

            if clean_phone.startswith('01'):
                clean_phone = '2' + clean_phone

            msg_text = (
                f"السلام عليكم ولي أمر الطالب/ة ({student_name})،\n"
                f"نود تذكير سيادتكم بميعاد سداد القسط القادم وقيمته ({data['total_due']:.2f} ج.م)، "
                f"والمستحق سداده قبل يوم {data['due_date']}.\n"
                f"شاكرين حسن تعاونكم معنا."
            )

            try:
                # =========================================================
                # 🟢 رابط إرسال API الواتساب المسجل بالنظام
                # =========================================================
                # payload = {'to': clean_phone, 'body': msg_text}
                # requests.post(api_url, data=payload, timeout=10)

                self.stdout.write(self.style.SUCCESS(f"✅ تم تجهيز التذكير لـ: {student_name} ({clean_phone})"))
                sent_count += 1
            except Exception as e:
                self.stdout.write(self.style.ERROR(f"❌ فشل إرسال الرسالة لـ {student_name}: {e}"))

        self.stdout.write(self.style.SUCCESS(f"🎉 تم الانتهاء! إجمالي التذكيرات المستحقة: {sent_count}"))
