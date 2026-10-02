"""
CAD-063: testes de isolamento multi-tenant (ausência de data leakage entre escritórios).

Cenário: dois escritórios com workflows próprios; cada utilizador só vê e acede
aos registos da sua Organization via TenantAwareViewSet.
"""
from django.contrib.auth import get_user_model
from django.urls import reverse
from rest_framework import status
from rest_framework.test import APITestCase

from accounts.models import Organization, OrganizationMembership
from billing.models import SubscriptionPlan
from workflows.models import Workflow

User = get_user_model()


class CrossTenantDataLeakageTests(APITestCase):
    """Garante que dados de um escritório não vazam para outro via API REST."""

    def setUp(self):
        """
        Base de dados de teste (CAD-063):
        - Organização A → Utilizador A → Workflow A
        - Organização B → Utilizador B → Workflow B
        """
        self.plan = SubscriptionPlan.objects.create(
            name="Plano Leak Test",
            tier="PRO",
            price_brl=99,
            max_users=10,
            max_ai_extractions=1000,
        )

        # --- Organização A ---
        self.organization_a = Organization.objects.create(
            name="Organização A",
            plan=self.plan,
        )
        self.user_a = User.objects.create_user(
            username="utilizador_a@cadrius.test",
            email="utilizador_a@cadrius.test",
            password="strong-password-123",
        )
        OrganizationMembership.objects.create(
            user=self.user_a,
            organization=self.organization_a,
            role="OWNER",
        )
        self.workflow_a = Workflow.objects.create(
            name="Workflow A",
            organization=self.organization_a,
            description="Pertence apenas à Organização A",
        )

        # --- Organização B ---
        self.organization_b = Organization.objects.create(
            name="Organização B",
            plan=self.plan,
        )
        self.user_b = User.objects.create_user(
            username="utilizador_b@cadrius.test",
            email="utilizador_b@cadrius.test",
            password="strong-password-123",
        )
        OrganizationMembership.objects.create(
            user=self.user_b,
            organization=self.organization_b,
            role="OWNER",
        )
        self.workflow_b = Workflow.objects.create(
            name="Workflow B",
            organization=self.organization_b,
            description="Pertence apenas à Organização B",
        )

        # Aliases curtos (compatível com asserts existentes)
        self.org_a = self.organization_a
        self.org_b = self.organization_b

        self.list_url = reverse("workflow-list")

    def test_seed_organization_a_and_b_in_test_db(self):
        """Confirma o seed: Org A+User A+Workflow A e Org B+User B+Workflow B."""
        self.assertEqual(self.organization_a.name, "Organização A")
        self.assertEqual(self.workflow_a.organization_id, self.organization_a.id)
        self.assertTrue(
            OrganizationMembership.objects.filter(
                user=self.user_a,
                organization=self.organization_a,
                is_active=True,
            ).exists()
        )

        self.assertEqual(self.organization_b.name, "Organização B")
        self.assertEqual(self.workflow_b.organization_id, self.organization_b.id)
        self.assertTrue(
            OrganizationMembership.objects.filter(
                user=self.user_b,
                organization=self.organization_b,
                is_active=True,
            ).exists()
        )

        # Isolamento na BD: workflows em organizações distintas
        self.assertNotEqual(self.workflow_a.organization_id, self.workflow_b.organization_id)
        self.assertEqual(Organization.objects.filter(name__startswith="Organização").count(), 2)

    def _workflow_ids(self, response):
        """Extrai IDs de listagens paginadas ou listas simples."""
        data = response.data
        results = data["results"] if isinstance(data, dict) and "results" in data else data
        return {item["id"] for item in results}

    def test_get_workflows_as_user_a_excludes_workflow_b(self):
        """
        Autenticar como Utilizador A e GET no endpoint de Workflows.
        Assertiva: Workflow A devolvido; Workflow B não pode estar na lista.
        """
        self.client.force_authenticate(user=self.user_a)
        response = self.client.get(self.list_url)

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        ids = self._workflow_ids(response)

        self.assertIn(
            self.workflow_a.id,
            ids,
            msg="Workflow A tem de ser devolvido ao Utilizador A.",
        )
        self.assertNotIn(
            self.workflow_b.id,
            ids,
            msg="Workflow B não pode aparecer na lista do Utilizador A (data leakage).",
        )

    def test_list_workflows_tenant_b_isolated(self):
        """Utilizador B lista workflows e não vê o fluxo do escritório A."""
        self.client.force_authenticate(user=self.user_b)
        response = self.client.get(self.list_url)

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        ids = self._workflow_ids(response)
        self.assertIn(self.workflow_b.id, ids)
        self.assertNotIn(self.workflow_a.id, ids)

    def test_retrieve_foreign_tenant_workflow_returns_404(self):
        """Acesso direto ao detalhe de workflow de outro tenant → 404 (sem leakage)."""
        self.client.force_authenticate(user=self.user_a)
        url = reverse("workflow-detail", kwargs={"pk": self.workflow_b.id})
        response = self.client.get(url)

        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)

    def test_patch_workflow_b_as_user_a_returns_404_not_403(self):
        """
        Autenticar como Utilizador A e PATCH com o ID do Workflow B.
        Assertiva: estritamente HTTP 404 (nunca 403 — não revelar que o ID existe).
        """
        self.client.force_authenticate(user=self.user_a)
        url = reverse("workflow-detail", kwargs={"pk": self.workflow_b.id})
        response = self.client.patch(
            url,
            {"name": "Tentativa de alteração cross-tenant"},
            format="json",
        )

        self.assertEqual(
            response.status_code,
            status.HTTP_404_NOT_FOUND,
            msg="PATCH cross-tenant tem de ser 404, não 403 nem 200.",
        )
        self.assertNotEqual(
            response.status_code,
            status.HTTP_403_FORBIDDEN,
            msg="403 revelaria que o Workflow B existe na base de dados.",
        )
        # Garante que o registo B não foi alterado
        self.workflow_b.refresh_from_db()
        self.assertEqual(self.workflow_b.name, "Workflow B")

    def test_user_without_organization_sees_empty_list(self):
        """Utilizador autenticado sem membership ativa não vê workflows de ninguém."""
        lone = User.objects.create_user(
            username="sem-org@cadrius.test",
            email="sem-org@cadrius.test",
            password="strong-password-123",
        )
        self.client.force_authenticate(user=lone)
        response = self.client.get(self.list_url)

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        ids = self._workflow_ids(response)
        self.assertEqual(ids, set())
