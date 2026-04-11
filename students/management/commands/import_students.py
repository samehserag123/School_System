import csv
from django.core.management.base import BaseCommand
from students.models import Student, Grade
from finance.models import AcademicYear

class Command(BaseCommand):
    help = 'استيراد بيانات الطلاب من ملف نصي (Notepad) مفصول بمسافات Tab'

    def handle(self, *args, **kwargs):
        # 1. تجهيز السنة الدراسية والصف
        year = AcademicYear.objects.filter(is_active=True).first()
        if not year:
            self.stdout.write(self.style.ERROR('❌ لا توجد سنة دراسية نشطة!'))
            return
            
        grade, _ = Grade.objects.get_or_create(name="الصف الأول")

        success_count = 0
        error_count = 0

        self.stdout.write(self.style.WARNING('جاري استيراد البيانات من الملف النصي... الرجاء الانتظار.'))

        try:
            # قراءة الملف الذي صنعته أنت (باستخدام Tab كفاصل)
            with open('students_data.csv', encoding='utf-8') as f:
                reader = csv.DictReader(f, delimiter='\t')
                
                for row_num, row in enumerate(reader, start=1):
                    try:
                        # 1. الاسم
                        full_name = row.get('full_name', '').strip()
                        if not full_name:
                            continue
                            
                        print(f"جاري معالجة: {full_name}") # للتأكد من أن الكود يقرأ
                            
                        name_parts = full_name.split(' ', 1)
                        first_name = name_parts[0]
                        last_name = name_parts[1] if len(name_parts) > 1 else "---"

                        # 2. الشعبة
                        spec_raw = row.get('specialization', '').strip()
                        spec = 'General'
                        if 'طاه' in spec_raw: spec = 'Kitchen'
                        elif 'مضيف' in spec_raw: spec = 'Restaurant'
                        elif 'غرف' in spec_raw: spec = 'Internal'

                        # 3. الديانة
                        rel_raw = row.get('religion', '').strip()
                        religion = 'Christian' if 'مسيح' in rel_raw else 'Muslim'

                        # 4. الرقم القومي
                        nid = row.get('national_id', '').strip()
                        if len(nid) != 14 or not nid.isdigit():
                            nid = None
                        else:
                            # منع التكرار
                            if Student.objects.filter(national_id=nid).exists():
                                continue

                        # 5. تاريخ الميلاد (MM/DD/YYYY)
                        dob_raw = row.get('date_of_birth', '').strip()
                        dob = None
                        if dob_raw and '/' in dob_raw:
                            parts = dob_raw.split('/')
                            if len(parts) == 3:
                                m, d, y = parts[0].zfill(2), parts[1].zfill(2), parts[2]
                                if len(y) == 2:
                                    y = "20" + y if int(y) <= 25 else "19" + y
                                dob = f"{y}-{m}-{d}"

                        # 6. الحفظ في الداتا بيز مباشرة بناءً على العناوين التي وضعتها أنت
                        Student.objects.create(
                            first_name=first_name,
                            last_name=last_name,
                            national_id=nid,
                            registration_number=row.get('registration_number', '').strip(),
                            date_of_birth=dob,
                            gender='Female',
                            religion=religion,
                            enrollment_status='New', # نفترض أنهم مستجدين
                            specialization=spec,
                            mother_name=row.get('mother_name', '').strip(),
                            phone=row.get('phone', '').strip(),
                            academic_year=year,
                            grade=grade,
                            is_active=True
                        )
                        success_count += 1

                    except Exception as e:
                        self.stdout.write(self.style.ERROR(f'❌ خطأ في السطر {row_num}: {str(e)}'))
                        error_count += 1

        except FileNotFoundError:
            self.stdout.write(self.style.ERROR('❌ لم يتم العثور على ملف students_data.csv'))
            return

        self.stdout.write(self.style.SUCCESS(f'\n✅ انتهت العملية بنجاح! تم إدخال [{success_count}] طالب في قاعدة البيانات.'))
        if error_count > 0:
            self.stdout.write(self.style.WARNING(f'⚠️ لم يتم إدخال {error_count} صف لوجود أخطاء.'))