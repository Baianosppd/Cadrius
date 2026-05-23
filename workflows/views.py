from rest_framework import status, viewsets
from rest_framework.permissions import IsAuthenticated
from rest_framework.decorators import action
from rest_framework.response import Response
from rest_framework.views import APIView

from accounts.models import Organization

from .exceptions import WorkflowGenerationQuotaExceeded
from .models import Workflow
from .serializers import WorkflowSerializer
from .services import generate_workflow_from_prompt


class WorkflowViewSet(viewsets.ModelViewSet):
    """
    CRUD para automações + ações auxiliares (ex.: geração assistida por IA).
    """

    permission_classes = [IsAuthenticated]
    queryset = Workflow.objects.all().order_by("-created_at")
    serializer_class = WorkflowSerializer

    @action(detail=False, methods=["post"], url_path="generate-from-prompt")
    def generate_from_prompt(self, request):
        """
        POST /automations/generate-from-prompt/
        Requer autenticação: IsAuthenticated (JWT em Authorization: Bearer …).
        Body: {"prompt": "<string não vazia>"}
        Devolve JSON alinhado com WorkflowGenerationSchema (ainda não persiste na BD).
        Se a IA não conseguir extrair/gerar um JSON válido, responde **422** para o front
        pedir ao utilizador que reescreva o pedido.
        Se o escritório não tiver vínculo ativo ou exceder o limite de IA do plano, **403**
        com ``code`` ``no_organization`` ou ``quota_exceeded``.
        """
        if "prompt" not in request.data:
            return Response(
                {"detail": 'O corpo JSON deve incluir o campo "prompt".'},
                status=status.HTTP_400_BAD_REQUEST,
            )

        prompt = request.data.get("prompt")
        if not isinstance(prompt, str):
            return Response(
                {"detail": 'O campo "prompt" tem de ser uma string.'},
                status=status.HTTP_400_BAD_REQUEST,
            )

        prompt_clean = prompt.strip()
        if not prompt_clean:
            return Response(
                {"detail": 'O campo "prompt" não pode ser vazio nem só espaços.'},
                status=status.HTTP_400_BAD_REQUEST,
            )

        tenant = getattr(request, "tenant", None)
        if tenant is None:
            return Response(
                {
                    "detail": (
                        "Não há um escritório ativo associado à sua conta. "
                        "Peça acesso a um escritório para usar a geração de fluxos por IA."
                    ),
                    "code": "no_organization",
                },
                status=status.HTTP_403_FORBIDDEN,
            )

        organization = Organization.objects.select_related("plan").get(pk=tenant.pk)

        try:
            data = generate_workflow_from_prompt(prompt_clean, organization)
        except WorkflowGenerationQuotaExceeded as exc:
            return Response(
                {"detail": exc.detail, "code": "quota_exceeded"},
                status=status.HTTP_403_FORBIDDEN,
            )

        if data is None:
            return Response(
                {
                    "detail": (
                        "Não conseguimos gerar o workflow a partir deste pedido. "
                        "Reescreva o texto com mais detalhe (ex.: que evento dispara o fluxo, "
                        "que ações quer e para onde enviar dados) e tente outra vez."
                    ),
                    "code": "workflow_generation_failed",
                },
                status=status.HTTP_422_UNPROCESSABLE_ENTITY,
            )
        return Response(data, status=status.HTTP_200_OK)


class GenerateWorkflowView(APIView):
    """
    POST /api/workflows/generate/
    Requer autenticação: IsAuthenticated (JWT em Authorization: Bearer …).
    Mesmo contrato que POST .../automations/generate-from-prompt/ (corpo JSON com "prompt").
    """

    permission_classes = [IsAuthenticated]

    def post(self, request):
        return WorkflowViewSet().generate_from_prompt(request)
