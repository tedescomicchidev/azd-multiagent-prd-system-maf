# Building a Multi-Agent PRD Workflow with AZD, Microsoft Agent Framework, and Microsoft Foundry

This repository provides a complete, end-to-end example of how to design, build, and deploy a production-ready PRD workflow on Azure, leveraging the Microsoft Agent Framework and Microsoft Foundry resources.

We will build a product requirements document (PRD) pipeline in which a sequential workflow runs three agents: Product Researcher, Product Strategy, and Technical Architect. Together they produce a structured PRD with research, strategy, and architectural guidance.

This repository automates the scenario by provisioning Azure infrastructure with Bicep, deploying a FastAPI container to Azure Container Apps, and wiring the app to a multi-agent workflow in Microsoft Foundry.

The solution coordinates three agents:

| Agent | Role | Output |
|-------|------|--------|
| Product Researcher | Market & user research, personas, competitive analysis | Structured research output with PRD outline |
| Product Strategy | Vision, goals/non-goals, success metrics | Product strategy decisions |
| Technical Architect | Feasibility, approach, milestones, risks | Architecture recommendations and effort |

The repository adds operational conveniences that go beyond the lab handout, including automated infrastructure deployment, repeatable agent bootstrapping, rate-limit-aware verification, and a consolidated test harness with readable JSON traces for demos.

---

## Architecture Overview

```
Azure Resource Group (azd-multiagent)
├─ Azure Container Apps Environment
│  └─ Container App (FastAPI PRD API)
│     ├─ Managed Identity
│     └─ Azure Container Registry image
├─ Azure Container Registry
└─ Microsoft Foundry Project
	├─ GPT-4o model deployment (capacity configurable)
	├─ Project connection (AAD)
	└─ Multi-agent workflow (Researcher → Strategy → Technical Architect)
```

**Infrastructure as Code**: `infra/main.bicep` composes individual modules for the container app (`infra/modules/containerapp.bicep`), Microsoft Foundry resources (`infra/modules/foundry.bicep`), and container registry (`infra/modules/acr.bicep`).

**Application**: `src/api/app.py` hosts FastAPI endpoints that expose the PRD capability. Environment variables emitted by the Bicep deployment provide the AI project endpoint and agent IDs.

**Automation scripts**:

- `scripts/bootstrap_agents.py` – creates or refreshes the PRD agents with the Microsoft Agent Framework and persists their IDs to the current `azd` environment.
- `scripts/verify_agent.py` – verifies a single PRD workflow run and optionally prints the trace.
- `scripts/test_prd_workflow.py` – runs the three agents in sequence; automatically loads environment values from `.azure/<env>/.env` and emits normalized JSON blocks for each participant.

---

## Repository Layout

```
├─ azure.yaml                  # azd template metadata
├─ infra/
│  ├─ main.bicep               # top-level infrastructure composition
│  └─ modules/
│     ├─ containerapp.bicep    # Azure Container Apps + env vars
│     ├─ foundry.bicep         # Microsoft Foundry project + GPT-4o deployment
│     └─ acr.bicep             # Azure Container Registry
├─ src/
│  └─ api/
│     ├─ app.py                # FastAPI app exposing PRD API
│     ├─ prd_workflow.py       # Sequential PRD workflow
│     ├─ search_tool.py        # Optional Google Custom Search integration
│     ├─ dockerfile            # Container image definition
│     └─ requirements.txt      # API dependencies
└─ scripts/
	├─ bootstrap_agents.py      # Creates the three PRD agents and stores IDs
	├─ verify_agent.py          # Checks PRD workflow runs with retries
	└─ test_prd_workflow.py     # Aggregated PRD workflow test harness
```

---

## Prerequisites

1. **Azure subscription** with access to GPT-4o capacity in Microsoft Foundry.
2. **Azure Developer CLI (azd)** v1.9+ and the Azure CLI (`az`) installed locally.
3. **Python 3.12+** with `pip` available on your development machine.
4. **Docker** (builds the API image if you make code changes).
5. Sign in with `az login` before running any deployment commands.

> ℹ️ The lab document recommends manually creating the project and agents. This repository automates those steps; no Cloud Shell edits are necessary.

---

## Quick Start

### 1. Provision Infrastructure

From the repository root:

```pwsh
azd up
```

This command:

- Creates the Azure resource group and supporting resources.
- Deploys the FastAPI container image to Azure Container Apps.
- Provisions a Microsoft Foundry project, connection, and GPT-4o deployment (default capacity = 2, adjustable via `modelSkuCapacity`).

At the end of the run, `azd` populates `.azure/<env>/.env` with output values including:

- `AIFOUNDRY_PROJECT_ENDPOINT`
- `projectEndpoint` (camelCase alias)
- `AZURE_CONTAINER_REGISTRY_ENDPOINT`
- Container app URL (`apiUrl`)

### 2. Bootstrap the Agents

```pwsh
python scripts/bootstrap_agents.py
```

This script waits for DNS propagation, creates the **product researcher**, **product strategy**, and **technical architect** agents, and saves their IDs to the current `azd` environment:

- `PRD_RESEARCHER_AGENT_ID`
- `PRD_STRATEGY_AGENT_ID`
- `PRD_TECH_ARCH_AGENT_ID`

It also prints an environment snapshot and, when run with `--feature-idea`, writes the aggregated PRD response to `warmup.json` for easy sharing.

### 3. Test the PRD Workflow

```pwsh
python scripts/test_prd_workflow.py --feature-idea "Add dark mode to our mobile app"
```

`test_prd_workflow.py` automatically loads `.azure/<env>/.env`, maps the `projectEndpoint` alias if necessary, and prints the response from each agent using the Microsoft Agent Framework runtime. Output is rendered as compact JSON blocks so you can narrate each participant’s decision without additional formatting. Pass `--env-file` to point at a different environment snapshot.

Example output:

```
[product-researcher]
{ "personas": ["Nighttime power users", ...], ... }

[product-strategy]
{ "vision": "...", "goals": ["..."], ... }

[technical-architect]
{ "technical_feasibility": "...", "milestones": ["..."], ... }
```

### 4. (Optional) Verify Workflow Execution

To test a single workflow run with granular retry controls:

```pwsh
python scripts/verify_agent.py `
  --feature-idea "Add dark mode to our mobile app" `
  --show-trace
```

Use this command when debugging rate-limit behaviour or inspecting transcripts in detail.

---

## Search Tool (Optional)

The Product Researcher can optionally call `SearchTool`, which integrates with Google Custom Search JSON API.

Set these environment variables to enable it:

- `GOOGLE_SEARCH_API_KEY`
- `GOOGLE_SEARCH_ENGINE_ID`

If these are not configured, the tool returns a deterministic `search_not_configured` response and the workflow continues normally.

---

## Deploying Updates

1. **Modify application code** (e.g., update `src/api/app.py`).
2. Rebuild and redeploy:

	```pwsh
	azd deploy
	```

3. Re-run `python scripts/bootstrap_agents.py` whenever you change instructions or tear down the AI project resources.

---

## Cleanup

To remove all resources and avoid charges:

```pwsh
azd down
```
