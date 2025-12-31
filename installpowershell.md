###################################
# Prerequisites

# Update the list of packages
sudo apt-get update

# Install pre-requisite packages.
sudo apt-get install -y wget apt-transport-https software-properties-common

# Get the version of Ubuntu
source /etc/os-release

# Download the Microsoft repository keys
wget -q https://packages.microsoft.com/config/ubuntu/$VERSION_ID/packages-microsoft-prod.deb

# Register the Microsoft repository keys
sudo dpkg -i packages-microsoft-prod.deb

# Delete the Microsoft repository keys file
rm packages-microsoft-prod.deb

# Update the list of packages after we added packages.microsoft.com
sudo apt-get update

###################################
# Install PowerShell
sudo apt-get install -y powershell

# Start PowerShell
pwsh

## -------------------------------------------------
curl -sL https://aka.ms/InstallAzureCLIDeb | sudo bash

pip show agent-framework agent-framework-azure-ai
pip install -U agent-framework agent-framework-azure-ai

--output-file out/prd.json

python scripts/verify_agent.py --feature-idea-md ./inputs/architecture_description.md


## -------------------------------------------------
ARCHITECTURE_DESCRIPTION = """
Below is a combined “Confidential Computing + Federated Learning + Governance” architecture on Azure
for multi-org agentic AI with secure data sharing.

---

## 1) Target outcomes (what this architecture guarantees)

1. Data stays protected in use during ingestion, embedding, retrieval, tool execution, and (where possible) inference using TEEs (confidential computing).
2. Cross-organization learning without centralizing raw data using Federated Learning (FL).
3. Enterprise-grade governance: purpose limitation, access control, auditability, policy enforcement, monitoring, and right-to-forget controls.

---

## 2) Reference architecture (logical components)

### A. Network & identity perimeter (per organization)

- VNet + Private Endpoints for Storage, Key Vault, AI services (where supported), Container Registry.
- Azure Entra ID for workforce/service identities, Conditional Access, workload identities.
- Private DNS + egress control via Azure Firewall/NVA (deny-by-default outbound).

### B. Confidential Agent Runtime (per organization)

Run the Agentic OS and sensitive RAG components inside AKS Confidential node pools (AMD SEV-SNP TEEs).

Core workloads:
- Orchestrator / Supervisor agent
- Tool execution sandbox
- RAG ingestion + embedding jobs
- Retriever service
- Optional vector DB inside TEE

Attestation & key release:
- Azure Attestation verifies enclave measurements.
- Key Vault / Managed HSM releases keys only after successful attestation.

### C. Data plane (per organization)

- Immutable document sources: ADLS Gen2 / Blob (encrypted, private).
- Index artifacts:
  - Option 1: embeddings + vector index inside confidential AKS.
  - Option 2: managed vector store outside TEEs with mitigations.

### D. Model / inference layer

Pattern 1 — Confidential inference where available  
Pattern 2 — Private model endpoint + confidential prompt assembly

### E. Federated Learning plane (cross-organization)

- Local FL clients train on sensitive data.
- Encrypted updates sent to aggregator.
- Secure aggregation and optional differential privacy.
- Global model published with lineage and policy gates.

### F. Governance, security & compliance

- Microsoft Purview
- Azure Policy
- Defender for Cloud
- Central audit via Log Analytics / Sentinel

---

## 3) End-to-end flows

Flow 1 — Secure RAG query across organizations  
Flow 2 — Federated learning

---

## 4) Azure service mapping

- AKS Confidential node pools
- Azure Attestation
- Key Vault / Managed HSM
- Azure OpenAI / Azure AI services
- Azure ML
- Microsoft Purview, Defender, Sentinel

---

## 5) Key design decisions

1. Plaintext exists only inside TEEs.
2. Vector store placement tradeoff.
3. Prefer retrieval-result sharing.
4. Treat unlearning as first-class.
"""


