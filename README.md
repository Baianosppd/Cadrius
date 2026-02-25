🚀 Cadrius
Plataforma SaaS de Hiperautomação Jurídica e Empresarial.

O Cadrius é uma plataforma Multi-tenant que permite a orquestração de processos complexos unindo gatilhos digitais (E-mail, Webhooks), físicos (IoT/MQTT) e Inteligência Artificial (LLMs), através de uma interface visual No-Code.

📑 Índice

1.Visão Geral e Funcionalidades
2.Stack Tecnológico
3.Pré-requisitos
4.Instalação e Execução (Docker)
5.Estrutura do Projeto
6.Variáveis de Ambiente
7.Testes e Qualidade
8.Contribuindo
9.Autores

🌟 Visão Geral e Funcionalidades

O sistema foi desenhado para escalar como um SaaS B2B, atendendo escritórios e indústrias com isolamento total de dados.

*Multi-tenancy: Isolamento estrito de dados por Organização.
*Workflow Engine: Editor visual (nós e arestas) para criar automações.
*AI Agents (RAG): Assistente inteligente com memória contextual da empresa.
*Integrações: Conectores nativos para WhatsApp, Trello, ERPs (Bling) e E-mail.
*IoT Ready: Ingestão de telemetria via MQTT para automação industrial.

🛠 Stack Tecnológico
A arquitetura segue o padrão de Monolito Modular containerizado.

Backend & Infra

*Linguagem: Python 3.11
*Framework: Django + Django REST Framework (DRF)
*Assincronia: Django-Q (Task Queue)
*Real-time: Django Channels (WebSockets/ASGI)
*Banco de Dados: PostgreSQL 15 (com extensão pgvector)
*Cache/Broker: Redis 7
*IoT Broker: Eclipse Mosquitto (MQTT)
*Infra: Docker & Docker Compose

Frontend (SPA)

*Framework: React.js
*Build: Vite
*Visual: TailwindCSS + ReactFlow

📋 Pré-requisitos

Antes de começar, certifique-se de ter instalado na sua máquina:

*Docker e Docker Compose (Essencial)
*Git

🐳 Instalação e Execução (Docker)
Siga estes passos para levantar o ambiente de desenvolvimento completo em minutos.

1. Clonar o Repositório

git clone https://github.com/JullioDutra/cadrius-backend.git


2. Configurar Variáveis de Ambiente

Duplique o arquivo de exemplo e renomeie para .env.

cp .env.example .env
Edite o .env se necessário, mas os valores padrão já funcionam para o Docker local.

3. Subir os Containers
Este comando irá baixar as imagens, instalar dependências e subir: Banco, Redis, API e Worker.

docker-compose up --build

4. Executar Migrations e Criar Superusuário
Com os containers rodando, abra um novo terminal e execute:

# Criar as tabelas no Banco de Dados
docker-compose exec web python manage.py migrate

# (Opcional) Popular dados iniciais de SaaS
docker-compose exec web python manage.py loaddata initial_data.json

# Criar um administrador para acessar o /admin
docker-compose exec web python manage.py createsuperuser

5. Acessar a Aplicação

API / Backend: http://localhost:8000
Documentação Swagger: http://localhost:8000/swagger/
Admin do Django: http://localhost:8000/admin/

📂 Estrutura do Projeto

cadrius/
├── accounts/         # Gestão de Usuários e Organizações (Multi-tenant)
├── core/             # Utilitários base e modelos abstratos
├── integrations/     # Adaptadores para APIs externas (WhatsApp, Trello)
├── tasks/            # Definição das tarefas assíncronas (Django-Q)
├── workflows/        # Lógica do motor de automação (Engine)
├── cadrius/          # Configurações do projeto (settings.py, urls.py)
├── docker-compose.yml
├── Dockerfile
├── manage.py
└── requirements.txt

🔑 Variáveis de Ambiente

Variável,Descrição,Padrão (Local)
DEBUG,Modo de Debug do Django,True
SECRET_KEY,Chave criptográfica do Django,insecure-dev...
DATABASE_URL,String de conexão do Postgres,postgres://...
REDIS_URL,String de conexão do Redis,redis://...
OPENAI_API_KEY,Chave para funcionalidades de IA,None

🧪 Testes e Qualidade
Para garantir a estabilidade do sistema, execute os testes automatizados dentro do container:

# Rodar todos os testes
docker-compose exec web pytest

# Rodar testes com relatório de cobertura
docker-compose exec web pytest --cov=.

🤝 Contribuindo

Utilizamos o fluxo Gitflow Adaptado.

A branch main é produção (intocável).

A branch develop é o ambiente de integração.

Para nova funcionalidade: crie uma branch feat/nome-da-tarefa a partir da develop.

Para correção de bug: crie uma branch fix/nome-do-bug.

Abra um Pull Request para a develop e solicite Code Review.

👥 Autores e Time

Jullio - DevSecOps & Lead Architect
Thales - Back-end Core & Engine
Juliano - Back-end Integrations & AI
Ryan - Front-end Architecture
Allan - Front-end UI/UX
João Marcelo - QA & Quality Engineering