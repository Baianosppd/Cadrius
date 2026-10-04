"""Presets de provedor de e-mail (CAD-155/161). Trocar de provedor = mudar EMAIL_PROVIDER (e usuário/senha) no .env, sem tocar no código.

Cada preset só define host/porta/TLS; usuário e senha SEMPRE vêm do ambiente. ``EMAIL_HOST``/``EMAIL_PORT``/``EMAIL_USE_TLS`` explícitos
no ambiente sobrescrevem o preset (qualquer SMTP serve: provedor ``custom``).
"""
PRESETS = {
    # Gmail / Google Workspace: exige verificação em 2 etapas + SENHA DE APP (não a senha da conta). Ver deploy/EMAIL.md.
    'gmail': {'host': 'smtp.gmail.com', 'port': 587, 'tls': True},
    'brevo': {'host': 'smtp-relay.brevo.com', 'port': 587, 'tls': True},
    'ses': {'host': 'email-smtp.sa-east-1.amazonaws.com', 'port': 587, 'tls': True},   # troque a região se necessário via EMAIL_HOST
    'locaweb': {'host': 'email-ssl.com.br', 'port': 587, 'tls': True},
    'custom': {'host': '', 'port': 587, 'tls': True},
}


def resolve(provider: str) -> dict:
    provider = (provider or '').strip().lower()
    if provider and provider not in PRESETS:
        raise ValueError(f'EMAIL_PROVIDER desconhecido: {provider!r}. Use um de {sorted(PRESETS)}.')
    return PRESETS.get(provider, PRESETS['custom'])
