from django import views
from django.views.decorators.csrf import csrf_exempt
from haystack import connections as haystack_connections
from haystack.exceptions import NotHandled
from haystack.utils.app_loading import haystack_get_models, haystack_load_apps

from django_solr import models


class FetchIndexesView(views.generic.RedirectView):
    pattern_name = "admin:django_solr_indexes_changelist"

    @csrf_exempt
    def post(self, request, *args, **kwargs):
        labels = haystack_load_apps()
        backends = haystack_connections.connections_info.keys()
        for label in labels:
            for using in backends:
                unified_index = haystack_connections[using].get_unified_index()
                for model in haystack_get_models(label):
                    try:
                        index = unified_index.get_index(model)
                    except NotHandled:
                        continue
                    hints = index.search().count()
                    record, is_created = models.Indexes.objects.get_or_create(
                        document=index.__class__.__name__,
                        defaults={
                            "model": index.model._meta.label,
                            "hints": hints,
                        },
                    )
                    if not is_created:
                        record.hints = hints
                        record.save()
        return super().post(request, *args, **kwargs)


class RebuildIndexView(views.generic.RedirectView):
    pass
