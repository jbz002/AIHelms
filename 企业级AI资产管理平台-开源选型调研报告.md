# 企业级 AI 资产管理平台 — 开源选型调研报告

> 第 5 项「开发文档 / Skill / MCP 能力中心」
> 编写日期：2026-07-07 ｜ 版本：v1.0（基于三个开源项目的源码深度分析）
> 评估对象：`AIHelms`、`mcp-gateway-registry`、`backstage-dev-ai-hub`

---

## 摘要（TL;DR）

- **定位校准**：第 5 项的定位已从「面向 AI 开发者的能力中心」升级为「**企业级 AI 资产管理平台**」。分水岭是：**"成本可见可控 + 统一 AI 身份"是资产管理平台区别于开发者工具的标志**——资产应面向全员（决策层/管理员/员工），而非仅 AI 开发者。
- **核心洞察**：demo 下的三个开源项目**并非同质竞争，而是处于三个不同的架构层**——
  - `AIHelms` = **运营管控层**（企业 AI 资产的 "ERP"：成本/身份/预算/效能）
  - `mcp-gateway-registry` = **接入治理层**（AI 资产的 "Service Mesh"：发现/认证/审计/多租户）
  - `backstage-dev-ai-hub` = **开发者门户层**（资产目录 + MCP 自动发现分发）
- **没有任何单一项目覆盖"资产管理平台"的全部四大支柱**。三者能力互补，需组合。
- **最终推荐**：以 **AIHelms 为主平台**（唯一覆盖成本/身份/预算/效能，最贴近资产管理定位）；**mcp-gateway-registry 作为按需补强的接入治理层**（当 MCP/Agent 规模化时叠入）；**文档库缺口用 docs-mcp-server 补**（注册为 MCP 进 AI 市场）；**backstage-dev-ai-hub 不作生产主力**（个人早期项目，但 GitOps+MCP 自动发现理念可借鉴）。
- **落地前第一件事**：与技术总管对齐**第 4 项（大模型网关）边界**——AIHelms 自带 LiteLLM 网关 + 成本管理，极可能已覆盖第 4 项，避免重复建设。

---

## 一、调研背景与定位校准

### 1.1 第 5 项定位演进

| 阶段 | 定位 | 受众 |
|---|---|---|
| 原始规划 | 面向内部 AI 开发者的工具与资源聚合平台 | 仅 AI 开发者 |
| **当前定位** | **企业级 AI 资产管理平台** | **全员（决策层/管理员/员工）** |

升级理由：既然定位是"资产管理"，AI 资产（模型、Skill、MCP、智能体）不应只服务 AI 开发者——决策层要看成本与效能、管理员要管权限与合规、员工要用 AI 身份调用能力。

### 1.2 资产管理平台 vs 开发者工具的分水岭

> **"成本可见可控 + 统一 AI 身份"是资产管理平台区别于开发者工具的标志。**

- 只有"资产目录/分发" → 是**开发者工具/门户**（如 Backstage、skillsmp）
- 加上"成本核算 + 身份管控 + 预算限速 + 效能报表" → 才是**资产管理平台**（如企业资产的 ERP）

### 1.3 与第 1 项（企业知识库）的边界

第 5 项沉淀的是**能力/工具**（被开发者在造 AI 应用时调用、组装）；第 1 项沉淀的是**知识**（被 AI 读取后回答员工问题）。判断口诀：**给员工"查询"的 → 第 1 项；给开发者"调用"的 → 第 5 项。**

---

## 二、评估框架：企业级 AI 资产管理平台的四大支柱

本报告以此四维评估每个项目的覆盖度：

| 支柱 | 内涵 | 关键能力 |
|---|---|---|
| **A. 资产纳管** | 统一注册、发现、分类所有 AI 资产 | MCP Server / Skill / Agent / 文档库 / 模型 的纳管 |
| **B. 统一 AI 身份与成本** | 资产管理平台的"灵魂" | API Key、预算、限速、token 级成本归因、用量统计、多维报表 |
| **C. 治理** | 企业级安全合规 | RBAC、SSO/多 IdP、版本、审计、安全扫描、审核发布、多租户 |
| **D. 体验** | 全员可用 | 检索、一键安装/调用、贡献上传、评分 |

> **B 支柱是分水岭**：B 强 → 资产管理平台；B 缺 → 只是工具/门户。

---

## 三、三项目速览

| 维度 | AIHelms | mcp-gateway-registry | backstage-dev-ai-hub |
|---|---|---|---|
| **一句话定位** | 企业 AI 资产的 ERP | AI 资产的 Service Mesh | Backstage 插件化的资产中台 |
| **架构层** | 运营管控层 | 接入治理层 | 开发者门户层 |
| **远程仓库** | beizhu-1209/AIHelms | agentic-community/mcp-gateway-registry | JulianPedro/backstage-dev-ai-hub |
| **技术栈** | Vue3 + FastAPI + PostgreSQL + LiteLLM | Python3.14 + FastAPI + MongoDB/DocumentDB + Keycloak | Backstage + React + Node + SQLite |
| **许可证** | ⚠️ GPL-3.0 | ✅ Apache-2.0 | ✅ Apache-2.0 |
| **提交数** | 91 | **1665** | 43 |
| **贡献者** | 3 | **60** | 2 |
| **最近提交** | 2026-07-07（今天） | 2026-07-06（昨天） | 2026-06-14（3 周前） |
| **成熟度** | 🟡 小团队高频迭代（v0.1.14） | 🟢 社区级成熟（AWS 背书） | 🔴 个人早期项目（v0.1.0） |
| **A 资产纳管** | ✅ 85% | 🟡 80%（元数据✅/内容❌） | ✅ 90% |
| **B 身份与成本** | ✅ **90%** | 🟡 50%（接入身份✅/模型成本❌） | ❌ **0%** |
| **C 治理** | 🟡 70% | ✅ **95%** | 🟡 40%（仅骨架） |
| **D 体验** | ✅ 80% | ✅ 85% | ✅ 85% |
| **部署复杂度** | 中（4 核 8G 起） | 高（6+ 容器，需 SRE） | 中（需懂 Backstage） |

---

## 四、项目深度剖析

### 4.1 AIHelms —— 运营管控层（企业 AI 资产的 "ERP"）

**定位**：统一管理 AI 资产、控制 AI 成本、量化 AI 价值的全生命周期平台。

**技术架构**：
- 前端：Vue 3.4+ / TypeScript / Vite / TailwindCSS（npm workspaces monorepo，admin + web + shared 三包）
- 后端：Python 3.11 / FastAPI / Celery，严格分层 Router→Service→Repository→DB
- 数据：PostgreSQL 16（**47 张表**的完整业务模型）+ Redis 7
- 模型层：**LiteLLM v1.85.1** 作为统一模型网关（不改源码、可独立升级）
- 部署：Docker Compose + Nginx，最低 4 核 8G

**核心功能（均已落地）**：
- **模型纳管**：多供应商统一接入、多部署负载均衡、路由策略、连通性测试
- **AI 身份管理**：部门/项目/人员 RBAC、Key 签发（个人/部门/项目场景）、**四维预算**（人/部门/项目/模型，软/硬限制）、TPM/RPM 限速、模型白名单
- **成本与效能**：**内外双轨定价**、**token 级成本归因**（`llm_call_logs` 表记录到人/部门/项目/模型）、周月自动报告（Celery 异步生成）、模型性价比分析
- **AI 市场**：Skill 发布上架 + MCP Server 注册 + 申请审批流
- **安全**：**AI Policies 一键扫描 Skill 恶意指令**（v0.1.13，基于 NVIDIA SkillSpector + OWASP Agentic Skills Top 10）、管理员审计日志（180 天）
- **智能体中心**：智能体创建配置、生命周期、使用日志

**四大支柱覆盖**：
- A 资产纳管 **85%**：MCP/Skill/Agent/模型 ✅；**文档库 ❌**
- B 身份与成本 **90%**：API Key/预算/限速/token 归因/报表 全覆盖（**三项目中最强**）
- C 治理 **70%**：RBAC/审计/安全扫描 ✅；**SSO ❌、版本管理 ❌**
- D 体验 **80%**：检索/安装/贡献 ✅；评分 ❌

**优势**：
1. **真正的企业级成本管控**——内外双轨定价 + token 级归因 + 四维预算，是三项目中唯一把"成本"做透的
2. **数据主权**——平台数据库是唯一数据源，所有业务数据先落库再同步 LiteLLM，外部依赖丢失可完整恢复
3. **开箱即用的安全合规**——SkillSpector 扫描 + 审计日志 + RBAC
4. **生产就绪**——Docker Compose 一键部署、健康检查、日志轮转、Celery 异步
5. **中文原生**——贴合国内企业语境与审批习惯

**劣势与风险**：
- ⚠️ **GPL-3.0**：纯内网使用合法（仅分发修改版二进制才触发开源义务）；比 AGPL 友好，但比 Apache 严格
- ⚠️ **成熟度**：91 commits / 3 人 / v0.1.x，建议 2–4 周 POC 再生产采纳
- 缺 SSO（企业常需 LDAP/OAuth/SAML）、缺文档库/RAG、审批流较简单（无多级会签工作流引擎）
- 无 Prometheus/Grafana 监控集成，需自建

**独特卖点**：
> **AIHelms 不是"一个 MCP 网关"或"一个门户插件"，而是"企业 AI 资产的 ERP 系统"——把模型、Skill、MCP、智能体视为可计费、可管控、可审计的资产，提供从采购接入 → 分配使用 → 成本核算 → 安全治理的全生命周期管理，让 AI 投入"看得见、管得住、算得清"。**

---

### 4.2 mcp-gateway-registry —— 接入治理层（AI 资产的 "Service Mesh"）

**定位**：从 MCP 网关演化而来的通用 AI 资产注册表，是"AI 资产的接入层和治理控制面"。

**技术架构**（三服务解耦）：
- **Registry**（控制面）：资产元数据存储 + 治理（WHO can access WHAT），Python/FastAPI + MongoDB/DocumentDB（支持向量搜索）
- **Auth Server**（身份层）：独立可扩展，支持 Keycloak/Entra ID/Okta/Auth0/Cognito/PingFederate 等 6+ 企业 IdP
- **MCP Gateway**（代理层，可选）：路由、健康检查、负载均衡
- 部署：Docker Compose / Helm（EKS）/ Terraform（AWS ECS Fargate）；安全工具链齐全（Bandit/Semgrep/pre-commit/secrets 扫描）

**核心功能（企业级成熟）**：
- **统一资产注册表**：MCP Server / A2A Agent / Skill (SKILL.md) / **Custom Entity**（1.24.4 突破——管理员自定义 Schema，可纳管**任意**资产：模型卡、数据集、评估、n8n 工作流、策略、提示模板）
- **OAuth 2LO/3LO**：M2M + 用户授权；**Per-User Egress Auth**（1.26.0 突破）——第三方 SaaS（GitHub/Slack/Atlassian）令牌由 Gateway 统一 OAuth 3LO 获取并保管在 Vault，用户本地永不存令牌
- **多租户 RBAC**：基于 Groups 的细粒度权限（服务器/工具/方法/UI 特性级）、Group-Restricted 可见性
- **审计与合规**：WHO/WHAT/WHEN/WHERE/OUTCOME 完整日志、自动凭证屏蔽、TTL 保留、JSONL/CSV 导出、SOC 2/GDPR 就绪
- **安全扫描**：集成 Cisco AI Defense（MCP/Agent/Skill 三类扫描器）
- **A2A 协议**：Agent 注册发现 + 点对点通信
- **联邦**：兼容 Anthropic MCP Registry、AWS AgentCore、ARD v1.0 spec，支持对等联邦
- **可观测性**：OpenTelemetry 原生指标（Prometheus/Datadog/Grafana Cloud 等）
- **混合搜索**：RRF 算法（向量 + 关键词融合）

**四大支柱覆盖**：
- A 资产纳管 **80%**：资产**元数据**注册发现 ✅（Custom Entity 极强）；但**不托管内容**（模型文件/数据集/文档全文 ❌）——是"资产电话簿"非"资产仓库"
- B 身份与成本 **50%**：**接入身份管理 ✅**（OAuth/Groups/Per-User Egress）；**大模型 Key/成本/预算/限速 ❌**（不管 Claude/OpenAI 的 Key 轮换与用量归因）
- C 治理 **95%**：**三项目中最强**——多 IdP/多租户/审计/扫描/审核工作流/合规，达商业产品水准
- D 体验 **85%**：语义搜索/注册/调用测试/投票/Registry Card

**优势**：
1. **治理成熟度最高**——媲美商业安全产品，60 人社区 + AWS 背书
2. **Per-User Egress Auth**——企业第三方令牌收敛到单一审计点，安全价值极高
3. **Custom Entity Registry**——突破预设类型，真正"任意 AI 资产可纳管"
4. **协议无关**——不绑定 Agent 框架/模型 Provider/运行时，heterogeneous 资产统一治理
5. **生产级运维**——OTel 指标、多表面部署、压力测试套件

**劣势与风险**：
- ⚠️ **定位边界明确**：它是"接入网关 + 注册表"，**不是完整资产管理平台**——不管大模型成本/路由、不托管内容、不做 Agent 运行时编排
- ⚠️ **运维重**：6+ 容器（Registry/Auth/MCPGW/Metrics/Keycloak/Mongo + 可选 Grafana/Prometheus/otel/OpenBao），需专职 DevOps/SRE
- 与 AIHelms 的 MCP 管理、Agent 中心存在功能重叠，同时使用需界定边界

**独特卖点**：
> **它是"协议无关的 AI 资产接入治理层"——类似 API Gateway 之于微服务、Service Mesh 之于服务网格，是 AI-Native 的治理控制面。管访问控制、发现、审计，不管业务逻辑和内容托管。**

---

### 4.3 backstage-dev-ai-hub —— 开发者门户层（资产目录 + MCP 自动发现）

**定位**：基于 Backstage 的 AI 资产中台插件，统一管理和分发 AI 资产（Instructions/Agents/Skills/Workflows/Bundles/Prompts），通过**内嵌 MCP Server** 让 AI 工具（Claude Code/Copilot/Cursor/Gemini）自动发现并安装资产。

**技术架构**：
- 框架：Backstage（React 18 + MUI 5 + Node/Express + TypeScript）
- 数据：SQLite（Knex，可换 PostgreSQL/MySQL）
- MCP：内嵌 `@modelcontextprotocol/sdk`，暴露 8 个工具 + 1 个 proactive prompt
- 包管理：Yarn 4 workspaces monorepo（dev-ai-hub 前端 / backend / common / node 四包）

**核心功能**：
- **GitOps 资产同步**：定时拉取 GitHub/GitLab/Bitbucket/Azure DevOps 仓库，解析 YAML+MD 资产，增量入库；每个资产绑定 `branch+commitSha+path`，可回滚
- **内嵌 MCP Server**：AI 工具通过 MCP 自动 `list/search/get/install` 资产；**Proactive 模式**让 AI 主动推荐相关资产；**工具感知**按 `?tool=` 过滤兼容资产
- **MCP Catalog**：展示第三方 MCP 服务器目录、一键安装到 VSCode/Cursor
- **资产类型**：instruction / agent / skill / workflow / prompt / bundle（组合）
- **权限**：继承 Backstage Permission API（但默认 `unauthenticated` 访问）

**四大支柱覆盖**：
- A 资产纳管 **90%**：GitOps 单一数据源、6 类资产、多维筛选、版本溯源——**纳管体验最好**
- B 身份与成本 **0%**：**完全缺失**——无 API Key、无预算、无限速、无 token 归因、无用量统计（仅 installCount）
- C 治理 **40%**：仅 RBAC 骨架（默认允许匿名）；继承 Backstage SSO 能力；**无审计、无审核发布、无多租户**
- D 体验 **85%**：全文搜索、MCP 自动发现安装、Git PR 贡献

**优势**：
1. **Backstage 的"资产管理"基因**——资产即实体、插件生态可扩展（100+ 现成插件）、关系图谱潜力
2. **原生 MCP 协议深度集成**——一个 Server 兼容多 AI 工具、Proactive 主动推荐
3. **GitOps 驱动**——版本可追溯、多仓库团队隔离、修改 Git 即生效、PR 流程即审核
4. **Apache-2.0** 商业友好

**劣势与风险**：
- 🔴 **成熟度极低**：43 commits / 2 人 / v0.1.0 / 测试稀疏 / 个人项目（JulianPedro），**不可作生产主力**
- 🔴 **定位偏差**：本质是"开发者门户 + AI 插件"，**完全无运营管控**（成本/身份/限速/审计全缺）——是工具，不是管理平台
- ⚠️ **落地门槛**：需自托管 Backstage 实例、懂 React/Node/Backstage 框架；企业若无 Backstage 技术储备，集成成本高

**独特卖点**：
> **"Backstage 插件化的 AI 资产目录 + MCP 自动发现"——不做调用网关、不做运营管控，只解决"资产从哪来、如何被 AI 工具自动发现安装"。**

---

## 五、横向对比

### 5.1 四支柱覆盖度矩阵

| 支柱 | AIHelms | mcp-gateway-registry | backstage-dev-ai-hub |
|---|:---:|:---:|:---:|
| **A 资产纳管** | ✅ 85% | 🟡 80% | ✅ 90% |
| **B 身份与成本**（分水岭） | ✅ **90%** | 🟡 50% | ❌ **0%** |
| **C 治理** | 🟡 70% | ✅ **95%** | 🟡 40% |
| **D 体验** | ✅ 80% | ✅ 85% | ✅ 85% |

### 5.2 关键能力逐项对比

| 能力 | AIHelms | mcp-gateway-registry | backstage-dev-ai-hub |
|---|:---:|:---:|:---:|
| 模型纳管 / 路由 | ✅ LiteLLM | ❌ | ❌ |
| **token 级成本归因** | ✅ **内外双轨** | ❌（仅 CLI 显示） | ❌ |
| 预算 / 限速 | ✅ 四维 | ❌ | ❌ |
| 用量统计 / 效能报表 | ✅ 周月报告 | 🟡 审计+遥测 | ❌ |
| MCP Server 纳管 | ✅ | ✅ **网关+注册** | 🟡 Catalog 展示 |
| Skill 纳管 + 扫描 | ✅ SkillSpector | ✅ Cisco AI Defense | ✅（无扫描） |
| Agent 纳管 | ✅ | ✅ **A2A 协议** | ✅ |
| 文档库 / RAG | ❌ | 🟡 Custom Entity 元数据 | ❌ |
| RBAC | ✅ | ✅ **Groups+Scopes** | 🟡 骨架 |
| SSO / 多 IdP | ❌ | ✅ **6+ IdP** | 🟡 继承 Backstage |
| 多租户 | 🟡 部门隔离 | ✅ **Groups 命名空间** | ❌ |
| 审计日志 | ✅ 180 天 | ✅ **合规级** | ❌ |
| 审核发布工作流 | 🟡 简单审批 | ✅ Self-Service+Gate | 🟡 Git PR |
| 第三方令牌托管 | ❌ | ✅ **Per-User Egress** | ❌ |
| 语义检索 | 🟡 列表过滤 | ✅ **RRF 混合** | ✅ 全文 |
| MCP 自动发现分发 | ❌ | ✅ 动态工具发现 | ✅ **Proactive** |
| 部署复杂度 | 中 | **高** | 中 |
| 许可证 | ⚠️ GPL-3.0 | ✅ Apache-2.0 | ✅ Apache-2.0 |
| 成熟度（commits/人） | 91 / 3 | **1665 / 60** | 43 / 2 |

### 5.3 核心洞察：三者是"三个层"，不是同质竞争

```
┌─────────────────────────────────────────────────────────────┐
│            企业级 AI 资产管理平台（完整形态）                 │
├─────────────────────────────────────────────────────────────┤
│                                                              │
│  ┌──────────────────────────────────────────────────────┐   │
│  │  运营管控层（B 支柱：成本/身份/预算/效能）   AIHelms   │   │
│  │  ← 资产管理平台的"灵魂"，决定它是不是管理平台        │   │
│  └──────────────────────────────────────────────────────┘   │
│                          ▲ 互补 ▼                            │
│  ┌────────────────────┐   ┌────────────────────┐            │
│  │ 接入治理层          │   │ 开发者门户层        │            │
│  │ mcp-gateway-registry│   │ backstage-dev-ai-hub│            │
│  │ (C 支柱：发现/认证/ │   │ (A+D：目录/MCP分发) │            │
│  │  审计/多租户/A2A)   │   │                    │            │
│  └────────────────────┘   └────────────────────┘            │
│                                                              │
└─────────────────────────────────────────────────────────────┘
```

- **AIHelms** 唯一占据"运营管控层"——是三者中最接近"资产管理平台"完整形态的
- **mcp-gateway-registry** 占据"接入治理层"——治理最深，但不管成本（B 的核心缺失）
- **backstage-dev-ai-hub** 占据"开发者门户层"——纳管/发现体验好，但完全无运营管控

> **结论：三者能力正交、可组合，没有任何一个能单独充当完整资产管理平台。**

---

## 六、定位契合度判定

| 判定维度 | 结论 |
|---|---|
| 谁最贴近"资产管理平台"完整形态？ | **AIHelms**（唯一 B 支柱≥90%，覆盖成本/身份/预算/效能） |
| 谁的治理最值得信赖？ | **mcp-gateway-registry**（C 支柱 95%，60 人社区 + AWS 背书） |
| 谁的资产发现/分发体验最好？ | **backstage-dev-ai-hub**（GitOps + MCP Proactive） |
| 谁能直接生产上线？ | mcp-gateway-registry（成熟）／AIHelms（需 POC） |
| 谁不可作主力？ | backstage-dev-ai-hub（个人早期项目，无运营管控） |

---

## 七、选型推荐与组合方案

### 7.1 🏆 推荐方案：AIHelms 为主 + 分层补强

```
                   ┌─────────────────────────────┐
                   │   企业级 AI 资产管理平台     │
                   └─────────────────────────────┘
                                │
                 ┌──────────────┴───────────────┐
                 ▼                              ▼
    ┌──────────────────────┐        ┌──────────────────────┐
    │  主平台：AIHelms      │        │  文档库缺口：         │
    │  • 模型/身份/预算/效能 │        │  docs-mcp-server      │
    │  • Skill/MCP/智能体   │        │  （注册为 MCP 进      │
    │  • 成本归因/报表      │        │   AIHelms AI 市场）   │
    └──────────┬───────────┘        └──────────────────────┘
               │ 按需补强（MCP/Agent 规模化后）
               ▼
    ┌──────────────────────────────────────────┐
    │  接入治理层（可选）：mcp-gateway-registry  │
    │  • 多 IdP OAuth / Per-User Egress         │
    │  • 深度审计 / 多租户 / A2A / Custom Entity │
    └──────────────────────────────────────────┘
```

**为什么是 AIHelms 为主**：
1. 唯一覆盖 B 支柱（成本/身份/预算）——这是资产管理平台的分水岭
2. 功能最全（模型/身份/市场/效能/安全/智能体全闭环），最贴近直接上线
3. 中文原生，贴合国内企业审批与报表习惯

**docs-mcp-server 补文档库缺口**：AIHelms 无 RAG/文档库模块，用 docs-mcp-server（开源版 Context7，1.5k★/MIT）作为 MCP Server 注册进 AIHelms 的 AI 市场，统一纳管开发文档/内部 API 文档。

**mcp-gateway-registry 作为按需补强层**（不是 MVP 必需）：
- 触发条件：当 MCP Server/Agent 数量爆炸、需要多企业 IdP（Okta/Entra ID）、需要 Per-User Egress 托管第三方令牌、需要 A2A 协议或深度合规审计时
- 定位：作为 AIHelms 下的"接入网关"，补强 AIHelms 治理（C 支柱 70%）中缺的 SSO/多 IdP/深度审计
- ⚠️ **注意与 AIHelms 自带的 MCP 管理/审批/审计功能重叠**——同时使用必须界定：谁做"注册发现与目录"、谁做"代理网关与身份"，否则重复建设

### 7.2 备选方案（按企业实际情况）

| 场景 | 推荐组合 | 理由 |
|---|---|---|
| 要"最贴近资产管理、能较快上线" | **AIHelms 为主 + docs-mcp-server** | 唯一覆盖成本/身份，中文，闭环最全 |
| 已有 Backstage、只要资产分发门户、接受个人项目风险 | backstage-dev-ai-hub | 纳管/发现体验好，但无运营管控 |
| MCP/Agent 规模化、治理第一诉求、有 DevOps 团队 | mcp-gateway-registry 为主 + 外补成本模块（如 LangSmith） | 治理最成熟，但需另配成本核算 |
| 追求"全自由许可 + 全自研掌控" | 以 mcp-gateway-registry（Apache）为底座自研 | 规避 GPL，但工程量大 |

### 7.3 不推荐的情况

- ❌ **backstage-dev-ai-hub 作生产主力**——个人早期项目（43 commits/2 人），且无任何成本/身份/治理能力
- ❌ **三者同时全上**——功能大面积重叠（MCP 管理、Agent、审批、审计），运维灾难
- ❌ **mcp-gateway-registry 替代 AIHelms**——前者不管模型成本/身份/预算，无法独立充当资产管理平台

---

## 八、落地路径（MVP → 演进）

**原则：以 AIHelms 为骨架，单模块切入，小步迭代。**

### 阶段一（MVP，2–4 周）：AIHelms POC + 文档库闭环
- 本地 Docker Compose 部署 AIHelms，跑通模型纳管 + AI 身份 + 成本归因
- 接入 docs-mcp-server 作为 MCP，跑通"开发文档 → 检索 → AI 调用"闭环
- **POC 期间同步验证 AIHelms 是否已覆盖第 4 项（大模型网关）**

### 阶段二：Skill 市场 + 治理底座
- 沉淀 5–10 个高频技术 Skill，跑通"贡献 → SkillSpector 扫描 → 审批 → 发布 → 调用"
- 打好版本/权限/统计底座

### 阶段三（按需）：接入 mcp-gateway-registry 治理层
- 当 MCP/Agent 规模化、需多 IdP/Per-User Egress/深度审计时引入
- 明确与 AIHelms 的职责边界（注册发现 vs 代理网关）

---

## 九、风险与待对齐事项

| # | 事项 | 说明 | 应对 |
|---|---|---|---|
| 1 | ⚠️ **第 4 项边界（最高优先）** | AIHelms 自带 LiteLLM 模型网关 + 统一接入 + 成本核算 + 用量统计 + 权限管控，**几乎覆盖第 4 项全部需求** | **落地前与技术总管确认：第 4 项是独立做，还是由 AIHelms 统一承载。这决定整个选型范围** |
| 2 | ⚠️ AIHelms 与 mcp-gateway-registry 功能重叠 | 两者都有 MCP 管理/审批/审计/Agent | 同时用须界定边界，否则重复建设 |
| 3 | ⚠️ GPL-3.0（AIHelms） | 纯内网用无传染风险；仅分发修改版二进制才触发开源义务 | 内网部署合规；若需对外分发，评估商业授权或改用 Apache 方案 |
| 4 | 🟡 AIHelms 成熟度 | 91 commits / 3 人 / v0.1.x | 先 2–4 周 POC，关键路径补测试后再生产 |
| 5 | 🟡 AIHelms 缺 SSO | 企业常需 LDAP/OAuth/SAML | 评估二次开发接入成本，或由 mcp-gateway-registry 的 Auth Server 补 |
| 6 | 🔴 backstage-dev-ai-hub 不可作主力 | 个人早期项目，无运营管控 | 仅借鉴其 GitOps + MCP 自动发现理念 |

---

## 十、结论

> 第 5 项按"企业级 AI 资产管理平台"落地，**主平台选 AIHelms**（唯一覆盖成本/身份/预算/效能，最贴近资产管理定位，中文原生，闭环最全）；**文档库缺口用 docs-mcp-server 补**（注册为 MCP 进 AI 市场）；**mcp-gateway-registry 作为按需补强的接入治理层**（规模化后叠入，补 SSO/多 IdP/深度审计/A2A）；**backstage-dev-ai-hub 不作生产主力**，但其 GitOps + MCP 自动发现模式可借鉴到资产上架流程。
>
> **落地前第一件事：与技术总管对齐第 4/5 项边界——AIHelms 自带模型网关与成本管理，极可能已覆盖第 4 项。**

---

## 附录 A：三项目 git 成熟度原始数据

| 项目 | remote | commits | 贡献者 | 最近提交 |
|---|---|---|---|---|
| AIHelms | beizhu-1209/AIHelms | 91 | 3 | 2026-07-07 |
| mcp-gateway-registry | agentic-community/mcp-gateway-registry | 1665 | 60 | 2026-07-06 |
| backstage-dev-ai-hub | JulianPedro/backstage-dev-ai-hub | 43 | 2 | 2026-06-14 |

## 附录 B：评估维度与需求映射来源

- 四大支柱：源自《AI开发能力中心-需求解读.md》第 4 章「三位一体 + 治理底座」+ 资产管理平台定义
- 第 4 项边界：源自《ai开发计划.txt》第 4 项「通用大模型网关」
- 第 1 项边界：源自《ai开发计划.txt》第 1 项「企业知识库对话系统」
