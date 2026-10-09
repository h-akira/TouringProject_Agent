# TouringProject_Agent — AgentCore のエージェント

ツーリング AI 会話アプリのエージェント（Bedrock AgentCore Runtime ＋ Strands・`us-east-1`）。会話の保持・回答の生成・Web 検索を担う。
[TouringProject](https://github.com/h-akira/TouringProject) の submodule。

| 見たいもの | 場所 |
|---|---|
| 設計 | [docs/](docs/README.md) |
| プロジェクト全体の要件と契約 | [docs-parent/](docs-parent/README.md)（親リポジトリの写し。編集しない） |
| AI 向けの規約 | [AGENTS.md](AGENTS.md) |

## TouringProject での使い方

- デプロイは Backend より先に行う。手元で `agentcore deploy` したら、Runtime の ARN を東京の SSM（`/trg/<env>/agent-runtime-arn`）に書く。ARN が変わったら Backend も再デプロイする。

  ```sh
  AWS_REGION=us-east-1 agentcore deploy -y
  AGENT_ARN=$(AWS_PROFILE=touring aws bedrock-agentcore-control list-agent-runtimes \
    --region us-east-1 --query 'agentRuntimes[0].agentRuntimeArn' --output text)
  AWS_PROFILE=touring aws ssm put-parameter --name /trg/dev/agent-runtime-arn \
    --value "$AGENT_ARN" --type String --overwrite --region ap-northeast-1
  ```

- `agentcore/aws-targets.json` はアカウント ID を含むので追跡しない。雛形は `aws-targets-sample.json`（実 ID を入れてリネームして使う）。
- デプロイせずに手元で質問を通すには `scripts/ask_local.py` を使う。Backend と同じ形のプロンプトとペイロードを組み、本物の LLM（Bedrock）とツールで答えさせ、呼ばれたツールと回答を表示する。座標は公共のランドマークだけを使う。

  ```sh
  cd app/agentcore_trg_dev_ask
  eval "$(aws configure export-credentials --profile touring --format env)"
  .venv/bin/python ../../scripts/ask_local.py "右手に見える公園は？" \
    --lat 35.6812 --lon 139.7671 --heading 0 --address 東京都千代田区丸の内
  ```

以下は `agentcore` CLI が生成した説明。

This project was created with the [AgentCore CLI](https://github.com/aws/agentcore-cli).

## Project Structure

```
my-project/
├── AGENTS.md               # AI coding assistant context (TouringProject's own)
├── agentcore/
│   ├── agentcore.json      # Project config (agents, memories, credentials, gateways, evaluators)
│   ├── aws-targets.json    # Deployment targets (account + region)
│   ├── .env.local          # Secrets — API keys (gitignored)
│   ├── .llm-context/       # TypeScript type definitions for AI assistants
│   │   ├── agentcore.ts    # AgentCoreProjectSpec types
│   │   ├── aws-targets.ts  # Deployment target types
│   │   └── mcp.ts          # Gateway and MCP tool types
│   └── cdk/                # CDK infrastructure (@aws/agentcore-cdk)
├── app/                    # Agent application code
└── evaluators/             # Custom evaluator code (if any)
```

## Getting Started

### Prerequisites

- **Node.js** 20.x or later
- **Python 3.10+** and **uv** for Python agents ([install uv](https://docs.astral.sh/uv/getting-started/installation/))
- **AWS credentials** configured (`aws configure` or environment variables)
- **Docker** (only for Container build agents)

### Development

Run your agent locally:

```bash
agentcore dev
```

### Deployment

Deploy to AWS:

```bash
agentcore deploy
```

## Commands

| Command | Description |
| --- | --- |
| `agentcore create` | Create a new AgentCore project |
| `agentcore add` | Add resources (agent, memory, credential, gateway, evaluator, policy) |
| `agentcore remove` | Remove resources |
| `agentcore dev` | Run agent locally with hot-reload |
| `agentcore deploy` | Deploy to AWS via CDK |
| `agentcore status` | Show deployment status |
| `agentcore invoke` | Invoke agent (local or deployed) |
| `agentcore logs` | View agent logs |
| `agentcore traces` | View agent traces |
| `agentcore eval` | Run evaluations |
| `agentcore package` | Package agent artifacts |
| `agentcore validate` | Validate configuration |
| `agentcore pause` | Pause a deployed agent |
| `agentcore resume` | Resume a paused agent |
| `agentcore fetch` | Fetch remote resource definitions |
| `agentcore import` | Import existing resources |
| `agentcore update` | Check for CLI updates |

## Configuration

Edit the JSON files in `agentcore/` to configure your project. See `agentcore/.llm-context/` for type definitions and validation constraints.

The project uses a **flat resource model** — agents, memories, credentials, gateways, evaluators, and policies are top-level arrays in `agentcore.json`. Resources are independent; agents discover memories and credentials at runtime via environment variables or SDK calls.

## Resources

| Resource | Purpose |
| --- | --- |
| Agent (runtime) | HTTP, MCP, or A2A agent deployed to AgentCore Runtime |
| Memory | Persistent context storage with configurable strategies |
| Credential | API key or OAuth credential providers |
| Gateway | MCP gateway that routes tool calls to targets |
| Gateway Target | Tool implementation (Lambda, MCP server, OpenAPI, Smithy, API Gateway) |
| Evaluator | Custom LLM-as-a-Judge or code-based evaluation |
| Online Eval Config | Continuous evaluation pipeline for deployed agents |
| Policy | Cedar authorization policies for gateway tools |

### Agent Types

- **Template agents**: Created from framework templates (Strands, LangChain/LangGraph, GoogleADK, OpenAI Agents, Autogen)
- **BYO agents**: Bring your own code with `agentcore add agent --type byo`
- **Import agents**: Import existing Bedrock agents with `agentcore import`

### Build Types

- **CodeZip**: Python source packaged as a zip and deployed directly to AgentCore Runtime
- **Container**: Docker image built via CodeBuild (ARM64), pushed to ECR, and deployed to AgentCore Runtime

## Documentation

- [AgentCore CLI](https://github.com/aws/agentcore-cli)
- [AgentCore CDK Constructs](https://github.com/aws/agentcore-l3-cdk-constructs)
- [Amazon Bedrock AgentCore](https://aws.amazon.com/bedrock/agentcore/)
