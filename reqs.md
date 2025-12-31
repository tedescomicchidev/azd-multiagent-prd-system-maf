# Confidential Computing + Federated Learning + Governance on Azure

Below is a **combined "Confidential Computing + Federated Learning +
Governance" architecture on Azure** for **multi-org agentic AI with
secure data sharing**, tailored to the risks and primitives discussed in
the article.

------------------------------------------------------------------------

## 1) Target outcomes (what this architecture guarantees)

1.  **Data stays protected in use** during ingestion, embedding,
    retrieval, tool execution, and (where possible) inference using
    **TEEs** (confidential computing).
2.  **Cross-organization learning without centralizing raw data** using
    **Federated Learning (FL)**.
3.  **Enterprise-grade governance**: purpose limitation, access control,
    auditability, policy enforcement, monitoring, and "right to forget"
    controls.

------------------------------------------------------------------------

## 2) Reference architecture (logical components)

### A. Network & identity perimeter (per organization)

-   **VNet + Private Endpoints** for Storage, Key Vault, AI services
    (where supported), Container Registry.
-   **Azure Entra ID** for workforce/service identities, Conditional
    Access, workload identities.
-   **Private DNS** + egress control via Azure Firewall/NVA
    (deny-by-default outbound).

### B. Confidential Agent Runtime (per organization)

Run the "Agentic OS" and sensitive RAG components inside **AKS
Confidential node pools** (AMD SEV-SNP TEEs).

Core workloads (inside confidential nodes):

-   Orchestrator / Supervisor agent (LangGraph / Semantic Kernel / etc.)
-   Tool execution sandbox for high-risk tools (CRM/ERP/KB connectors)
-   RAG ingestion + embedding jobs
-   Retriever service (query → embed → search → context assembly)
-   Optional: Vector DB inside TEE node pool

**Attestation & key release**

-   **Azure Attestation** verifies enclave/node measurements.
-   **Key Vault / Managed HSM** releases keys only after successful
    attestation.

### C. Data plane (per organization)

-   Immutable document sources: **ADLS Gen2 / Blob** (encrypted,
    private).
-   Index artifacts:
    -   Option 1: embeddings + vector index inside confidential AKS.
    -   Option 2: managed vector store outside TEEs with mitigations.

### D. Model / inference layer

**Pattern 1 --- Confidential inference where available**

-   Azure AI Confidential Inferencing (preview / limited models).

**Pattern 2 --- Private model endpoint + confidential prompt assembly**

-   Prompt construction and grounding inside TEEs.
-   Minimal prompt sent to model endpoint over private networking.

### E. Federated Learning plane (cross-organization)

-   Local FL clients train on sensitive data.
-   Encrypted updates sent to aggregator.
-   Secure aggregation + optional differential privacy.
-   Global model published via registry with lineage and policy gates.

### F. Governance, security & compliance layer

-   **Microsoft Purview** for data discovery, lineage, and GenAI
    governance.
-   **Azure Policy** for enforcement (Private Link, CMK, SKU
    restrictions).
-   **Defender for Cloud** for runtime and posture security.
-   **Central audit** via Log Analytics / Sentinel.

------------------------------------------------------------------------

## 3) End-to-end flows

### Flow 1 --- Secure RAG query across organizations

1.  User queries Org A agent.
2.  Agent runs in Org A confidential AKS.
3.  Org A requests retrieval from Org B.
4.  Org B retrieves data inside its confidential AKS.
5.  Org B returns minimized, approved context.
6.  Org A builds final answer and logs decisions.

### Flow 2 --- Federated learning

1.  Each org trains locally.
2.  Encrypted updates sent to aggregator.
3.  Aggregated global model published.
4.  Orgs evaluate and promote under policy.

------------------------------------------------------------------------

## 4) Azure service mapping

-   Confidential computing: AKS Confidential node pools, Azure
    Attestation, Key Vault / Managed HSM
-   Core AI: Azure OpenAI / Azure AI services, Confidential Inferencing
-   Data: ADLS Gen2, Blob, Vector DB
-   FL: Azure ML pipelines and jobs
-   Governance: Microsoft Purview, Azure Policy, Defender for Cloud,
    Sentinel

------------------------------------------------------------------------

## 5) Key design decisions

1.  Plaintext should exist only inside TEEs.
2.  Vector store placement tradeoff (privacy vs scale).
3.  Prefer retrieval-result sharing over data sharing.
4.  Treat unlearning and right-to-forget as first-class requirements.
