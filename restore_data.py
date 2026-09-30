import json
import os
from students.models import Student

file_path = 'backup_data.json'

if not os.path.exists(file_path):
    print(f"❌ خطأ: لم يتم العثور على {file_path} في المجلد الحالي!")
else:
    print(f"🔄 جاري قراءة {file_path}...")
    with open(file_path, 'r', encoding='utf-8') as f:
        data = json.load(f)

    student_records = [item for item in data if item.get('model') == 'students.student']
    print(f"📊 تم العثور على {len(student_records)} طالب في النسخة الاحتياطية.")

    updated_count = 0
    for item in student_records:
        pk = item.get('pk')
        fields = item.get('fields', {})
        national_id = fields.get('national_id')
        old_status = fields.get('enrollment_status')
        old_grade_id = fields.get('grade')
        old_notes = fields.get('enrollment_notes')

        student = None
        if pk:
            student = Student.objects.filter(pk=pk).first()
        if not student and national_id:
            student = Student.objects.filter(national_id=national_id).first()

        if student:
            student.enrollment_status = old_status
            if old_grade_id:
                student.grade_id = old_grade_id
            student.enrollment_notes = old_notes
            student.save(update_fields=['enrollment_status', 'grade', 'enrollment_notes'])
            updated_count += 1

    print("=" * 45)
    print(f"✅ تم بنجاح استرجاع حالة {updated_count} طالب بدقة تامة!")
    print("🔒 لم يتم المساس بأي عملية مالية أو إيصال سداد.")
    print("=" * 45)
