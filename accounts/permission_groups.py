"""Catálogo de grupos de permissão (TEAM-02)."""
from __future__ import annotations

PERMISSION_GROUPS = [
    {
        'name': 'Admin',
        'description': 'Acesso total ao sistema',
        'permissions': [
            'Ver documentos',
            'Criar documentos',
            'Editar documentos',
            'Deletar documentos',
            'Gerir equipa',
            'Gerir automações',
            'Ver faturação',
            'Gerir integrações',
        ],
    },
    {
        'name': 'Advogado Pleno',
        'description': 'Acesso operacional completo, sem gestão de equipa',
        'permissions': [
            'Ver documentos',
            'Criar documentos',
            'Editar documentos',
            'Executar automações',
            'Gerir tarefas',
            'Ver atividades recentes',
        ],
    },
    {
        'name': 'Estagiário',
        'description': 'Acesso limitado para acompanhamento e apoio',
        'permissions': [
            'Ver documentos',
            'Ver tarefas',
            'Comentar documentos',
            'Ver atividades recentes',
        ],
    },
]


def list_permission_groups() -> list[dict]:
    return PERMISSION_GROUPS
