from django.core.management.base import BaseCommand
from django_q.models import Schedule

# nome -> (comando, tipo, minutos)
JOBS = {
    'Segurança: detetar anomalias': ('run_anomaly_detection', Schedule.MINUTES, 5),
    'Segurança: verificar cadeia de auditoria': ('verify_audit_chain', Schedule.DAILY, None),
    'Privacidade: aplicar retenção (LGPD)': ('enforce_retention', Schedule.DAILY, None),
    'Conformidade: fotografia diária': ('snapshot_compliance', Schedule.DAILY, None),
    'Agenda: sincronizar Google Calendar': ('gcal_pull', Schedule.MINUTES, 15),
    'Pesquisa: consultar andamentos de processos': ('research_poll', Schedule.HOURLY, None),
    'Pesquisa: atualizar notícias': ('research_news', Schedule.HOURLY, None),
    'Privacidade: limpar importações abandonadas': ('purge_import_rows', Schedule.DAILY, None),
    'IA: aprender com as decisões (regras e autonomia)': ('brain_evaluate', Schedule.DAILY, None),
    'Automações: prazos próximos e regras agendadas': ('automations_tick', Schedule.MINUTES, 15),
    'Publicações: capturar comunicações do DJEN': ('publications_poll', Schedule.MINUTES, 180),
}


class Command(BaseCommand):
    help = 'Agenda (Django-Q) as rotinas de segurança: deteção de anomalias, verificação da cadeia e retenção.'

    def handle(self, *args, **options):
        for name, (command, kind, minutes) in JOBS.items():
            defaults = {'func': 'django.core.management.call_command', 'args': f"'{command}'",
                        'schedule_type': kind, 'repeats': -1}
            if minutes:
                defaults['minutes'] = minutes
            _, created = Schedule.objects.update_or_create(name=name, defaults=defaults)
            self.stdout.write(f"{'criado' if created else 'atualizado'}: {name}")
