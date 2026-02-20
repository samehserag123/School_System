from django.db import models
from audit.models import AuditLog
#from django.contrib.auth import get_user_model
#from finance.models import InstallmentPlan
#import uuid
from django.utils import timezone
#User = get_user_model()

#def save(self, *args, **kwargs):
    #super().save(*args, **kwargs)
    #AuditLog.objects.create(
        #user=None,
        #action="Created or Updated",
        #model_name="Student",
        #object_id=self.id
    #)

class Grade(models.Model):
    name = models.CharField("اسم الصف", max_length=100)

    class Meta:
        verbose_name = "صف دراسي"
        verbose_name_plural = "الصفوف الدراسية"

    def __str__(self):
        return self.name


class Classroom(models.Model):
    name = models.CharField("اسم الفصل", max_length=100)
    grade = models.ForeignKey("students.Grade", on_delete=models.CASCADE)

    class Meta:
        verbose_name = "فصل"
        verbose_name_plural = "الفصول"

    def __str__(self):
        return f"{self.grade.name} - {self.name}"


class Student(models.Model):

    # ======================
    # Choices
    # ======================

    RELIGION_CHOICES = [
        ("Muslim", "مسلم"),
        ("Christian", "مسيحي"),
    ]

    STATUS_CHOICES = [
        ("New", "مستجد"),
        ("Transferred", "منقول"),
        ("Home", "منازل"),
    ]

    SPECIALIZATION_CHOICES = [
        ("General", "شعبة عامة"),
        ("Restaurant", "مطعم"),
        ("Kitchen", "مطبخ"),
        ("Guidance", "ارشاد"),
        ("Internal", "اشراف داخلي"),
        ("Computer", "حاسب الي"),
    ]

    GENDER_CHOICES = [
        ('Male', 'ذكر'),
        ('Female', 'أنثى'),
    ]

    # ======================
    # البيانات الأساسية
    # ======================

    student_code = models.CharField(
        "كود الطالب",
        max_length=20,
        unique=True
    )

    registration_number = models.CharField(
        "رقم القيد",
        max_length=50,
        unique=True,
        blank=True,
        null=True
    )

    first_name = models.CharField("الاسم الأول", max_length=100)
    last_name = models.CharField("اسم العائلة", max_length=100)

    national_id = models.CharField("الرقم القومي", max_length=20, unique=True)

    date_of_birth = models.DateField("تاريخ الميلاد")
    birth_place = models.CharField("محل الميلاد", max_length=150, blank=True, null=True)

    gender = models.CharField("النوع", max_length=10, choices=GENDER_CHOICES)
    religion = models.CharField("الديانة", max_length=20, choices=RELIGION_CHOICES)

    nationality = models.CharField("الجنسية", max_length=100, default="مصري")
    address = models.TextField("العنوان", blank=True, null=True)

    mother_name = models.CharField("اسم الأم", max_length=150)
    phone = models.CharField("رقم التليفون", max_length=20)

    enrollment_status = models.CharField(
        "حالة القيد",
        max_length=20,
        choices=STATUS_CHOICES,
        default="New"
    )

    integration_status = models.BooleanField("موقف الدمج", default=False)

    specialization = models.CharField(
        "التخصص",
        max_length=30,
        choices=SPECIALIZATION_CHOICES,
        blank=True,
        null=True
    )

    # ======================
    # العلاقات
    # ======================

    grade = models.ForeignKey(
        "students.Grade",
        on_delete=models.SET_NULL,
        null=True
    )

    classroom = models.ForeignKey(
        "students.Classroom",
        on_delete=models.SET_NULL,
        null=True
    )

    academic_year = models.ForeignKey(
        "finance.AcademicYear",
        on_delete=models.CASCADE
    )

    #installment_plan = models.ForeignKey(
        #"finance.InstallmentPlan",
        #on_delete=models.SET_NULL,
        #null=True,
        #blank=True,
        #related_name="students"
    #)

    # ======================
    # نظام عام
    # ======================

    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)

    # ======================
    # Logging
    # ======================

    def save(self, *args, **kwargs):
        is_new = self.pk is None
        super().save(*args, **kwargs)

        AuditLog.objects.create(
            user=None,
            action="Created" if is_new else "Updated",
            model_name="Student",
            object_id=self.id
        )

    # ======================

    class Meta:
        ordering = ["-created_at"]
        verbose_name = "طالب"
        verbose_name_plural = "الطلاب"

    def __str__(self):
        return f"{self.first_name} {self.last_name}"


