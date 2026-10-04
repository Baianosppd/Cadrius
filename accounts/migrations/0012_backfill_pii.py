"""CAD-152: cifra e indexa os dados pessoais JÁ existentes (a migração anterior só troca o tipo das colunas).

Os campos são ``EncryptedTextField``: ao ler, valor legado em texto puro passa como está; ao salvar, é cifrado.
Aqui calculamos os índices (CPF/CNPJ cegos, nome por tokens) e regravamos cada linha. Reversível sem perda
(a reversão é no-op: os dados continuam legíveis).
"""
from django.db import migrations

USER_FIELDS = ['first_name', 'last_name', 'phone', 'cpf', 'oab_number', 'cpf_bidx', 'name_idx']
ORG_FIELDS = ['cnpj', 'cep', 'street', 'number', 'neighborhood', 'main_phone', 'corporate_phone', 'corporate_email', 'cnpj_bidx']


def backfill(apps, schema_editor):
    from core.pii import blind_index, search_tokens

    User = apps.get_model('accounts', 'CustomUser')
    for user in User.objects.all().iterator():
        user.cpf_bidx = blind_index('user.cpf', user.cpf, 'digits')
        user.name_idx = search_tokens('user.name', f'{user.first_name or ""} {user.last_name or ""}')
        user.save(update_fields=USER_FIELDS)

    Organization = apps.get_model('accounts', 'Organization')
    for org in Organization.objects.all().iterator():
        org.cnpj_bidx = blind_index('org.cnpj', org.cnpj, 'digits')
        org.save(update_fields=ORG_FIELDS)


class Migration(migrations.Migration):
    dependencies = [('accounts', '0011_encrypt_pii')]
    operations = [migrations.RunPython(backfill, migrations.RunPython.noop)]
