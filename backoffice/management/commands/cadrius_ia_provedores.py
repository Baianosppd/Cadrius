"""Diagnóstico e liberação de provedores de IA (CAD-222).

    python manage.py cadrius_ia_provedores                       # mostra o que está configurado e por que a IA (não) responde
    python manage.py cadrius_ia_provedores --liberar ANTHROPIC   # inclui o provedor na política de TODOS os escritórios
    python manage.py cadrius_ia_provedores --liberar ANTHROPIC,OLLAMA --escritorio <uuid>

Liberar um provedor para escritórios que já existem muda a lista de suboperadores deles (LGPD): registre a decisão e avise
os clientes. Escritórios novos já nascem com todos os provedores; o roteador continua bloqueando, para dado de cliente,
os planos gratuitos que treinam com os dados.
"""
from django.core.management.base import BaseCommand, CommandError

from aigov import llm
from aigov.guard import global_ai_enabled
from aigov.models import AIGovernancePolicy


class Command(BaseCommand):
    help = 'Mostra a situação dos provedores de IA e libera provedores para escritórios existentes.'

    def add_arguments(self, parser):
        parser.add_argument('--liberar', default='', help='Lista separada por vírgula (ex.: ANTHROPIC,OLLAMA).')
        parser.add_argument('--escritorio', default='', help='UUID de um escritório (padrão: todos).')

    def handle(self, *args, **opts):
        wanted = [p.strip().upper() for p in opts['liberar'].split(',') if p.strip()]
        unknown = [p for p in wanted if p not in llm.PROVIDERS]
        if unknown:
            raise CommandError(f'Provedor desconhecido: {", ".join(unknown)}. Válidos: {", ".join(llm.PROVIDERS)}')
        self.stdout.write(f'Chave geral da IA da plataforma: {"LIGADA" if global_ai_enabled() else "DESLIGADA"}')
        for row in llm.catalog():
            flag = 'configurado' if row['configurado'] else 'sem chave'
            extra = ' · só sem dado de cliente (treina com os dados)' if row['configurado'] and row['treina_com_dados'] else ''
            self.stdout.write(f'  {row["chave"]:<11} {flag:<12} modelo={row["modelo"]}{extra}')
        safe = llm.candidates(None, sensitive=True)
        self.stdout.write(f'Seguros para dado de cliente agora: {", ".join(safe) or "NENHUM — o assistente não vai responder"}')
        from aigov import routing
        self.stdout.write('IA por atividade (Gestão → IA por atividade; reserva automática se o 1º cair):')
        for row in routing.overview():
            self.stdout.write(f'  {row["atividade"]:<11} atende agora: {row["atende_agora"] or "NINGUÉM"} · ordem: '
                              f'{" > ".join(row["ordem_efetiva"]) or "—"}{" (personalizada)" if row["personalizado"] else ""}')
        qs = AIGovernancePolicy.objects.all()
        if opts['escritorio']:
            qs = qs.filter(organization_id=opts['escritorio'])
        if not wanted:
            blocked = sum(1 for p in qs if not set(safe) & set(p.allowed_providers or []))
            self.stdout.write(f'Escritórios sem nenhum provedor seguro permitido: {blocked} de {qs.count()} '
                              '(use --liberar ou peça ao dono para marcar em Segurança → IA segura).')
            return
        changed = 0
        for policy in qs:
            missing = [p for p in wanted if p not in (policy.allowed_providers or [])]
            if missing:
                policy.allowed_providers = list(policy.allowed_providers or []) + missing
                policy.updated_by = 'cadrius_ia_provedores'
                policy.save(update_fields=['allowed_providers', 'updated_by', 'updated_at'])
                changed += 1
        self.stdout.write(self.style.SUCCESS(f'{", ".join(wanted)} liberado(s) em {changed} escritório(s).'))
