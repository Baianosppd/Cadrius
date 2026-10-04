from decimal import Decimal

from django.core.management.base import BaseCommand

from billing.models import CreditPack, SubscriptionPlan

# Catálogo PROPOSTO em docs/ANALISE_PRECOS_PLANOS.md §4 — os valores precisam ser aprovados pela diretoria antes de ir para produção.
PLANS = [
    dict(tier='FREE', name='Trial gratuito', price_brl=Decimal('0'), max_users=1, max_ai_extractions=30),
    dict(tier='START', name='Start', price_brl=Decimal('99'), max_users=1, max_ai_extractions=300),
    dict(tier='PRO', name='Pro', price_brl=Decimal('299'), max_users=5, max_ai_extractions=1500),
    dict(tier='ENTERPRISE', name='Business', price_brl=Decimal('799'), max_users=20, max_ai_extractions=6000),
]
PACKS = [
    dict(name='200 créditos', credits=200, price_brl=Decimal('59')),
    dict(name='1.000 créditos', credits=1000, price_brl=Decimal('199')),
    dict(name='5.000 créditos', credits=5000, price_brl=Decimal('799')),
]


class Command(BaseCommand):
    help = ('Cria o catálogo de planos e pacotes de créditos. SEM --apply só mostra o que faria (nada é gravado). '
            'Com --apply cria o que falta; com --update também ajusta preço/limites dos que já existem.')

    def add_arguments(self, parser):
        parser.add_argument('--apply', action='store_true')
        parser.add_argument('--update', action='store_true', help='Sobrescreve nome/preço/limites de planos existentes (por tier).')

    def handle(self, *args, apply=False, update=False, **options):
        self.stdout.write(('APLICANDO' if apply else 'SIMULAÇÃO (use --apply para gravar)') + '\n')
        for spec in PLANS:
            existing = SubscriptionPlan.objects.filter(tier=spec['tier']).first()
            if existing is None:
                self.stdout.write(f"  + plano {spec['tier']}: {spec['name']} R$ {spec['price_brl']} · {spec['max_users']} usuário(s) · {spec['max_ai_extractions']} créditos")
                if apply:
                    SubscriptionPlan.objects.create(is_active=True, **spec)
            elif update:
                self.stdout.write(f"  ~ plano {spec['tier']}: atualizado para R$ {spec['price_brl']} · {spec['max_ai_extractions']} créditos")
                if apply:
                    for k, v in spec.items():
                        setattr(existing, k, v)
                    existing.is_active = True
                    existing.save()
            else:
                self.stdout.write(f"  = plano {spec['tier']} já existe (R$ {existing.price_brl}); use --update para ajustar")
        for spec in PACKS:
            existing = CreditPack.objects.filter(credits=spec['credits']).first()
            if existing is None:
                self.stdout.write(f"  + pacote {spec['name']} R$ {spec['price_brl']}")
                if apply:
                    CreditPack.objects.create(is_active=True, **spec)
            elif update:
                self.stdout.write(f"  ~ pacote {spec['name']} → R$ {spec['price_brl']}")
                if apply:
                    existing.name, existing.price_brl, existing.is_active = spec['name'], spec['price_brl'], True
                    existing.save()
            else:
                self.stdout.write(f"  = pacote {spec['name']} já existe")
        if not apply:
            self.stdout.write(self.style.WARNING('\nNada foi gravado.'))
