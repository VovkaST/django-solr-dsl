from typing import List, Tuple, Union

from django.utils.encoding import force_str
from haystack.backends import SQ
from haystack.backends.solr_backend import (
    SolrEngine,
    SolrSearchBackend,
    SolrSearchQuery,
)
from haystack.constants import DEFAULT_ALIAS, DOCUMENT_FIELD
from haystack.exceptions import NotHandled
from haystack.models import SearchResult
from haystack.query import SearchQuerySet

from .fields import NestedField


class ProjectSolrSearchBackend(SolrSearchBackend):
    TYPE_MAP = {
        "date": "pdate",
        "datetime": "pdate",
        "integer": "plong",
    }

    def build_schema(self, fields) -> Tuple[str, List[dict]]:
        """Метод используется для составления схемы данных.
        Перегружен только в части маппинга типов полей."""
        content_field_name = ""
        schema_fields = []

        for _, field_class in fields.items():
            field_data = {
                "field_name": field_class.index_fieldname,
                "type": "text",
                "indexed": "true",
                "stored": "true",
                "multi_valued": "false",
            }

            if field_class.document is True:
                content_field_name = field_class.index_fieldname

            if field_class.field_type in self.TYPE_MAP:
                field_data["type"] = self.TYPE_MAP[field_class.field_type]
            else:
                field_data["type"] = field_class.field_type

            if field_class.is_multivalued:
                field_data["multi_valued"] = "true"

            if field_class.stored is False:
                field_data["stored"] = "false"

            # Do this last to override `text` fields.
            if field_class.indexed is False:
                field_data["indexed"] = "false"

                # If it's text and not being indexed, we probably don't want
                # to do the normal lowercase/tokenize/stemming/etc. dance.
                if field_data["type"] == "text_en":
                    field_data["type"] = "string"

            # If it's a ``FacetField``, make sure we don't postprocess it.
            if hasattr(field_class, "facet_for"):
                # If it's text, it ought to be a string.
                if field_data["type"] == "text_en":
                    field_data["type"] = "string"

            schema_fields.append(field_data)

        return content_field_name, schema_fields


class SolrSearchResult(SearchResult):
    """
    Класс представления одной записи результата запроса.
    """

    def __getattr__(self, attr):
        return self.__dict__.get(attr, None)

    def __getitem__(self, item):
        return getattr(self, item)

    @property
    def django_id(self):
        """
        Возвращает значение первичного ключа результирующей модели,
        приведенного к типу данных в соответствии с полем модели.
        """
        *_, django_id = self.id.split(".")
        return self.model._meta.pk.to_python(django_id)

    def _nested_to_dict(
        self, field, nested: Union[dict, List[dict], None], fields_only: bool
    ) -> Union[dict, List[dict], None]:
        if nested is None:
            if field.has_default():
                return field.default
            return None
        if isinstance(nested, list):
            return self._multiple_nested_to_dict(field, nested=nested, fields_only=fields_only)
        if isinstance(nested, dict):
            value = self._single_nested_to_dict(field, nested=nested, fields_only=fields_only)
            if field.is_multivalued:
                return [value]
            return value
        raise ValueError("Nested field value must be dict or list of dict type")

    def _single_nested_to_dict(self, field, nested: dict, fields_only: bool) -> dict:
        _dict = {}
        if not nested:
            return _dict
        for field_name, field_instance in field.properties.items():
            if fields_only and not self.is_need_dump_field(field_name):
                continue
            value = nested.get(field_name)
            if isinstance(field_instance, NestedField):
                _dict[field_name] = self._nested_to_dict(field_instance, nested=value, fields_only=fields_only)
            else:
                if value is None and field_instance.has_default():
                    value = field_instance.default
                _dict[field_name] = field_instance.convert(value)
                if hasattr(field_instance, "model_field") and field_instance.model_field.primary_key:
                    _dict[field_instance.model_field.name] = _dict[field_name]

        return _dict

    def _multiple_nested_to_dict(self, field, nested: List[dict], fields_only: bool) -> List[dict]:
        _list = list()
        if not nested:
            return _list
        for single_nested in nested:
            _list.append(self._single_nested_to_dict(field, single_nested, fields_only))
        return _list

    def is_need_dump_field(self, field_name: str) -> bool:
        if self._fields:
            return field_name in self._fields
        return True

    def to_dict(self, fields_inheritance: bool = False) -> dict:
        """
        Метод приведения записи к словарю.
        По умолчанию в результирующий словарь добавляется поле `pk`
        со значением первичного ключа модели и атрибут, соответствующий имени
        первичного ключа, например:

            ---------------------------------------------------------------------
            class ModelWithGuidPk(models.Model):
                guid = models.CharField(default=uuid.uuid4, primary_key=True)
                ...

            instance = ModelWithGuidPk(guid="dc5017dd-6299-4957-8d07-b9daa5947956")
            ...

            Экземпляр строки для строки для индексированного экземпляра `instance`
            будет преобразован в словарь:
            {
                "pk": "dc5017dd-6299-4957-8d07-b9daa5947956",
                "guid": "dc5017dd-6299-4957-8d07-b9daa5947956",
                ...
            }
            ---------------------------------------------------------------------

            class ModelWithIdPk(models.Model):
                id = models.BigAutoField(primary_key=True)

            instance = ModelWithIdPk(id=123)
            ...

            Экземпляр строки для строки для индексированного экземпляра `instance`
            будет преобразован в словарь:
            {
                "pk": "123",
                "guid": 123,
                ...
            }
            ---------------------------------------------------------------------

        :param fields_inheritance: Учитывать перечень выводимых полей (`fields`) для вложенных объектов.
        """
        if self._dict is None:
            from haystack import connections

            try:
                index = connections[DEFAULT_ALIAS].get_unified_index().get_index(self.model)
            except NotHandled:
                return {}

            model_pk_field = self.model._meta.pk

            self._dict = {
                "pk": self.pk,
                model_pk_field.attname: self.django_id,
            }
            for field_name, field in index.fields.items():
                if not self.is_need_dump_field(field_name):
                    continue
                value = getattr(self, field_name, None)
                if field_name == DOCUMENT_FIELD and not value:
                    continue
                if isinstance(field, NestedField):
                    self._dict[field_name] = self._nested_to_dict(field, nested=value, fields_only=fields_inheritance)
                else:
                    if value is None and field.has_default():
                        value = field.default
                    self._dict[field_name] = field.convert(value)
        return self._dict


class SolrSearchQuerySet(SearchQuerySet):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._internal_fields = ["id", "django_ct", "django_id", "score"]
        self._fields = []

    def fields(self, *fields):
        """
        Метод ограничения полей для вывода результатов.

        :param fields: Перечень имен полей для включения в ответ.
        """
        self._fields = list(fields)
        return self

    def _clone(self, klass=None):
        """
        Внутренний метод клонирования себя с сохранением полей для вывода.
        """
        clone = super()._clone(klass)
        clone._fields = self._fields
        return clone

    def first(self) -> SolrSearchResult:
        """Получить первый элемент выборки."""
        return self[0]

    def last(self) -> SolrSearchResult:
        """Получить последний элемент выборки."""
        return self[-1]

    def _fill_cache(self, start, end, **kwargs):
        if self._fields:
            query_fields = set(self._internal_fields)
            query_fields.update(self._fields)
            self.query.fields = list(query_fields)
        return super()._fill_cache(start, end, **kwargs)

    def nested(self, **kwargs):
        return self.narrow(ParentSQ(**kwargs))

    def nested_exists(self, nested: str):
        return self.narrow(ParentSQ(**{nested: None}))

    def post_process_results(self, results):
        """
        Метод пост-обработки результатов запроса.
        Метод перегружен присвоением атрибута `_fields` каждому результату для передачи полей,
        подлежащих включению в ответ.
        """
        results = super().post_process_results(results)
        for result in results:
            setattr(result, "_fields", self._fields)
        return results


class ProjectSolrSearchQuery(SolrSearchQuery):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.result_class = SolrSearchResult

    def build_params(self, spelling_query=None, **kwargs):
        kwargs = super().build_params(spelling_query, **kwargs)
        if "fields" not in kwargs:
            kwargs["fields"] = []
        kwargs["fields"].extend(["*", "score", "[child]"])
        return kwargs


class ProjectSolrEngine(SolrEngine):
    backend = ProjectSolrSearchBackend
    query = ProjectSolrSearchQuery


class EMPTY:
    pass


class ParentSQ(SQ):
    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self._full_path = EMPTY
        self._path = EMPTY
        self._value = EMPTY
        self._key = EMPTY
        if self.children:
            self._parse_args()

    def __repr__(self):
        return "<%s: %s %s>" % (
            self.__class__.__name__,
            self.connector,
            self.as_query_string(self._repr_query_fragment_callback),
        )

    def _parse_args(self):
        self._full_path, self._value = self.children[0]
        if isinstance(self.value, list):
            self._value = " ".join(self._value)
        *path_items, self._key = self._full_path.split(".")
        self._path = "/" + "/".join(path_items)

    @property
    def value(self):
        if self.children and self._value is EMPTY:
            self._parse_args()
        return self._value

    @property
    def path(self):
        if self.children and self._path is EMPTY:
            self._parse_args()
        return self._path

    @property
    def key(self):
        if self.children and self._key is EMPTY:
            self._parse_args()
        return self._key

    def _repr_query_fragment_callback(self, field, filter_type, value):
        parent = '{!parent which="*:* -_nest_path_:*"}'
        nest_path = f"/{self.key}" if self.path == "/" else self.path
        queries = [f'+_nest_path_:"{nest_path}"']
        if value:
            queries.append(f"+{field}:({force_str(value)})")
        query = " ".join(queries)
        return f"{parent} ({query})"

    def as_query_string(self, *args, **kwargs):
        return self._repr_query_fragment_callback(self.key, self.connector, self.value)
