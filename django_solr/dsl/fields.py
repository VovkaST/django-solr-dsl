from datetime import date, datetime
from typing import Union

from django.db import models
from django.template import TemplateDoesNotExist
from haystack.fields import DateField as _HaystackDateField
from haystack.fields import *  # noqa F403


class NestedField(SearchField):  # noqa F405
    field_type = "_nest_path_"

    def __init__(self, *args, **kwargs):
        self.properties = kwargs.pop("properties", {})
        super().__init__(*args, indexed=True, stored=True, null=True, **kwargs)

    def get_instances(self, obj, field_name: str) -> Union[models.QuerySet, models.Model, None]:
        """
        Получить связанные по полю объекты в зависимости от типа поля модели.
        Если связанный объект - объект модели (простая связь один-к-одному),
        то возвращается этот объект, если это менеджер (связь один-ко-многим,
        многие-ко-многим) то возвращается QuerySet по связанной модели.

        :param obj: Текущий индексируемый объект.
        :param field_name: Имя текущего поля связи.
        """
        set_field_name = f"{field_name}_set"
        if hasattr(obj, set_field_name):
            related = getattr(obj, set_field_name)
        elif not hasattr(obj, field_name):
            return None
        else:
            related = getattr(obj, field_name)
        if isinstance(related, models.manager.Manager):
            return related.all()
        if isinstance(related, models.Model):
            return related

    def _instance_to_dict(self, instance: models.Model, properties: dict) -> dict:
        doc = {}
        for property_name, field_class in properties.items():
            if not hasattr(instance, property_name):
                continue
            if not field_class.model_attr:
                field_class.model_attr = property_name
            doc[property_name] = field_class.prepare(instance)
        return doc

    def prepare(self, obj):
        """
        Представить объект в структуре данных для помещения в индекс.
        В качестве имени используется атрибут `model_attr`, указанный
        при инициализации поля, либо имя атрибута основной модели, если
        это вложенность первого уровня, или имя атрибута, если это вложенность
        более глубокого уровня.

        :param obj: Текущий индексируемый объект.
        """
        field_name = self.model_attr or self.instance_name
        related = self.get_instances(obj, field_name)
        if related:
            if isinstance(related, models.QuerySet):
                return [self._instance_to_dict(instance, self.properties) for instance in related]
            else:
                return self._instance_to_dict(related, self.properties)
        return None


class TextGeneralField(CharField):  # noqa F405
    field_type = "text_general"

    def prepare_template(self, obj):
        """
        Т.к. SOLR по умолчанию использует шаблоны для генерации текстового поля, основного
        для поиска при традиционном его использовании, требуется его указание в формате
        шаблонов Django. В данной реализации это требование исключено и в случае, когда шаблон
        отсутствует, поле text принимает пустое значение, а ошибка отсутствующего
        шаблона игнорируется.

        :param obj: Текущий индексируемый объект.
        """
        try:
            return super().prepare_template(obj)
        except TemplateDoesNotExist:
            return ""


class DateField(_HaystackDateField):
    FORMAT = "%Y-%m-%d"
    base_type = date

    def __init__(self, *args, **kwargs):
        self.format = kwargs.pop("format", None)
        super().__init__(*args, **kwargs)

    def prepare(self, obj):
        value = super().prepare(obj)
        if isinstance(value, self.base_type):
            return value.strftime(self.format or self.FORMAT)
        return value

    def convert(self, value):
        if isinstance(value, str) and (match := DATE_REGEX.match(value)):  # noqa F405
            return datetime_safe.date(  # noqa F405
                int(match.group("year")),
                int(match.group("month")),
                int(match.group("day")),
            ).strftime(self.FORMAT)
        return value


class DateTimeField(DateField):
    FORMAT = "%Y-%m-%d %H:%M:%S"
    base_format = datetime

    def convert(self, value):
        if isinstance(value, str) and (match := DATETIME_REGEX.match(value)):  # noqa F405
            return datetime_safe.datetime(  # noqa F405
                int(match.group("year")),
                int(match.group("month")),
                int(match.group("day")),
                int(match.group("hour")),
                int(match.group("minute")),
                int(match.group("second")),
            ).strftime(self.FORMAT)
        return value


# Для обратной совместимости с OpenSearch поле TextField приравнено к CharField
TextField = CharField  # noqa F405
