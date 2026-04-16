import os
import django

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'config.settings')
django.setup()

from students.models import Student

print("--- الحقول المتاحة للتخزين في موديل الطالب هي: ---")
for field in Student._meta.fields:
    print(f"الحقل: {field.name}")