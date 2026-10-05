"""Obrigações-padrão do Fiscal da Cadrius (CAD-175). Editáveis na Gestão → Fiscal → Obrigações. [VALIDAR com o contador]"""
from django.db import migrations

DEFAULTS = [
    ('pgdas-das', 'PGDAS-D e DAS (Simples Nacional)', 'Declaração e guia do mês anterior.', 'mensal', 20, 0, 'posterga'),
    ('dctfweb', 'DCTFWeb', 'Débitos previdenciários e retenções do mês anterior.', 'mensal', 0, 0, 'ultimo_util'),
    ('efd-reinf', 'EFD-Reinf', 'Retenções e informações fiscais do mês anterior.', 'mensal', 15, 0, 'antecipa'),
    ('iss', 'ISS municipal (se fora do DAS)', 'Guia do ISS conforme o município.', 'mensal', 10, 0, 'posterga'),
    ('fgts-digital', 'FGTS Digital', 'Se houver empregados.', 'mensal', 20, 0, 'antecipa'),
    ('esocial', 'eSocial (folha)', 'Eventos periódicos da folha, se houver empregados.', 'mensal', 15, 0, 'antecipa'),
    ('defis', 'DEFIS (Simples Nacional)', 'Declaração anual de informações socioeconômicas e fiscais.', 'anual', 31, 3, 'antecipa'),
]


def seed(apps, schema_editor):
    Ob = apps.get_model('billing', 'FiscalObligation')
    for code, name, desc, per, day, month, adj in DEFAULTS:
        Ob.objects.get_or_create(code=code, defaults={'name': name, 'description': desc, 'periodicity': per, 'due_day': day,
                                                      'due_month': month or 3, 'adjust': adj})


class Migration(migrations.Migration):
    dependencies = [('billing', '0006_fiscalobligation_payment_nfse_error_payment_nfse_ref_and_more')]
    operations = [migrations.RunPython(seed, migrations.RunPython.noop)]
