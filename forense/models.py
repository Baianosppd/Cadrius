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


class CourtSuspension(models.Model):
    """Suspensão de prazos / falta de expediente / indisponibilidade de sistema num tribunal (CAD-223).

    Cadastrada pela equipe Cadrius (área Jurídico) a partir da portaria/certidão do tribunal; vale para TODOS os escritórios:
    entra na contagem de prazos (``forense.calendar``) e dispara o gatilho ``court_suspension`` para quem tem processo ali.
    ``tribunal`` vazio = nacional (ex.: suspensão determinada pelo CNJ)."""

    class Kind(models.TextChoices):
        DEADLINES = 'prazos', 'Suspensão de prazos'
        CLOSED = 'expediente', 'Sem expediente forense'
        OUTAGE = 'indisponibilidade', 'Indisponibilidade do sistema (prorroga prazos)'

    tribunal = models.CharField(max_length=12, blank=True, default='', db_index=True)
    comarca = models.CharField(max_length=80, blank=True, default='')          # vazio = todo o tribunal
    kind = models.CharField(max_length=20, choices=Kind.choices, default=Kind.DEADLINES)
    start = models.DateField(db_index=True)
    end = models.DateField()
    reason = models.CharField(max_length=200)
    source_url = models.URLField(max_length=500, blank=True, default='')       # portaria/certidão oficial
    created_by = models.ForeignKey('accounts.CustomUser', null=True, blank=True, on_delete=models.SET_NULL, related_name='+')
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-start']


class CourtInfo(models.Model):
    """Dados de serviço de um tribunal para a rotina do advogado (CAD-223): Balcão Virtual (Res. CNJ 372/2021), portal de serviços,
    consulta de pauta. Mantido pela área Jurídico da Cadrius (links oficiais, conferidos)."""

    tribunal = models.CharField(max_length=12, unique=True)
    name = models.CharField(max_length=120)
    balcao_virtual_url = models.URLField(max_length=500, blank=True, default='')
    services_url = models.URLField(max_length=500, blank=True, default='')
    hearings_url = models.URLField(max_length=500, blank=True, default='')
    hours = models.CharField(max_length=120, blank=True, default='')            # ex.: "12h às 18h"
    notes = models.CharField(max_length=500, blank=True, default='')
    updated_by = models.ForeignKey('accounts.CustomUser', null=True, blank=True, on_delete=models.SET_NULL, related_name='+')
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['tribunal']
