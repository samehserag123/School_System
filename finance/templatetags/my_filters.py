from django import template

register = template.Library()

@register.filter(name='split')
def split(value, arg):
    """تقسيم النص بناءً على العلامة المرسلة"""
    return value.split(arg)