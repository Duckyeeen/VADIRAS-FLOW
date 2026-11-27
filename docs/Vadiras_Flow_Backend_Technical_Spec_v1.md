# VADIRAS FLOW — BACKEND TECHNICAL SPECIFICATION

**Version:** 1.0  
**Status:** Baseline specification for prototype/demo  
**Target:** Existing backend repository; inspect and extend, do not replace blindly  
**Primary stack:** Python, FastAPI, Temporal, PostgreSQL, pgvector, Docker Compose  
**Frontend contract:** React + TypeScript; workflow canvas may use React Flow  

---

## 0. Executive summary

Vadiras Flow is an AI-assisted enterprise workflow orchestration platform. It receives internal and external business requests, understands and classifies them, proposes workflows, checks permissions and risk, coordinates specialized AI agents and human workers, executes approved actions through tools/connectors, monitors progress and SLA, verifies results using evidence, and stores audit and reusable knowledge for future requests.

The prototype must demonstrate one complete and observable lifecycle across five request categories:

1. Incident / Bug
2. Change Request
3. Service Request
4. Customer Onboarding
5. Internal Task / Department Coordination

The demo models one organization with six departments: Support, Engineering, DevOps, Security, Product, and Management. Both employee and external customer requesters are supported. The data model must be industry-extensible, but the prototype does not need full production-grade workflows or analytics for every industry.

### Product principle

**Think to understand. Design to plan. Control to authorize. Act to execute. Verify to prove. Learn to improve.**

### Non-negotiable trust boundaries

- LLM output is untrusted input to backend systems.
- LLMs may propose actions and plans; deterministic backend services authorize and execute them.
- The policy/permission layer is independent of the AI agent layer.
- The workflow runtime executes only a validated, versioned workflow definition.
- A successful tool/API response is not automatically proof that the business request is resolved.
- High-risk or scope-expanding changes require an authorized human approval.
- External content (issue text, comments, attachments, webhook payloads, retrieved documents and memory) is untrusted data, never privileged instructions.

---

## 1. Confirmed product and technical decisions

| Area | Confirmed choice | Implementation interpretation |
|---|---|---|
| Product scope | General enterprise | Domain-neutral request, workflow, identity, policy and execution core |
| Demo request types | Incident, Change, Service, Onboarding, Internal | Five seed request categories and example workflows |
| Organization count | One organization | Single-organization demo with `organization_id` throughout business data; keep tenant-ready design |
| Requesters | Internal and external | Employee and customer-contact identities, with strict own-request access for customers |
| Industry support | Extensible | Domain packs/configuration; do not hard-code industry-specific assumptions in core entities |
| Backend | Python + FastAPI | Async API, Pydantic contracts, SQLAlchemy 2, Alembic |
| Workflow runtime | Temporal | Durable long-running workflows; external I/O and model calls happen in Activities |
| AI topology | Swarm | Bounded, supervisor-managed specialist swarm; no unrestricted peer-to-peer tool access |
| Vector memory | pgvector | Store embeddings in PostgreSQL; metadata and authorization filters always apply |
| GitHub integration | GitHub App | Installation-scoped, least-privilege integration; webhooks plus reconciliation polling |
| App authentication | JWT | Short-lived access token, secure password hashing, explicit authorization checks |
| Approval | Risk-based | Approval policy by action, resource scope, requester/actor rights, impact and risk |
| Event integration | Webhook + polling | Webhook-first, polling/reconciliation as fallback |
| Deployment | Docker Compose | Local demo environment, reproducible startup and seeded demo data |
| Frontend | React | Backend publishes stable API contracts and real-time execution events |
| Analytics | SLA, automation, cost, agent, audit, department, industry | Common metric dimensions; demo data for one organization and selected workflows |
| Adaptation | Bounded adaptive workflow | Safe retry/reassign/wait/replan within explicit limits; approval for scope or risk escalation |
| Existing repository | Yes | Audit repository first; preserve working architecture and conventions |
| Delivery goal | End-to-end demo | Prioritize observable real lifecycle over production-scale breadth |
| LLM vendor | Undecided | Provider abstraction, Mock provider, configuration-driven real provider; no vendor lock-in |

### Important interpretation of “swarm”

The swarm is a controlled collaboration topology, not an uncontrolled autonomous society. A Supervisor/Orchestrator delegates bounded analysis tasks to specialist agents, collects structured results, resolves conflicts and creates a proposal. All tool execution goes through a centralized Tool Broker and Policy Enforcement layer. Agents do not grant permissions, modify policy, create unapproved credentials, or directly bypass the workflow runtime.

---

## 2. Demo scope and acceptance journeys

### 2.1 Personas

- **Requester (employee):** submits internal work and tracks their requests.
- **Requester (customer contact):** submits customer-facing service/onboarding requests and sees only their own permitted requests.
- **Worker:** accepts assigned human tasks and records progress/evidence.
- **Department manager:** reviews workload, approves actions in their authorized scope and escalates exceptions.
- **Security / auditor:** reviews policies, approvals, execution evidence and audit history.
- **Organization admin:** manages users, departments, roles, connectors and policy configuration.
- **AI agent identity:** a non-human service identity with explicitly declared capabilities and limited scopes.

### 2.2 Required end-to-end journeys

**Journey A — Incident / Bug**
1. Employee or customer submits a bug/incident request.
2. Intake validates and stores the original request.
3. Intelligence classifies type, priority, impacted service, missing information and likely department.
4. Supervisor dispatches parallel specialist analysis (technical, support/operations, security/risk when relevant).
5. Planner proposes a workflow using allowed node types and available connectors.
6. Validator checks graph integrity, permissions, risk, resource limits and required inputs.
7. Requester/manager approval is requested only when policy requires it.
8. Workflow creates or links a GitHub Issue, assigns the responsible team, and waits for updates.
9. GitHub webhook or reconciliation polling updates the workflow state.
10. Verification checks the external issue/resource state and required evidence.
11. Request is marked verified, partially verified, failed or unverified; all decisions are auditable.

**Journey B — Change Request**
1. Request describes a change and target environment/resource.
2. AI identifies impact, dependencies, risks and missing change details.
3. Workflow includes impact assessment, Security/DevOps review and approval gate.
4. No production deployment or privileged configuration change occurs in the initial demo. Use a simulated/Mock action unless an explicitly scoped connector and policy are later approved.
5. Approval, rejection, timeout and rework paths are visible.

**Journey C — Service Request**
1. Request is routed to Support or another department.
2. AI extracts service category, requester, due date and required data.
3. Workflow creates human tasks and/or a permitted GitHub issue.
4. SLA timer and reminders are tracked.
5. Completion requires task evidence and requester/worker confirmation when configured.

**Journey D — Customer Onboarding**
1. Customer contact submits onboarding request.
2. Planner creates a multi-department checklist (Support, Product, Engineering, Security or Management according to policy).
3. Human tasks, approval gates and dependency edges are shown.
4. Customer-facing information is separated from internal notes.
5. Completion is verified against required onboarding checklist items.

**Journey E — Internal Task / Department Coordination**
1. Employee submits an internal cross-department request.
2. AI identifies relevant departments and decomposes the request into tasks.
3. Human/agent tasks can run in parallel where dependencies allow.
4. Progress, blockers and SLA are visible.
5. Final verification checks all required subtasks.

### 2.3 In-scope for demo

- Organization-aware identity and authorization.
- Employee and external requester roles.
- Request intake, normalized classification and structured analysis.
- Bounded multi-agent analysis and planning.
- Workflow graph generation, editing contract, validation and versioning.
- Temporal execution with pause, resume, cancellation, signals/events, timeout and retry.
- Risk-based approvals and least-privilege policy enforcement.
- GitHub App connector for Issue read/create/update/assign/comment as explicitly allowed.
- GitHub webhooks and fallback reconciliation polling.
- Human task representation and state transitions.
- Evidence-based verification.
- Execution event stream, audit history, SLA/cost/automation/agent/department metrics.
- Basic memory retrieval with pgvector and safe metadata filtering.
- Mock LLM and Mock Connector paths for deterministic testing.
- Docker Compose startup, migrations, demo seed data and automated tests.

### 2.4 Explicitly out of scope for initial demo

- Fully autonomous production deployments or infrastructure changes.
- Arbitrary code execution generated by an LLM.
- An unrestricted agent-to-agent network with shared credentials.
- Full ERP/CRM/Jira/Slack/email integration suite.
- Production SSO/SAML and enterprise identity federation unless already present in the repository.
- Full multi-tenant SaaS billing and tenant provisioning.
- Autonomous policy editing or permission escalation.
- Self-modifying models or automatic model fine-tuning.
- Industry-specific predictive analytics across all industries.

---

## 3. Logical architecture

### 3.1 Component layers

1. **API & Identity Layer** — FastAPI routes, authentication, request context, RBAC/ABAC, rate limiting.
2. **Business Domain Layer** — requests, departments, human tasks, workflows, approvals, connectors, metrics.
3. **AI Intelligence Layer** — provider adapter, request understanding, bounded swarm supervisor, planning, risk analysis, retrieval and verification assistance.
4. **Governance Layer** — policy evaluation, permission resolution, resource/action scope, risk score, approval manager, budget guard and execution guard.
5. **Workflow Runtime Layer** — Temporal workflows/workers, node interpreter, scheduling, retries, timers, signals, event handling and adaptive decisions.
6. **Integration Layer** — GitHub App, webhook inbox, polling/reconciliation, connector abstraction and Mock Connector.
7. **Evidence & Observability Layer** — execution events, audit logs, evidence, SLA, costs, traces and metrics.
8. **Memory Layer** — versioned, permission-filtered knowledge and outcome memories with pgvector embeddings.

### 3.2 Suggested deployable processes

Keep one repository and a modular-monolith codebase initially. Run separate processes/containers where lifecycle or workload requires it:

- `api`: FastAPI application.
- `temporal-worker`: Temporal workflow and activity workers.
- `outbox-worker`: dispatches transactional outbox messages and scheduled reconciliation work.
- `scheduler` (optional): recurring SLA checks and GitHub polling jobs if not implemented as Temporal schedules/workflows.
- `postgres`: PostgreSQL with pgvector extension.
- `temporal`: self-hosted Temporal service for local demo.
- `temporal-ui` (optional): inspect workflow history during development/demo.

Do not introduce Redis, Kafka, Kubernetes or multiple independently deployed microservices unless the existing repository already uses them or a demonstrated requirement justifies them. Temporal and PostgreSQL are the baseline durable coordination/storage components.

### 3.3 Architecture rule

Domain modules must not import FastAPI route modules. AI modules must not directly mutate domain tables or call external systems. Connector operations must pass through the Tool Broker and Policy Enforcement. Temporal workflow definitions must remain deterministic; database/network/LLM interactions belong in Activities.

---

## 4. Backend technology baseline

| Concern | Baseline | Notes |
|---|---|---|
| Language | Python | Follow repository-supported version; pin dependencies |
| API | FastAPI | Async endpoints and OpenAPI |
| Validation | Pydantic | Strict request/response and LLM schemas |
| ORM | SQLAlchemy 2.x | Async session if repository uses async database I/O |
| Migrations | Alembic | Versioned forward migrations; avoid manual schema drift |
| Database | PostgreSQL | JSONB for graph/config metadata; relational tables for lifecycle records |
| Vector extension | pgvector | Embeddings stored with tenant/org and access metadata |
| Workflow runtime | Temporal Python SDK | Durable long-running orchestration |
| Auth | JWT + password hashing | Use a maintained JWT library and Argon2id-capable password hashing where compatible |
| GitHub | GitHub App | Minimum required permissions; installation token handling |
| Real-time API | SSE first | WebSocket only if existing architecture requires bidirectional interaction |
| Testing | pytest | Unit, integration, contract, security and end-to-end tests |
| Packaging | Existing repository tool | Preserve Poetry/uv/pip-tools/etc.; do not replace without reason |
| Local environment | Docker Compose | Health checks, persistent volumes, env-file example |

LLM provider must be configured through a provider interface. The initial implementation must include:

- `LLMProvider` protocol/interface.
- `MockLLMProvider` with deterministic fixtures.
- At least one configurable real provider adapter only if credentials/provider are available.
- Model capability/config registry (model id, context limit if known, supported structured output/tool calling, timeout, retry policy, price configuration if known).
- Structured JSON output validation and bounded repair attempts.
- Usage/cost metadata capture where provider exposes it.

Do not select or hard-code a vendor. Do not embed API keys in source, frontend bundles, Docker image or database plaintext.

---

## 5. Bounded multi-agent swarm specification

### 5.1 Roles

| Agent | Responsibility | Default tool access |
|---|---|---|
| Supervisor / Orchestrator | Delegates analysis, collects outputs, resolves disagreement, produces plan proposal | No direct external side effects |
| Request Analyst | Intent, category, entities, priority, missing information | Read-only context retrieval |
| Technical Analyst | Technical dependencies, likely cause, task breakdown | Read-only GitHub/knowledge access when allowed |
| Operations Analyst | Department, workload, SLA, operational dependencies | Read-only business context |
| Security / Risk Analyst | Data sensitivity, impact, attack surface, risk flags | Read-only policy metadata; cannot change policy |
| Workflow Planner | Generates candidate workflow graphs | No execution tools |
| Critic / Reviewer | Checks assumptions, gaps, contradictions and unsafe steps | Read-only candidate workflow/context |
| Executor Worker | Runs one specifically authorized action through Tool Broker | Only the specific capability/action granted for that task |
| Verification Worker | Collects/checks evidence and evaluates completion criteria | Read-only resource inspection; no self-approval |

Roles can share the same underlying model. They are logical agents with distinct instructions, schemas and capability boundaries. Avoid deploying separate model services for each role in the prototype.

### 5.2 Collaboration protocol

1. Supervisor creates an immutable `analysis_job_id` and context snapshot.
2. Supervisor dispatches bounded specialist tasks in parallel when independent.
3. Each specialist returns typed JSON: `findings`, `assumptions`, `risks`, `missing_information`, `confidence`, `evidence_refs`.
4. Supervisor detects contradictions and can request one additional review round.
5. Critic checks the consolidated plan. Maximum debate/review rounds are configurable; default maximum is 2.
6. Supervisor emits a structured proposal with rationale summary and provenance. Do not store or expose hidden chain-of-thought. Store concise decision rationale, evidence references, assumptions and scores.
7. Backend validators and Policy Engine independently validate the proposal.
8. Only the runtime invokes permitted executor activities after workflow validation and required approval.

### 5.3 Swarm constraints

- Maximum concurrent specialist tasks per analysis: configurable; demo default 4.
- Maximum review/debate rounds: 2.
- Maximum agent task duration and token/cost budget: configurable.
- No direct agent-to-agent network calls outside the orchestrator-mediated task interface.
- No agent can grant permissions, edit policies, mint connector credentials or approve its own action.
- Every tool invocation carries `organization_id`, `actor_id`, `agent_id`, `request_id`, `workflow_run_id`, `node_run_id`, capability, resource scope, idempotency key and policy decision reference.
- Any tool call not in the allowlist is rejected by code outside the LLM.
- Treat all model output as untrusted and validate against Pydantic schemas.

### 5.4 Conflict resolution

Do not use simple majority vote as the only decision mechanism. Use deterministic aggregation:

- Hard blockers from policy/security validation override agent preference.
- Missing mandatory data causes `NEEDS_INFORMATION`.
- Conflicting factual claims require evidence or human review.
- Candidate plans are scored only after hard constraints pass.
- If no candidate passes validation, return `NO_SAFE_PLAN` and request human intervention.

---

## 6. Request intelligence and workflow algorithms

### 6.1 Request intake pipeline

`Raw Input -> Normalization -> Intent Classification -> Entity Extraction -> Completeness Check -> Priority/SLA Suggestion -> Risk Signals -> Structured Analysis`

Store original input separately from AI-generated analysis. Analysis must be versioned and linked to model/provider/prompt version.

Required normalized request fields:

- `id`, `organization_id`, `request_number`.
- `title`, `description`, `request_type`.
- `requester_id`, `requester_kind` (employee/customer contact), optional customer/account reference.
- `source` (web, API, email later, integration, manual).
- `status`, `priority`, `impact`, `urgency`.
- `department_id` or proposed departments.
- `due_at`, `sla_policy_id`, optional service/product/resource references.
- `metadata` JSONB with schema validation.
- timestamps and created/updated actor references.

`request_type` must be extensible. Seed values: `INCIDENT`, `CHANGE`, `SERVICE_REQUEST`, `ONBOARDING`, `INTERNAL_TASK`.

### 6.2 Classification algorithm

Use LLM structured output for semantic interpretation plus deterministic validation/rules. The AI may suggest priority and department; backend policies may override or flag it. Confidence is not permission. Low confidence, ambiguous request type or missing mandatory fields should create a clarification task rather than fabricate data.

Output schema should include:

- request type and subtype;
- intent summary;
- entities and affected resources;
- proposed department(s);
- priority/impact/urgency with explanation summary;
- missing required fields/questions;
- possible subtasks;
- risk indicators;
- confidence and evidence references;
- model/prompt version.

### 6.3 Workflow DSL

Persist a versioned JSON graph, not executable Python/shell or raw prompt text.

Top-level fields:

- `workflow_id`, `version`, `name`, `description`, `domain_pack`, `request_type`.
- `input_schema`, `output_schema`.
- `nodes[]`, `edges[]`.
- `limits` (node count, max duration, retries, max parallelism, estimated cost ceiling, replan count).
- `policy_requirements` and `approval_requirements` references.
- `created_by`, `created_from_analysis_id`, timestamps.

Node fields:

- `id`, `type`, `name`, `description`.
- `config` validated against a node-type-specific schema.
- `input_mapping`, `output_schema`, `timeout_seconds`, `retry_policy`.
- optional `required_capabilities`, `resource_scope`, `risk_class`, `approval_gate`.

Edge fields:

- `id`, `source`, `target`, optional `condition`, optional `label`.

Initial allowed node types:

`TRIGGER`, `CLASSIFY`, `AI_ANALYSIS`, `CONDITION`, `AGENT_TASK`, `HUMAN_TASK`, `APPROVAL`, `CONNECTOR_ACTION`, `WAIT_EVENT`, `NOTIFICATION`, `VERIFICATION`, `END`.

Node types must be registered in a backend Node Registry. Reject unknown node types. Do not run arbitrary generated code. Validate acyclicity unless a future explicit bounded-loop node is introduced. Conditions must use a safe, declarative expression format; do not use `eval`.

### 6.4 Candidate workflow planning and scoring

Generate 1–3 candidate workflows where practical. First apply hard constraints:

- allowed node types only;
- graph structurally valid;
- required input present or represented by a human clarification step;
- every action has an available connector/capability;
- policy and permission constraints satisfied or explicitly gated by approval;
- resource, node, runtime, retry, concurrency and cost limits respected;
- verification criteria exist for material outcomes.

Then score feasible candidates, for example:

`Score = wC*Coverage + wF*Feasibility + wE*Efficiency - wR*Risk - wK*Cost - wT*ExpectedTime`

Weights must be configurable by organization/domain/request class and normalized. Hard security constraints must never be traded away for a high score. Scores are ranking aids, not autonomous authorization.

### 6.5 Workflow validation stages

- Structural validation: schema, unique node IDs, valid edges, reachable end, cycle rules.
- Dataflow validation: required inputs available, output-to-input mappings compatible.
- Capability validation: required capability exists and is enabled.
- Permission validation: actor/agent/connector has resource/action scope.
- Policy and risk validation: approval or hard block.
- Resource validation: node count, duration, retry, parallelism, LLM budget, connector rate limits.
- Verification validation: final success criteria and required evidence sources exist.

States: `DRAFT`, `VALIDATING`, `VALID`, `INVALID`, `AWAITING_APPROVAL`, `APPROVED`, `PUBLISHED`, `ARCHIVED`.

### 6.6 Bounded adaptive workflow algorithm

Adaptation decisions are restricted to:

- retry a transient failure within policy;
- wait for an external event;
- reassign a task to another authorized agent/worker;
- ask requester/worker for missing information;
- add a pre-approved safe node/template;
- create a new workflow proposal/version for approval.

A running workflow version is immutable. Replanning creates a `replan_proposal` or new version and records the parent version. Completed nodes and evidence remain immutable. Any change that expands data access, permission, target resource, irreversible action or risk class pauses execution and requires fresh validation and approval.

Defaults for demo (configurable): maximum 2 replan attempts per run; maximum 3 retries per retryable activity; finite per-node and per-run timeouts; maximum 4 concurrent agent analyses; bounded connector request rate. Never retry a non-idempotent side effect without idempotency protection or reconciliation.

---

## 7. Governance, permissions and approval

### 7.1 Authorization model

Use RBAC plus resource-scoped checks (ABAC-style conditions). Do not rely on department labels alone.

Permission evaluation must consider:

- organization membership;
- user/agent identity and active status;
- role and explicit permissions;
- department/team membership;
- resource ownership/scope;
- connector installation and repository scope;
- action type (read/create/update/assign/comment/close/deploy/etc.);
- request relationship and requester/approver rights;
- current policy version and runtime context.

Employee and customer-contact identities must be distinguished. A customer contact may view only requests explicitly associated with that contact/account and customer-visible fields. Internal notes, risk analysis, security findings and internal tasks must never be exposed through customer APIs by default.

### 7.2 Agent identity and delegation

An agent is a service principal, not a human user. It has:

- `agent_id`, `organization_id`, status;
- registered capabilities;
- allowed tool/action list;
- allowed resource scopes;
- maximum cost/concurrency/time limits;
- owner/maintainer reference;
- versioned policy binding.

Never automatically inherit every requester permission. A task-specific grant must be created or resolved by policy. Prefer delegated, short-lived, narrow grants. Approval cannot grant authority beyond the approver's own allowed scope or organization policy.

### 7.3 Risk and approval

Start with deterministic risk bands and configurable policy rules. A possible scoring feature set:

- impact/severity;
- probability/uncertainty;
- data sensitivity;
- scope breadth;
- privilege level;
- external/customer impact;
- reversibility;
- production/financial/security implications.

A simple `Impact x Likelihood` base can be augmented by these factors. Do not treat a numeric score as the sole safety mechanism.

Suggested policy mapping:

- **LOW:** auto-execute if all permission and budget checks pass.
- **MEDIUM:** additional validation, optional team lead approval based on policy.
- **HIGH:** explicit authorized approval required.
- **CRITICAL:** block in demo or require designated approval and a separately configured safe execution path.

Approval record must bind to the exact proposed action, node, parameters hash, workflow version, resource scope, policy version and expiry. If parameters/version/scope change, approval is invalidated. Record approver identity, decision, timestamp, rationale and delegated authority check.

### 7.4 Execution guard

Evaluate policy immediately before every side-effecting tool call, not only at workflow start. Re-check when credentials, resource scope, actor, parameters, approval state or policy version changes.

---

## 8. Temporal workflow runtime

### 8.1 Responsibilities

Temporal owns durable orchestration of long-running request workflows and related waits/retries. PostgreSQL remains the system-of-record for business entities, policy, evidence, metrics and audit records. Temporal history is operational workflow history, not a replacement for domain/audit tables.

### 8.2 Determinism rule

Temporal Workflow code must be deterministic. Do not call external APIs, database sessions, LLM providers, filesystem, random/time APIs outside Temporal-supported deterministic mechanisms directly from Workflow code. Put I/O and nondeterministic work inside Activities. Use signals/updates for approvals and external events; use Queries for read-only workflow status where useful.

### 8.3 Runtime building blocks

- `RequestOrchestrationWorkflow`
- `WorkflowExecutionWorkflow` (or one parent workflow with child workflow per execution design, as repository structure warrants)
- `AgentAnalysisWorkflow` (optional child workflow)
- `HumanTaskWaitWorkflow` or signal/timer state in parent workflow
- Activities for DB writes, LLM calls, policy evaluation, connector actions, webhook reconciliation, verification, evidence and audit.

Avoid making the runtime excessively granular. A single workflow run should coordinate a validated DAG and schedule node activities according to dependencies/parallelism.

### 8.4 Node runtime

- Resolve ready nodes from graph dependencies.
- Check current run state and cancellation.
- Ask Policy Engine before side-effecting nodes.
- If approval required, record approval request and wait on signal/update with timeout.
- Execute activity using idempotency key.
- Persist node state, result summary and evidence references.
- Publish execution events.
- On failure, classify transient/permanent/permission/business failure; retry only when policy says safe.
- On external event, correlate to run/node/resource and resume relevant wait.
- At finalization, invoke Verification Engine and set final request/run state.

### 8.5 State model

Workflow run states:

`QUEUED`, `RUNNING`, `WAITING_APPROVAL`, `WAITING_EVENT`, `PAUSED`, `REPLANNING`, `COMPLETED`, `PARTIALLY_COMPLETED`, `FAILED`, `CANCELLED`, `TIMED_OUT`.

Node run states:

`PENDING`, `READY`, `RUNNING`, `WAITING_APPROVAL`, `WAITING_EVENT`, `RETRYING`, `COMPLETED`, `FAILED`, `SKIPPED`, `CANCELLED`, `BLOCKED`.

Request final states should distinguish business outcome from runtime state, including `VERIFIED`, `PARTIALLY_VERIFIED`, `UNVERIFIED`, `REJECTED`, `CANCELLED` and `OPEN`/`IN_PROGRESS`.

### 8.6 Idempotency and side effects

Every activity that creates/updates an external resource must accept an idempotency key and persist an operation record. On retry, first reconcile whether the external action already succeeded. Do not assume Temporal activity retry makes an external side effect exactly-once.

### 8.7 Recovery and operational controls

Test API restart, worker restart, Temporal service restart (where supported by local stack), activity timeout, duplicate start request, cancellation during wait, and resumption after approval/webhook.

---

## 9. Connectors and GitHub App integration

### 9.1 Connector abstraction

A connector exposes registered capabilities rather than arbitrary URL/request execution. Minimum interface:

- `get_capabilities()`
- `validate_connection()`
- `get_resource()`
- `execute_action(action, validated_payload, execution_context)`
- `verify_result(action, expected_state, evidence_context)`
- `health_check()`

Every action schema must define input validation, required GitHub permission, resource scope, side-effect class, idempotency support, expected result and verification method.

### 9.2 GitHub App minimum scope

Start with the minimum required permissions:

- Repository metadata: read.
- Issues: read/write only if demo needs creating/updating/assigning/commenting on Issues.
- Subscribe only to required events, initially `issues` and optionally `issue_comment`.
- Do not request Contents, Administration, Actions, Checks, Deployments or organization permissions unless a clearly defined demo capability requires them.

Use GitHub App installation-scoped tokens. Cache only in memory or a secure short-lived token cache; refresh before expiry and never expose tokens to frontend or agent prompt. Allow-list repositories per connector installation. Installation tokens expire; do not assume a fixed token string format.

### 9.3 Webhook security and processing

- Verify `X-Hub-Signature-256` using HMAC-SHA256 over the raw request body and constant-time comparison.
- Require and persist delivery ID for deduplication.
- Store a minimal webhook inbox record before async processing.
- Validate event type, installation ID, repository ID and allowed resource scope.
- Treat payload contents as untrusted data.
- Acknowledge quickly after durable receipt; process asynchronously.
- Make handlers idempotent.

### 9.4 Polling/reconciliation fallback

Use webhooks for low-latency updates. Polling is a reconciliation fallback for missed events, expired webhook delivery windows, or demo environments where inbound webhooks cannot reach local development. Use backoff, rate-limit awareness, per-installation/repository cursors and last-synced timestamps. Do not poll aggressively.

### 9.5 Mock connector

Provide a local mock GitHub-compatible connector for deterministic tests and demo walkthroughs. It must support configurable success, transient failure, permanent failure, delayed update, duplicate webhook and verification mismatch scenarios.

---

## 10. Verification, evidence, audit and observability

### 10.1 Verification result

Use four explicit outcomes:

- `VERIFIED`: all configured acceptance criteria are supported by sufficient evidence.
- `PARTIALLY_VERIFIED`: a subset is proven; remaining requirements are incomplete.
- `FAILED`: evidence contradicts expected result or required action failed.
- `UNVERIFIED`: insufficient or unavailable evidence.

Do not equate `API 2xx`, agent `success=true`, issue creation or node completion with business resolution.

### 10.2 Verification contract

Each material node/workflow has:

- expected postcondition;
- evidence source(s);
- evaluator type (deterministic rule first; LLM-assisted interpretation only as supplementary);
- evidence freshness requirement;
- required human confirmation if relevant;
- result and rationale summary.

Examples:

- GitHub Issue creation: read back the issue and compare repository, issue number, title and configured fields.
- Assignment: read back and compare assignee/team.
- Status/label change: read back the resource state.
- Bug resolution: issue closure alone is not proof that the bug is fixed; require configured evidence such as linked pull request/check/test result or authorized human confirmation.
- Onboarding: all mandatory checklist tasks and approvals completed, with customer-visible and internal completion separated.

### 10.3 Evidence model

Evidence record includes source type, source reference, captured timestamp, actor, resource, content hash or stable identifier, verification rule, freshness and access classification. Avoid copying unnecessary sensitive content into evidence tables.

### 10.4 Audit model

Append-only at application level. Record:

- actor type/id (user, agent, system, connector);
- organization and request/run/node context;
- action and resource;
- timestamp and correlation ID;
- policy decision and policy version;
- approval reference, if applicable;
- outcome and evidence reference;
- safe metadata/parameter hash.

Never log credentials, private keys, full access tokens, password values or unnecessary sensitive request content. Do not log hidden chain-of-thought.

### 10.5 Observability

- Structured logs with `request_id`, `workflow_run_id`, `node_run_id`, `organization_id`, `trace_id`.
- Metrics for API latency/errors, activity attempts, queue/worker health, workflow duration, retries, LLM tokens/cost, connector rate limits, SLA and verification.
- Health endpoints for API, database and Temporal connectivity.
- Execution event stream (SSE) filtered by authorization and organization.

---

## 11. Memory and pgvector

### 11.1 Memory classes

- `REQUEST_MEMORY`: prior requests and relevant outcomes.
- `WORKFLOW_MEMORY`: approved workflow templates and versions.
- `EXECUTION_MEMORY`: execution results, errors and recovery patterns.
- `KNOWLEDGE_MEMORY`: policy documents, SOPs and technical knowledge.
- `FEEDBACK_MEMORY`: employee/requester feedback and corrections.

### 11.2 Promotion rules

Do not promote an execution into “successful reusable pattern” merely because the agent said it succeeded. Promotion requires a verified outcome or explicit authorized human approval. Preserve provenance, validity period, confidence and review status.

### 11.3 Retrieval requirements

- Filter by organization, department, access classification, request type, validity and source status before/alongside similarity ranking.
- Never retrieve cross-organization memory.
- Do not let retrieved memory issue privileged instructions.
- Keep retrieved content labeled as untrusted reference data.
- Store embedding model/provider and dimensions metadata; changing embedding model may require a new embedding version/re-index.
- Begin with exact/keyword plus vector retrieval only if useful; vector search is not a substitute for relational filters.

### 11.4 Initial demo behavior

Implement basic memory write/read and filtering, but keep it advisory. Do not enable autonomous policy or workflow learning from unreviewed data.

---

## 12. Data model and persistence requirements

The repository may already define equivalent entities. Reuse compatible models and map this specification to existing naming rather than duplicating tables.

### 12.1 Core tables/entities

**Identity and organization**
- `organizations`
- `users`
- `memberships` (user, organization, status, user_kind)
- `departments`
- `teams` (optional if repository already models teams)
- `roles`, `permissions`, `role_permissions`, `membership_roles`
- `agent_identities`, `agent_capabilities`, `agent_tool_grants`

**Request domain**
- `requests`
- `request_participants`
- `request_attachments`
- `request_analyses` (versioned structured outputs)
- `human_tasks`
- `comments` or `request_messages` with internal/customer visibility classification

**Workflow domain**
- `workflow_definitions`
- `workflow_versions` (immutable published version and JSONB graph)
- `workflow_runs`
- `workflow_node_runs`
- `workflow_replan_proposals`

**AI and agent execution**
- `agent_tasks`
- `agent_runs`
- `llm_call_records` (provider/model, purpose, latency, token usage/cost if available, status; no secrets or hidden reasoning)
- `prompt_versions` or prompt registry if not already provided

**Governance**
- `policy_sets`
- `policy_rules`
- `policy_decisions`
- `approval_requests`
- `approval_decisions`
- `permission_grants` (scoped, time-bound where appropriate)

**Integration and event processing**
- `connector_installations`
- `connector_resource_scopes`
- `connector_secret_references`
- `webhook_inbox`
- `integration_sync_cursors`
- `outbox_events`
- `connector_operation_records`

**Evidence and audit**
- `execution_events`
- `execution_evidence`
- `audit_logs`
- `verification_runs`

**Memory and analytics**
- `knowledge_sources`
- `memory_items`
- `memory_embeddings` (or embeddings column on memory items where appropriate)
- `sla_policies`
- `cost_records`
- `metric_snapshots` (optional; derived queries may suffice for demo)

### 12.2 Common fields

Business tables should generally include `id` (UUID), `organization_id`, `created_at`, `updated_at`, `created_by`/`updated_by` where applicable, and `metadata` only when a flexible extension is needed. Use foreign keys and explicit status enums/check constraints where appropriate. Add indexes for frequent filters: organization, status, department, requester, created time, request/run correlation, connector resource ID and event idempotency key.

### 12.3 Workflow version integrity

- Draft versions may be edited.
- Published versions are immutable.
- Every workflow run references one exact version ID and content hash.
- Replanning creates a new proposal/version; never mutate the graph of an active run in place.

### 12.4 Organization isolation

Even with one organization in the demo, include `organization_id` on all business and memory records. Enforce organization scoping in repositories/service layer and tests. PostgreSQL Row-Level Security may be added if compatible with the existing connection/role model; do not claim RLS protection unless database roles and policies are actually configured and tested.

### 12.5 Secrets

- `.env.example` contains placeholders only.
- Never commit `.env`, private keys, webhook secrets or GitHub credentials.
- Use environment variables/Docker secrets for demo and document a future secret manager integration.
- Encrypt persisted connector secrets if the architecture requires storing them; otherwise store only secure secret references.

---

## 13. API contract baseline

All endpoints use `/api/v1`, typed request/response schemas, consistent error format, authorization dependencies and correlation IDs. Align with existing routes if already established; do not create duplicate API patterns.

### 13.1 Authentication and identity

- `POST /api/v1/auth/login`
- `POST /api/v1/auth/refresh` (only if refresh flow is implemented)
- `POST /api/v1/auth/logout` (revoke refresh/session where applicable)
- `GET /api/v1/auth/me`
- `GET /api/v1/departments`
- `GET /api/v1/users` (authorized admin/manager scope)

### 13.2 Requests and intelligence

- `POST /api/v1/requests`
- `GET /api/v1/requests`
- `GET /api/v1/requests/{request_id}`
- `PATCH /api/v1/requests/{request_id}`
- `POST /api/v1/requests/{request_id}/analyze`
- `POST /api/v1/requests/{request_id}/clarifications`
- `GET /api/v1/requests/{request_id}/analysis`
- `POST /api/v1/requests/{request_id}/propose-workflows`

### 13.3 Workflow design and validation

- `POST /api/v1/workflows`
- `GET /api/v1/workflows`
- `GET /api/v1/workflows/{workflow_id}`
- `POST /api/v1/workflows/{workflow_id}/versions`
- `POST /api/v1/workflows/validate`
- `POST /api/v1/workflows/{workflow_id}/publish`
- `GET /api/v1/workflows/{workflow_id}/versions/{version_id}`

### 13.4 Execution

- `POST /api/v1/workflow-runs`
- `GET /api/v1/workflow-runs`
- `GET /api/v1/workflow-runs/{run_id}`
- `GET /api/v1/workflow-runs/{run_id}/events`
- `POST /api/v1/workflow-runs/{run_id}/pause`
- `POST /api/v1/workflow-runs/{run_id}/resume`
- `POST /api/v1/workflow-runs/{run_id}/cancel`
- `POST /api/v1/workflow-runs/{run_id}/replan` (creates a bounded proposal, never silently edits running version)

### 13.5 Human tasks and approvals

- `GET /api/v1/tasks`
- `GET /api/v1/tasks/{task_id}`
- `POST /api/v1/tasks/{task_id}/claim`
- `POST /api/v1/tasks/{task_id}/complete`
- `POST /api/v1/tasks/{task_id}/block`
- `GET /api/v1/approvals`
- `GET /api/v1/approvals/{approval_id}`
- `POST /api/v1/approvals/{approval_id}/decision`

### 13.6 Agents, connectors and events

- `GET /api/v1/agents`
- `GET /api/v1/agents/{agent_id}`
- `GET /api/v1/connectors`
- `POST /api/v1/connectors/github/installations` or the callback route required by GitHub App setup
- `GET /api/v1/connectors/github/status`
- `POST /api/v1/webhooks/github`
- `POST /api/v1/connectors/github/reconcile` (admin-triggered/demo)

### 13.7 Evidence, audit, analytics and memory

- `GET /api/v1/requests/{request_id}/verification`
- `GET /api/v1/workflow-runs/{run_id}/evidence`
- `GET /api/v1/audit-logs`
- `GET /api/v1/metrics/overview`
- `GET /api/v1/metrics/sla`
- `GET /api/v1/metrics/automation`
- `GET /api/v1/metrics/cost`
- `GET /api/v1/metrics/agents`
- `GET /api/v1/metrics/departments`
- `GET /api/v1/metrics/industries`
- `GET /api/v1/memory/search` (strict permission/organization filters)

### 13.8 API implementation rules

- Do not expose ORM models directly.
- Use pagination, filtering, sorting and bounded page sizes.
- Apply authorization at service/use-case level, not only at route visibility.
- Use idempotency keys on request creation where practical and mandatory on side-effecting execution commands.
- Return `202 Accepted` for long-running analysis/execution with resource ID/status when appropriate.
- Use a consistent error envelope with stable error codes.
- SSE must enforce the same request/organization authorization as REST.

---

## 14. Events, transactional outbox and real-time updates

### 14.1 Domain event names

`REQUEST_CREATED`, `REQUEST_CLASSIFIED`, `CLARIFICATION_REQUIRED`, `WORKFLOW_PROPOSED`, `WORKFLOW_VALIDATED`, `APPROVAL_REQUESTED`, `APPROVAL_GRANTED`, `APPROVAL_REJECTED`, `WORKFLOW_STARTED`, `NODE_STARTED`, `NODE_COMPLETED`, `NODE_FAILED`, `EXTERNAL_EVENT_RECEIVED`, `SLA_WARNING`, `WORKFLOW_REPLAN_PROPOSED`, `WORKFLOW_REPLAN_APPROVED`, `VERIFICATION_COMPLETED`, `REQUEST_VERIFIED`, `WORKFLOW_COMPLETED`, `WORKFLOW_FAILED`.

### 14.2 Event envelope

Each event includes:

- `event_id`, `event_type`, `occurred_at`, `organization_id`;
- `aggregate_type`, `aggregate_id`, `aggregate_version`;
- `request_id`, optional `workflow_run_id`, `node_run_id`;
- `actor_type`, `actor_id`, `correlation_id`, `causation_id`;
- schema version and minimal payload.

### 14.3 Reliability

Use a transactional outbox when a database transaction must cause an asynchronous event. Consumers are idempotent. Webhook inbox is separate from internal outbox. Do not assume event delivery is exactly once.

### 14.4 SSE

Publish authorized event summaries, not secrets or unrestricted raw payloads. Frontend should be able to reconstruct run progress from a snapshot endpoint plus subsequent events.

---

## 15. Analytics definitions

All metrics should be filterable by date range, department, request type, workflow, and industry/domain tag where available. State the numerator/denominator and time-window in API documentation.

| Metric | Suggested definition |
|---|---|
| Request volume | Count of requests created in period |
| SLA compliance | Requests resolved within applicable SLA / requests with SLA due in period; document treatment of open requests |
| Mean resolution time | Time from accepted/created to verified/closed; report median and percentiles as well as mean |
| Automation rate | Eligible workflow steps completed without human execution / total eligible workflow steps; do not equate all AI actions with automation |
| Workflow success rate | Runs reaching configured terminal success state / completed runs; report verified and unverified separately |
| Verified resolution rate | Requests with VERIFIED result / requests reaching terminal evaluation |
| Human intervention rate | Runs requiring human task/approval / total runs |
| Agent success rate | Agent tasks meeting their typed output/acceptance contract / completed agent tasks |
| Agent failure/retry rate | Failed or retried agent tasks / total agent tasks |
| Cost per workflow | Recorded provider/connector/infrastructure cost attributed to run; mark estimates vs actuals |
| Department workload | Open tasks, completed tasks, aging and SLA breach by department |
| Approval latency | Time between approval request and decision |
| Replan rate | Runs with one or more replan proposals / total runs |
| Verification failure rate | Failed or unverified checks / verification runs |

Do not present estimated costs as actual charges. If provider usage/pricing is unavailable, mark cost as `ESTIMATED` or `UNKNOWN`.

---

## 16. Frontend integration contract

Frontend choice: React. TypeScript is recommended. React Flow can be used for node/edge canvas if appropriate to the existing frontend. The backend remains the source of truth for workflow schema, validation, permissions and execution.

Required backend support:

- Workflow schema with node/edge definitions and node configuration schemas.
- Node registry/capabilities endpoint for palette population.
- Server-side graph validation response with errors/warnings per node/edge.
- Workflow version and publish state.
- Execution snapshot and node statuses.
- SSE execution event stream.
- Approval payload showing exact action, parameters, resource scope, risk, requester and workflow version.
- Customer-safe versus internal-only request field serialization.
- Evidence and verification result display.

Frontend must not determine whether a node is authorized or approved. UI-level hiding is not a security control.

---

## 17. Security and privacy baseline

- Passwords hashed using a maintained password hashing implementation (prefer Argon2id where supported by repository/dependencies).
- Short-lived JWT access tokens; validate signature, issuer/audience where configured, expiry and subject. JWT payload is signed, not encrypted; do not put secrets or sensitive data in claims.
- Do not authorize solely from stale role claims in a long-lived token; load or validate current membership/permissions for protected actions.
- Refresh token rotation/revocation if refresh tokens are used.
- CORS allowlist configured for local frontend origins; no wildcard with credentials.
- Rate limits for login, request intake, LLM-triggering endpoints and webhook abuse as appropriate.
- Validate webhook HMAC over raw body using constant-time comparison.
- Strict file upload size/type limits and safe storage if attachments are implemented.
- Parameterized DB queries; no dynamic SQL from LLM output.
- No `eval`, dynamic import, shell execution or generated-code execution from workflow payloads.
- Prompt-injection defense is layered: trusted instructions separated from untrusted data, tool schemas constrained, output validated, tool permissions checked in backend, high-risk approval gates, and adversarial tests.
- Store secrets outside source control; redact logs.
- Apply organization and customer visibility filters to requests, memory, events, comments and attachments.
- Audit access to sensitive resources and connector actions.

---

## 18. Test strategy and acceptance criteria

### 18.1 Required tests

**Unit tests**
- Pydantic input/output schemas.
- Request classifier parsing and fallback.
- Workflow graph validator (invalid nodes, missing dependencies, cycles, bad mappings).
- Policy evaluation and scope checks.
- Risk band and approval requirements.
- Agent capability selection and bounded concurrency.
- Idempotency and event deduplication.
- Verification rules and evidence freshness.
- Memory organization/permission filters.

**Integration tests**
- Database migrations apply from clean database.
- FastAPI auth and RBAC/department/customer scopes.
- Temporal workflow with mock activities.
- Approval wait/resume via signal/update.
- Retry and timeout behavior.
- GitHub App adapter with mocked HTTP responses.
- Webhook signature verification and duplicate delivery handling.
- Outbox publish/consume recovery.

**End-to-end tests**
- Each of the five request types can be submitted and receives a structured analysis.
- At least one end-to-end workflow reaches a verified terminal state using Mock GitHub or a test GitHub App.
- Change Request pauses for approval before any protected action.
- Customer contact cannot view another customer’s/internal request.
- Agent with insufficient permission is blocked even if the LLM proposes the action.
- Duplicate start request/webhook does not duplicate external issue creation or workflow events.
- Backend/worker restart preserves resumability.
- Frontend can render workflow, validation errors, node progress, approval and verification state from APIs/events.

### 18.2 Definition of Done

A phase is done only when:
- Code follows existing repository conventions.
- Migrations and config are documented.
- Relevant automated tests pass.
- No secrets are committed.
- API schemas/docs are updated.
- Failure and authorization paths are tested, not only the happy path.
- Demo runbook explains how to start services, seed data and execute the demo.

### 18.3 Demo acceptance checklist

- [ ] Start the stack using documented Docker Compose commands.
- [ ] Apply migrations and seed one organization, six departments, roles, agents and demo policies.
- [ ] Log in as requester, worker, manager, security/auditor and admin test users.
- [ ] Create all five request categories.
- [ ] Run bounded multi-agent analysis and view structured findings.
- [ ] Generate and validate at least one workflow per selected category or a reusable template with category-specific config.
- [ ] Show policy decision and approval gate for high-risk Change Request.
- [ ] Execute GitHub Issue create/read/update against Mock or configured GitHub App.
- [ ] Receive webhook and run reconciliation fallback.
- [ ] Show execution timeline, node states, retries, SLA and costs/estimates.
- [ ] Prove result with evidence and show VERIFIED/PARTIALLY_VERIFIED/FAILED/UNVERIFIED outcomes.
- [ ] View audit trail and analytics by department/request type.
- [ ] Demonstrate bounded replan after a simulated failure without privilege escalation.

---

## 19. Suggested implementation phases

Prioritize vertical slices and preserve working code. Do not scaffold every module with empty placeholder functions.

1. **Repository audit and architecture map** — identify existing stack, conventions, migrations, tests, routes and active functionality.
2. **Foundation alignment** — settings, logging, database/migrations, health checks, auth and organization scope.
3. **Request domain vertical slice** — request API, customer/employee roles, department model and seeded data.
4. **AI provider and intelligence** — provider protocol, Mock provider, structured classification, bounded swarm orchestration and cost record.
5. **Workflow DSL and validation** — node registry, graph schema, validation, versioning and candidate scoring.
6. **Governance** — RBAC/resource scope, policy engine, risk bands, approval binding and execution guard.
7. **Temporal runtime** — durable workflow, node scheduling, signals, timeout/retry, cancellation and idempotency.
8. **GitHub App connector** — installation flow/config, least-privilege token use, issue actions, webhook inbox and polling reconciliation.
9. **Verification/evidence/audit** — read-back verification, status transitions and audit history.
10. **Memory/analytics/SSE** — permission-filtered pgvector retrieval, metrics definitions and real-time event API.
11. **Docker/demo hardening** — compose, seed data, mock failure scenarios, E2E tests and demo runbook.

If time is constrained, complete a smaller fully working path (Request -> Analyze -> Plan -> Validate -> Approve -> Execute -> Verify -> Audit) before adding breadth. All five request categories should be accepted and classified, but not every category needs a complex bespoke workflow in the first vertical slice.

---

## 20. Repository inspection requirements

Before changing code, inspect and report:

- top-level tree and actual backend/frontend directories;
- Python/runtime/package manager versions;
- existing API framework and routing conventions;
- database, ORM and migration setup;
- authentication/authorization implementation;
- background jobs, queue and workflow/runtime code;
- LLM or agent integrations;
- connectors/webhooks;
- test framework and current test results;
- Docker/CI/configuration;
- existing data models and naming conventions;
- incomplete/duplicate/dead code that materially affects implementation.

Create a mapping from this specification to existing code: `REUSE`, `EXTEND`, `REFACTOR`, `ADD`, or `DEFER`. Do not replace an existing working library or module solely to match this document. Where the repository conflicts with the baseline, explain the tradeoff and select the smallest safe change.

Do not delete data, rewrite Git history, remove tests, overwrite environment files, expose secrets, force-push, or make destructive migrations. Ask before any irreversible operation. Never claim tests passed unless actually executed.

---

## 21. External technical references

Use official documentation and check version compatibility against the repository before adding dependencies:

- Temporal Python SDK: https://docs.temporal.io/develop/python
- FastAPI OAuth2/JWT guide: https://fastapi.tiangolo.com/tutorial/security/oauth2-jwt/
- GitHub App permissions: https://docs.github.com/en/apps/creating-github-apps/registering-a-github-app/choosing-permissions-for-a-github-app
- GitHub App authentication: https://docs.github.com/en/apps/creating-github-apps/authenticating-with-a-github-app
- GitHub webhook signature validation: https://docs.github.com/en/webhooks/using-webhooks/validating-webhook-deliveries
- pgvector: https://github.com/pgvector/pgvector
- React Flow examples/docs: https://reactflow.dev/examples
- PostgreSQL Row Security: https://www.postgresql.org/docs/current/ddl-rowsecurity.html
- OWASP Prompt Injection Prevention: https://cheatsheetseries.owasp.org/cheatsheets/LLM_Prompt_Injection_Prevention_Cheat_Sheet.html

These are implementation references, not permission to blindly upgrade dependencies. Pin compatible versions after inspecting the existing repository.

---

## 22. Key architectural decisions to preserve

1. **AI proposes; policy authorizes; runtime executes; verifier proves.**
2. **Bounded swarm:** specialist collaboration under one supervisor, with centralized tool execution.
3. **Immutable workflow versions:** every execution binds to a precise workflow version and hash.
4. **No generated-code execution:** workflow definitions are declarative JSON over registered node types.
5. **Check before every side effect:** approval at workflow start does not replace per-action authorization.
6. **Idempotent external actions:** retries must not create duplicate Issues or duplicate business effects.
7. **Evidence-based completion:** success requires configured postconditions and evidence.
8. **Organization and customer data isolation:** enforced by backend, not merely frontend.
9. **Industry extensibility without demo bloat:** generic core + request/domain configuration.
10. **Existing repository first:** inspect, reuse and evolve rather than rebuild blindly.
