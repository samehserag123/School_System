from django import forms
from .models import Student


class StudentForm(forms.ModelForm):

    class Meta:
        model = Student
        fields = [
            'first_name',
            'last_name',
            'national_id',
            'date_of_birth',
            'gender',
            'grade',
            'classroom',
            'academic_year',
        ]

        widgets = {
            'date_of_birth': forms.DateInput(
                attrs={'type': 'date'}
            ),
        }

    # 👇 هنا المكان الصح
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

        for field_name, field in self.fields.items():

            # لو Select
            if isinstance(field.widget, forms.Select):
                field.widget.attrs.update({
                    'class': 'form-select'
                })
            else:
                field.widget.attrs.update({
                    'class': 'form-control'
                })
