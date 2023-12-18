from django.urls import path

from django_solr import views

app_name = "django_solr"

urlpatterns = [
    path("fetch/", views.FetchIndexesView.as_view(), name="index_fetch"),
]
