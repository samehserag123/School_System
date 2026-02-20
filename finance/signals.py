from django.db.models.signals import post_save
from django.dispatch import receiver
from students.models import Student
from .models import StudentAccount


@receiver(post_save, sender=Student)
def create_student_account(sender, instance, created, **kwargs):
    if created:
        StudentAccount.objects.create(
            student=instance
        )