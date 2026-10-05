from django.db import models


class Holiday(models.Model):
    """Feriado/fechamento cadastrado pelo escritório (municipal, estadual ou do tribunal) — CAD-172.

    Os nacionais e o recesso forense já vêm calculados em ``forense.calendar`` (não precisam de cadastro)."""

    organization = models.ForeignKey('accounts.Organization', on_delete=models.CASCADE, related_name='holidays')
    date = models.DateField()
    name = models.CharField(max_length=120)
    tribunal = models.CharField(max_length=12, blank=True, default='')   # vazio = vale para todos; 'tjsp' = só esse tribunal
    yearly = models.BooleanField(default=False)                         # repete todo ano (mesmo dia/mês)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['date']
