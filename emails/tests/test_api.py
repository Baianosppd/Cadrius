import pytest
from django.urls import reverse
from rest_framework import status
from emails.models import MailBox
from django.contrib.auth import get_user_model

# Configuração para que o Pytest detecte o Django
pytestmark = pytest.mark.django_db

User = get_user_model()

# --- Fixtures Comuns (Dados de Teste) ---

@pytest.fixture
def api_user():
    """Cria um usuário padrão para testes de API."""
    return User.objects.create_user(username='tester', password='testpassword')

@pytest.fixture
def auth_client(api_client, api_user):
    """
    Cliente de API autenticado via JWT.
    Simula o login e anexa o token Bearer ao cabeçalho.
    """
    # 1. Obter o token JWT (simulando o POST /api/v1/auth/token/)
    response = api_client.post(
        reverse('token_obtain_pair'),
        {'username': api_user.username, 'password': 'testpassword'},
        format='json'
    )
    assert response.status_code == status.HTTP_200_OK
    token = response.data['access']
    
    # 2. Configurar o cliente com o token
    api_client.credentials(HTTP_AUTHORIZATION=f'Bearer {token}')
    return api_client

@pytest.fixture
def sample_mailbox():
    """Cria uma instância de MailBox para testes de CRUD."""
    return MailBox.objects.create(
        name="Suporte Primário",
        imap_host="imap.support.com",
        imap_port=993,
        username="support@domain.com",
        password="secure_password"
    )

# --- Testes de Autenticação JWT (Jullio) ---

class TestAuthEndpoints:
    """Testa se os endpoints de autenticação e acesso funcionam."""

    def test_token_creation_success(self, api_client, api_user):
        """Deve retornar tokens de acesso e refresh após login bem-sucedido."""
        url = reverse('token_obtain_pair')
        response = api_client.post(url, {'username': api_user.username, 'password': 'testpassword'})
        
        assert response.status_code == status.HTTP_200_OK
        assert 'access' in response.data
        assert 'refresh' in response.data

    def test_protected_endpoint_requires_auth(self, api_client):
        """Um endpoint protegido (ex: listagem de emails) deve falhar sem token."""
        url = reverse('emailmessage-list')
        response = api_client.get(url)
        
        # Espera falha de autenticação (401 Unauthorized)
        assert response.status_code == status.HTTP_401_UNAUTHORIZED

# --- Testes de MailBox CRUD (Jullio) ---

class TestMailBoxEndpoints:
    """Testa o CRUD (Create, Retrieve, Update, Delete) do MailBoxViewSet."""
    list_url = reverse('mailbox-list')
    
    def test_mailbox_list_authenticated(self, auth_client, sample_mailbox):
        """Deve listar MailBoxes para um usuário autenticado."""
        response = auth_client.get(self.list_url)
        
        assert response.status_code == status.HTTP_200_OK
        assert len(response.data) == 1
        assert response.data[0]['name'] == sample_mailbox.name
        # Critério de segurança: a senha NUNCA deve ser retornada
        assert 'password' not in response.data[0]

    def test_mailbox_create_success(self, auth_client):
        """Deve permitir a criação de uma nova MailBox."""
        payload = {
            "name": "Vendas",
            "imap_host": "imap.sales.com",
            "imap_port": 993,
            "username": "sales@domain.com",
            "password": "new_secure_password"
        }
        response = auth_client.post(self.list_url, payload, format='json')
        
        assert response.status_code == status.HTTP_201_CREATED
        assert MailBox.objects.count() == 1
        
        # Critério de segurança: a senha enviada não deve estar na resposta
        assert 'password' not in response.data
        
        # Verifica se o password foi salvo (não deve ser fácil de checar, mas o teste confirma)
        mailbox = MailBox.objects.get(name="Vendas")
        assert mailbox.password == "new_secure_password"


    def test_mailbox_update_success(self, auth_client, sample_mailbox):
        """Deve permitir a atualização de campos da MailBox."""
        detail_url = reverse('mailbox-detail', args=[sample_mailbox.id])
        new_host = "novo.imap.com"
        
        response = auth_client.patch(
            detail_url, 
            {'imap_host': new_host}, 
            format='json'
        )
        
        assert response.status_code == status.HTTP_200_OK
        sample_mailbox.refresh_from_db()
        assert sample_mailbox.imap_host == new_host