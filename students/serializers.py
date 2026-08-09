from rest_framework import serializers
from .models import Student

class StudentSerializer(serializers.ModelSerializer):
    class Meta:
        model = Student
        fields = '__all__'



from django.core.validators import RegexValidator


class OnlineAdmissionSerializer(serializers.ModelSerializer):
    # إضافة شروط تحقق صارمة للبيانات القادمة أونلاين لضمان نظافتها
    national_id = serializers.CharField(
        max_length=14,
        min_length=14,
        validators=[RegexValidator(regex=r'^\d{14}$', message="الرقم القومي يجب أن يتكون من 14 رقماً.")]
    )
    whatsapp_number = serializers.CharField(
        max_length=11,
        min_length=11,
        validators=[RegexValidator(regex=r'^01[0-9]{9}$', message="رقم واتساب مصري غير صحيح.")]
    )

    # 🟢 إضافة حقول الصور والمستندات كـ optional حتى لا تتوقف عملية الحفظ إذا لم يرفق الطالب ملفاً منهم
    student_photo = serializers.ImageField(required=False, allow_null=True)
    parent_id_photo = serializers.ImageField(required=False, allow_null=True)
    birth_certificate = serializers.FileField(required=False, allow_null=True)
    qualification_photo = serializers.FileField(required=False, allow_null=True)

    class Meta:
        model = Student
        # استقبال البيانات الأساسية بالإضافة إلى الملفات المرفوعة
        fields = [
            'first_name', 'last_name', 'national_id', 'gender',
            'religion', 'phone', 'whatsapp_number', 'address', 'grade',
            # 🟢 إضافة حقول الميديا المستهدفة للحفظ
            'student_photo', 'parent_id_photo', 'birth_certificate', 'qualification_photo'
        ]

    def validate_national_id(self, value):
        # منع التسجيل المكرر أونلاين إذا كان الرقم القومي مسجل مسبقاً بالسيستم المدرسي
        if Student.objects.filter(national_id=value).exists():
            raise serializers.ValidationError("هذا الرقم القومي مسجل بالفعل في النظام الداخلي.")
        return value