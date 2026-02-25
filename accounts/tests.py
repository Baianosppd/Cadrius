from django.urls import reverse
from rest_framework import status
from rest_framework.test import APITestCase
from django.contrib.auth import get_user_model

User = get_user_model()

class AccountTests(APITestCase):
    """
    Suite de testes para os endpoints do app 'accounts'.
    """

    def setUp(self):
        """
        Configuração inicial para os testes.
        Cria um usuário de teste.
        """
        self.test_user_data = {
            'email': 'testuser@example.com',
            'first_name': 'Test',
            'last_name': 'User',
            'password': 'strong-password-123'
        }
        self.user = User.objects.create_user(
            username=self.test_user_data['email'],
            email=self.test_user_data['email'],
            password=self.test_user_data['password'],
            first_name=self.test_user_data['first_name'],
            last_name=self.test_user_data['last_name']
        )

    def test_user_registration_success(self):
        """
        Testa se um novo usuário pode ser registrado com sucesso.
        """
        url = reverse('user_register')
        data = {
            'email': 'newuser@example.com',
            'password': 'new-password-123',
            'first_name': 'New',
            'last_name': 'User'
        }
        response = self.client.post(url, data, format='json')

        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertTrue(User.objects.filter(email='newuser@example.com').exists())

    def test_user_registration_fails_if_email_exists(self):
        """
        Testa se o registro falha se o e-mail já estiver em uso.
        """
        url = reverse('user_register')
        # Tenta registrar com o mesmo e-mail do usuário criado no setUp
        data = {
            'email': self.test_user_data['email'],
            'password': 'another-password',
        }
        response = self.client.post(url, data, format='json')

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn('email', response.data) # Verifica se o erro é no campo 'email'

    def test_get_user_profile_authenticated(self):
        """
        Testa se um usuário autenticado pode obter seu perfil.
        """
        url = reverse('user_profile')
        self.client.force_authenticate(user=self.user) # Força a autenticação
        response = self.client.get(url)

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data['email'], self.test_user_data['email'])
        self.assertEqual(response.data['first_name'], self.test_user_data['first_name'])

    def test_get_user_profile_unauthenticated(self):
        """
        Testa se um usuário não autenticado é bloqueado de ver o perfil.
        """
        url = reverse('user_profile')
        response = self.client.get(url)

        # O esperado é 401 Unauthorized ou 403 Forbidden, dependendo da config
        self.assertIn(response.status_code, [status.HTTP_401_UNAUTHORIZED, status.HTTP_403_FORBIDDEN])