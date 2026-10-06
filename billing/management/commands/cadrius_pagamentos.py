"""CAD-224: diagnóstico da prontidão para cobrar (Stripe) — sem mostrar segredos.

    python manage.py cadrius_pagamentos            # confere configuração local (chaves, URLs, planos)
    python manage.py cadrius_pagamentos --online   # também consulta o Stripe (conta, modo e webhooks cadastrados)
"""
from django.conf import settings
from django.core.management.base import BaseCommand

from billing.models import CreditPack, Promotion, SubscriptionPlan
from billing.stripe_sync import HANDLERS

REQUIRED_EVENTS = sorted(HANDLERS)


def _mode(key: str) -> str:
    if not key:
        return 'ausente'
    if key.startswith(('sk_live_', 'rk_live_')):
        return 'PRODUÇÃO (cobra de verdade)'
    if key.startswith(('sk_test_', 'rk_test_')):
        return 'teste (não cobra)'
    return 'formato desconhecido'


class Command(BaseCommand):
    help = 'Mostra se o Cadrius está pronto para cobrar assinaturas e créditos (Stripe). Não imprime chaves.'

    def add_arguments(self, parser):
        parser.add_argument('--online', action='store_true', help='Consulta a conta e os webhooks no Stripe (somente leitura).')

    def handle(self, *args, online=False, **options):
        problems, warnings = [], []
        ok = lambda msg: self.stdout.write(self.style.SUCCESS(f'  OK   {msg}'))  # noqa: E731

        self.stdout.write('Configuração')
        key = getattr(settings, 'STRIPE_SECRET_KEY', '')
        mode = _mode(key)
        if key:
            ok(f'STRIPE_SECRET_KEY: {mode}')
        else:
            problems.append('STRIPE_SECRET_KEY vazia: o checkout responde "pagamento indisponível".')
        if getattr(settings, 'STRIPE_WEBHOOK_SECRET', ''):
            ok('STRIPE_WEBHOOK_SECRET configurado')
        else:
            problems.append('STRIPE_WEBHOOK_SECRET vazio: o webhook recusa tudo (503) e a assinatura nunca vira "ativa".')
        front = getattr(settings, 'FRONTEND_URL', '')
        if front.startswith('https://'):
            ok(f'FRONTEND_URL={front} (retorno do checkout)')
        else:
            (warnings if settings.DEBUG else problems).append(f'FRONTEND_URL={front!r}: em produção deve ser https://app...')
        methods = list(getattr(settings, 'STRIPE_PAYMENT_METHODS', ['card']))
        ok(f'Meios no checkout: {", ".join(methods)}')
        if methods == ['card']:
            warnings.append('Só cartão. Boleto em assinatura exige ativar no painel do Stripe e STRIPE_PAYMENT_METHODS=card,boleto. '
                            'Pix: confira no painel do Stripe se a conta aceita Pix em assinatura antes de incluir "pix".')

        self.stdout.write('Catálogo')
        paid = SubscriptionPlan.objects.filter(is_active=True, price_brl__gt=0)
        if paid.exists():
            ok('Planos pagos: ' + ', '.join(f'{p.name} R$ {p.price_brl}' for p in paid.order_by('price_brl')))
        else:
            problems.append('Nenhum plano pago ativo: rode "python manage.py seed_plans --apply".')
        if not SubscriptionPlan.objects.filter(is_active=True, price_brl=0).exists():
            warnings.append('Sem plano gratuito/trial ativo: o cadastro precisa de um plano de entrada.')
        ok(f'Pacotes de créditos ativos: {CreditPack.objects.filter(is_active=True).count()}')
        ok(f'Cupons ativos: {Promotion.objects.filter(is_active=True).count()}')

        if online and key:
            self.stdout.write('Stripe (online, somente leitura)')
            self._online(key, problems, warnings, ok)
        elif online:
            problems.append('--online ignorado: sem STRIPE_SECRET_KEY.')

        self.stdout.write('')
        for w in warnings:
            self.stdout.write(self.style.WARNING(f'  AVISO {w}'))
        for p in problems:
            self.stdout.write(self.style.ERROR(f'  FALTA {p}'))
        if problems:
            self.stdout.write(self.style.ERROR(f'\nNÃO está pronto para cobrar ({len(problems)} pendência(s)).'))
        else:
            self.stdout.write(self.style.SUCCESS(f'\nPronto para cobrar em modo {mode}.'))
        self.stdout.write(f'Webhook: https://<API>/api/billing/webhook/ com os eventos {", ".join(REQUIRED_EVENTS)}.')

    def _online(self, key, problems, warnings, ok):
        import stripe
        stripe.api_key = key
        try:
            acct = stripe.Account.retrieve()
            ok(f'Conta {acct.get("country")}/{acct.get("default_currency")} — cobranças '
               f'{"habilitadas" if acct.get("charges_enabled") else "NÃO habilitadas"}')
            if not acct.get('charges_enabled'):
                problems.append('Conta Stripe sem cobranças habilitadas: termine o cadastro da empresa no painel.')
            hooks = stripe.WebhookEndpoint.list(limit=20)
        except Exception as exc:  # chave inválida, rede etc.
            problems.append(f'Não foi possível consultar o Stripe: {type(exc).__name__}.')
            return
        mine = [h for h in hooks.auto_paging_iter() if h.get('url', '').endswith('/api/billing/webhook/') and h.get('status') == 'enabled']
        if not mine:
            problems.append('Nenhum webhook ativo apontando para /api/billing/webhook/.')
            return
        for h in mine:
            events = set(h.get('enabled_events') or [])
            missing = [] if '*' in events else [e for e in REQUIRED_EVENTS if e not in events]
            if missing:
                problems.append(f'Webhook {h["url"]} sem os eventos: {", ".join(missing)}.')
            else:
                ok(f'Webhook {h["url"]} com todos os eventos')
