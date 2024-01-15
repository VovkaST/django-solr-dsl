from django.db import models as django_models
from django.db.models.fields import NOT_PROVIDED as DJANGO_NOT_PROVIDED
from haystack.constants import DJANGO_ID, DOCUMENT_FIELD, ID
from haystack.indexes import *

from .backend import SolrSearchQuerySet
from .exception import MultipleResultError, NotFoundError
from .fields import NestedField, TextGeneralField


class SolrDocument(SearchIndex):
    """
    Основной класс объявления SOLR-индексов (документов).
    Т.к. при традиционном подходе к поиску основным поисковым полем является
    единственное - text, оно объявляется по умолчанию для всех документов.
    При этом, оно не является обязательным, т.к. исключена проверка наличия шаблона.

    Для связи с моделью Django необходимо объявить вложенный класс `Django` с атрибутом `model`,
    в значении которого указать конкретную модель из включенного в проект приложения.

    Также добавлен новый тип поля - NestedField, представляющее собой вложенную иерархию.
    Обязательность полей вложенных объектов определяется одноименными полями модели Django.

    Для объявления новых документов нужен атрибут `haystack_use_for_indexing` в значении
    `True` (указать принудительно или использовать при наследовании класс
    haystack.indexes.Indexable).

        class MyDocument(SolrDocument, indexes.Indexable):
            class Django:
                model = models.MyModel


    ### ПРИМЕЧАНИЕ:

    Весь функционал и именование максимально приведены к идентичности с DSL OpenSearch, однако,
    без особенностей не обошлось:

    * Для полей первого уровня (объявленных непосредственно в классе документа) недопустимо
      использование имени поля `pk`, т.к. оно используется для сборки экземпляров
      `SolrSearchResult`. При этом, при индексации ошибка выброшена не будет, но возникнут
      проблемы при получении и обработке результатов запроса.
    * Для полей всех уровней не рекомендуется использовать имя атрибута `id`, т.к. значение
      идентификатора для каждого объекта индекса должно быть уникально в рамках ядра. Поэтому
      данное поле является составным и автогенерируемым. В его значение включется название
      приложения, модели и значение первичного ключа, разделенные символом точки. Натуральное
      значение первичного ключа модели хранится в служебном атрибуте django_id.

    """

    text = TextGeneralField(document=True, use_template=True)

    def __init__(self):
        super().__init__()
        self.model = None
        self._django = getattr(self, "Django", None)

        if self._django:
            self.model = getattr(self._django, "model", None)
            self.set_fields_attributes(self.model, self.fields)

    def get_model_fields_map(self, model) -> dict:
        _map = {}
        for field in model._meta.fields:
            _map[field.name] = field
            if field.primary_key:
                _map["pk"] = field
        return _map

    def set_fields_attributes(self, model, fields):
        """
        Автоматическая установка атрибутов объявленных полей документа.
        Применяются следующие правила:

        - `model_attr` (соответствие атрибуту индексируемой модели): по умолчанию
          используется имя атрибута, которому присваивается объявляемое поле.
          Возможно указание произвольного имени, но при этом в одноименном параметре
          ожидается имя поля, с которым данный атрибут связывается.

          * ```code = fields.TextField()```
            Объявленное текстовое поле `code` будет связано с одноименным полем
            индексируемой модели.

          * ```my_custom_code_field = fields.TextField(model_attr="code")```
            Объявленное текстовое поле `my_custom_code_field` будет связано
            с полем `code` индексируемой модели, при этом в индексе ключ будет
            именоваться как `my_custom_code_field`.

        - `null` (обязательность наличия значения): соответствует атрибуту `null`
          связанного поля модели.

        - В атрибут `model_field` указывается ссылка на соответствущее атрибуту
          документа поле индексируемой модели.

        - Если не указано значение по умолчанию, то используется значение
          по умолчанию для связанного поля модели, если оно также задано.

        """
        model_fields_map = self.get_model_fields_map(model)
        for field_name, field in fields.items():
            if field_name == DOCUMENT_FIELD:
                continue
            if isinstance(field, NestedField):
                relation_field = getattr(model, field_name, None)
                if not relation_field and field.model_attr:
                    relation_field = getattr(model, field.model_attr, None)
                if not relation_field:
                    continue
                related_model = relation_field.field.related_model
                if related_model is model and hasattr(relation_field, "rel"):
                    related_model = relation_field.rel.related_model
                self.set_fields_attributes(
                    model=related_model,
                    fields=field.properties,
                )
                setattr(field, "model_field", relation_field)
                if not field.has_default():
                    if isinstance(relation_field.field, django_models.ForeignKey):
                        field._default = dict()
                    elif isinstance(relation_field.field, django_models.ManyToManyField):
                        field.is_multivalued = True
                        field._default = list()
                    else:
                        # todo: Возможные варианты других типов полей
                        pass
                    continue

            if not field.model_attr:
                field.model_attr = field_name
            if field.model_attr in model_fields_map:
                field.null = model_fields_map[field.model_attr].null
            model_field = model_fields_map.get(field.model_attr)
            if not model_field and field.model_attr.endswith("_id"):
                model_field = model_fields_map.get(field.model_attr[:-3])
            if model_field:
                setattr(field, "model_field", model_field)
            if not field.has_default():
                model_field_default = field.model_field.default
                if model_field_default is not DJANGO_NOT_PROVIDED and not callable(model_field_default):
                    field._default = model_field_default

    def get_model(self):
        return self.model

    @classmethod
    def search(cls) -> SolrSearchQuerySet:
        """
        Инициализировать запрос от текущей БД.
        """
        return SolrSearchQuerySet().models(cls.Django.model)

    def get_field_weights(self):
        return

    @classmethod
    def get(cls, *args, **kwargs):
        """
        Получить запись из индекса текущей модели по идентификатору.
        Допустимы имена первичных ключей: id, django_id, guid и uuid. Т.к. django_id -
        это эквивалент первичного ключа Django, если передан неименованный параметр,
        в качестве поискового ключа используется он.

        Ошибки:
            * `NotFoundError`: Запись не найдена.
            * `MultipleResultError`: Найдено больше, чем одна запись.

        """
        pk_fields = (ID, DJANGO_ID, "guid", "uuid")
        if args:
            pk_name = DJANGO_ID
            pk = args[0]
        else:
            for pk_name in pk_fields:
                if kwargs.get(pk_name):
                    pk = kwargs.get(pk_name)
                    break
            else:
                raise AttributeError(f"One of available pk names must be implemented: {', '.join(pk_fields)}")
        search = cls.search().filter(**{pk_name: pk})

        fields = kwargs.get("fields")
        if fields:
            search.fields(*fields)
        count = search.count()
        if not count:
            raise NotFoundError("No items found")
        if count > 1:
            raise MultipleResultError(f"Multiple records found ({count}). Expected only one.")
        return search.first()
