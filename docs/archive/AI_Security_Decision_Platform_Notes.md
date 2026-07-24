> **OUTDATED / HISTORICAL — DO NOT USE FOR RUNTIME**
>
> Archived 2026-07-13. Product / strategy brainstorm (2026-07-08), not an ops or sync spec.
> Decision runtime: **`docs/DECISION_LAYER.md`** + **`docs/CURRENT_RUNTIME.md`**.
> AI agents: **do not load this file** unless the user asks for historical product notes.

# AI 資安商業化與 Decision Layer 討論整理

> 日期：2026-07-08

## 一、是否值得訓練資安 AI 模型？

### 結論

值得，但**不建議從零開始訓練大型語言模型（LLM）**。

更有價值的方向是建立：

-   Security Decision Model
-   Security Decision Intelligence
-   Autonomous Security Decision Platform

真正的競爭力來自：

-   Decision Logic
-   Dataset
-   Workflow
-   Domain Knowledge

而不是模型本身。

------------------------------------------------------------------------

## 二、目前 GPT / Gemini / Claude 是否已經能做到？

答案：**可以做到大部分事件分析。**

例如：

-   EDR Alert
-   Windows Event
-   Sysmon
-   Zeek
-   Suricata
-   PowerShell
-   MITRE Mapping
-   IOC 萃取
-   Root Cause 推論
-   Timeline 建立

因此：

``` text
Raw Data
    ↓
GPT
    ↓
事件分析
```

並不是商業護城河。

------------------------------------------------------------------------

## 三、真正的價值在哪裡？

真正價值不是 AI 回答了什麼，而是：

> AI 做出了什麼決策。

例如：

-   是否隔離主機
-   是否通知客戶
-   是否升級 L2
-   是否需要 IR
-   是否符合 SLA
-   是否符合企業 Policy
-   是否影響關鍵系統

這些都屬於：

**Decision Layer**

------------------------------------------------------------------------

## 四、Decision Layer 是什麼？

Decision Layer 是一個可驗證、可稽核、可持續改善的決策引擎。

例如：

``` yaml
PowerShell:
    EncodedCommand: true
    AMSI_Block: true
    Parent: winword.exe

Decision:
    Confidence: 96%
    Severity: High
    Escalate: true
    Isolation: true
    NotifyCustomer: true
    Playbook: PS-003
```

AI 負責理解。

Decision Layer 負責決策。

------------------------------------------------------------------------

## 五、Knowledge Layer

Decision Layer 所需要的知識：

-   MITRE ATT&CK
-   D3FEND
-   Sigma
-   YARA
-   CVE
-   Threat Intelligence
-   Playbook
-   Jira
-   CMDB
-   AD
-   Firewall
-   歷史案件

這些透過檢索取得，而不是依賴 LLM 記憶。

------------------------------------------------------------------------

## 六、AI 放在哪裡？

建議流程：

``` text
Raw Event
    ↓
AI (Normalization)
    ↓
Decision Layer
    ↓
Knowledge Retrieval
    ↓
AI (Reasoning)
    ↓
Decision Layer
    ↓
AI (Report Generation)
```

AI 是協助者。

Decision Layer 才是核心。

------------------------------------------------------------------------

## 七、是否需要自己的 AI？

### 第一階段

直接使用 GPT / Gemini API。

目的：

驗證市場。

------------------------------------------------------------------------

### 第二階段

開始累積自己的 Dataset。

保存：

-   Raw Alert
-   AI 分析
-   人工修正
-   最終 Root Cause
-   Response
-   Outcome

------------------------------------------------------------------------

### 第三階段

再進行：

-   LoRA
-   Fine-tune
-   Qwen
-   Llama
-   Mistral

目標不是聊天，而是：

Decision Model。

------------------------------------------------------------------------

## 八、產品 Roadmap

### v0.1

GPT API

↓

事件分析

↓

JSON

------------------------------------------------------------------------

### v0.2

Decision Engine

-   Rule
-   Playbook
-   SLA
-   Jira Workflow

------------------------------------------------------------------------

### v0.3

Knowledge Layer

-   MITRE
-   IOC
-   Threat Intel
-   歷史案件
-   CMDB

------------------------------------------------------------------------

### v0.4

Agent

自動：

-   查 EDR
-   查 AD
-   查 Firewall
-   查 DNS
-   查 Jira

完成 Decision。

------------------------------------------------------------------------

### v1.0

建立：

Security Decision Dataset。

------------------------------------------------------------------------

### v2.0

Fine-tune：

Security Decision Model。

------------------------------------------------------------------------

## 九、Decision Dataset（核心資產）

建議每個事件保存：

``` yaml
alert:
  source: Stellar Cyber
  type: Credential Dumping

asset:
  criticality: High

customer:
  industry: Banking

decision:
  escalation: L2
  notify_customer: true
  isolate_host: false

playbook:
  id: PB-012

outcome:
  true_positive: true
```

這種 Dataset 將成為未來：

-   AI 微調
-   Decision Engine
-   商業授權
-   SaaS
-   OEM

的重要基礎。

------------------------------------------------------------------------

## 十、建議的最終產品定位

不是：

> AI SOC

而是：

> Autonomous Security Decision Platform

架構：

``` text
EDR / SIEM / Firewall / Email / Identity
                    │
                    ▼
          Event Normalization
                    │
                    ▼
            Correlation Engine
                    │
                    ▼
             Decision Layer
        ├── Risk Score
        ├── MITRE
        ├── Playbook
        ├── SLA
        ├── Escalation
        ├── Automation
        └── Compliance
                    │
                    ▼
          GPT / Gemini / Qwen
        ├── Explain
        ├── Reason
        ├── Report
        └── Analyst Chat
```

------------------------------------------------------------------------

## 十一、最重要的結論

真正的產品不是 AI。

真正的產品是：

-   Decision Logic
-   Decision Dataset
-   Knowledge Layer
-   Workflow
-   Playbook

LLM 可以替換。

Decision Intelligence 才是核心競爭力。
