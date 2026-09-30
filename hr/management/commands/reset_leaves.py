from django.core.management.base import BaseCommand
from hr.models import Employee

class Command(BaseCommand):
    help = 'تصفير رصيد الإجازات العارضة والسنوية لجميع الموظفين'

    def handle(self, *args, **kwargs):
        # تصفير العارضة لـ 7 أيام، والسنوية لـ 21 يوم لكل الموظفين النشطين
        updated_count = Employee.objects.filter(is_active=True).update(
            casual_balance=7.0,
            annual_balance=21.0
        )
        
        self.stdout.write(
            self.style.SUCCESS(f'تم تصفير الأرصدة بنجاح لعدد {updated_count} موظف.')
        )