import uuid

from django.db import models
from django.utils.translation import gettext_lazy as _


class Indexes(models.Model):
    guid = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    document = models.CharField(_("Document name"), max_length=255, db_index=True, editable=False)
    model = models.CharField(_("Model name"), max_length=255, db_index=True, editable=False)
    updated_at = models.DateTimeField(_("Date and time of last index"), null=True, blank=True, editable=False)
    hints = models.PositiveIntegerField(_("Count of hints in index"), default=0, editable=False)

    def __str__(self):
        return f"<{self.document}: {self.hints}>"

    class Meta:
        verbose_name = _("Index")
        verbose_name_plural = _("Indexes")
