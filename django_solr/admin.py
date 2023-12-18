from datetime import datetime

from dateutil.tz import tz
from django.apps import apps
from django.conf import settings
from django.contrib import admin, messages
from django.utils.translation import gettext as _
from django_solr.models import Indexes
from haystack import connections as haystack_connections
from haystack.management.commands.update_index import do_update

from django_solr import models


class IndexesAdmin(admin.ModelAdmin):
    list_display = ("document", "model", "hints", "updated_at")
    readonly_fields = ("document", "model", "hints", "updated_at")
    actions = ("clear_indexes", "rebuild_indexes", "update_indexes")

    def get_index(self, backend_name: str, model):
        unified_index = haystack_connections[backend_name].get_unified_index()
        return unified_index.get_index(model)

    def backends(self) -> str:
        for backend_name in haystack_connections.connections_info.keys():
            yield backend_name

    def has_add_permission(self, request) -> bool:
        return False

    def has_change_permission(self, request, obj=...) -> bool:
        return False

    def has_delete_permission(self, request, obj=...) -> bool:
        return False

    def _clear_index(self, queryset):
        models_to_delete = []
        record: Indexes
        for record in queryset:
            app_label, model_name = record.model.split(".")
            models_to_delete.append(apps.get_model(app_label, model_name))
            record.hints = 0
            record.updated_at = None
        for backend_name in self.backends():
            backend = haystack_connections[backend_name].get_backend()
            backend.clear(models=models_to_delete, commit=True)
        Indexes.objects.bulk_update(queryset, ["hints", "updated_at"])

    @admin.action(description=_("Clear selected indexes"))
    def clear_indexes(self, request, queryset):
        try:
            self._clear_index(queryset)
            messages.add_message(request=request, level=messages.INFO, message=_("Successfully cleared"))
        except Exception as error:
            error_msg = _(f"Clearing error occured")
            messages.add_message(request=request, level=messages.ERROR, message=f"{error_msg}: {error}")

    @admin.action(description=_("Rebuild selected indexes"))
    def rebuild_indexes(self, request, queryset):
        try:
            self._clear_index(queryset)
            self._update_index(queryset)
            messages.add_message(request=request, level=messages.INFO, message=_("Successfully rebuilt"))
        except Exception as error:
            error_msg = _(f"Rebuilding error occured")
            messages.add_message(request=request, level=messages.ERROR, message=f"{error_msg}: {error}")

    def do_update(self, backend, queryset):
        record: Indexes
        if settings.USE_TZ:
            tz_info = tz.gettz(settings.TIME_ZONE)
        else:
            tz_info = None
        for record in queryset:
            app_label, model_name = record.model.split(".")
            model = apps.get_model(app_label, model_name)
            index = self.get_index(backend.connection_alias, model)
            qs = index.build_queryset(using=backend.connection_alias)
            total = qs.count()
            batch_size = backend.batch_size
            max_pk = None
            for start in range(0, total, batch_size):
                end = min(start + batch_size, total)
                max_pk = do_update(backend, index, qs, start, end, total, last_max_pk=max_pk)
            record.hints = index.search().count()
            record.updated_at = datetime.now(tz=tz_info)

    def _update_index(self, queryset):
        for backend_name in self.backends():
            backend = haystack_connections[backend_name].get_backend()
            self.do_update(backend, queryset)
            Indexes.objects.bulk_update(queryset, ["hints", "updated_at"])

    @admin.action(description=_("Update selected indexes"))
    def update_indexes(self, request, queryset):
        try:
            self._update_index(queryset)
            messages.add_message(request=request, level=messages.INFO, message=_("Successfully updated"))
        except Exception as error:
            error_msg = _(f"Update error occured")
            messages.add_message(request=request, level=messages.ERROR, message=f"{error_msg}: {error}")


if admin.site.is_registered(models.Indexes):
    admin.site.unregister(models.Indexes)
admin.site.register(models.Indexes, IndexesAdmin)
