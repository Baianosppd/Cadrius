from django.core.management.base import BaseCommand

from compliance import engine
from compliance.models import ComplianceSnapshot


class Command(BaseCommand):
    help = 'Grava uma fotografia da conformidade (ISO 27001, ISO 27701 e LGPD) — evidência histórica e tendência.'

    def handle(self, *args, **options):
        data = engine.evaluate_all()
        for framework in ('iso27001', 'iso27701', 'lgpd'):
            block = data[framework]
            failing = [f'{r.control.id}: {r.control.title}' for r in block['rows'] if r.status == engine.NOT_IMPLEMENTED]
            ComplianceSnapshot.objects.create(framework=framework, score=block['score'], counts=block['counts'],
                                              failing=failing[:100])
            self.stdout.write(f"{framework}: {block['score']}%")
