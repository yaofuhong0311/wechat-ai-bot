# wechat-ai-bot

一个微信群 AI 助手框架，基于 [Claude Agent SDK](https://docs.claude.com/en/api/agent-sdk/overview) 和 [wkteam](https://wkteam.cn) 微信网关。

> English README: [README.md](README.md)

Bot 常驻在微信群里，被 @ 时响应。能做：

- 结合近期群消息上下文回答问题
- 解析图片、文件（PPT/Word/Excel 通过 skill）、合并转发的聊��记录、引用消息、分享链接
- 跨会话记忆：群级对话历史 + 每个用户的画像
- 通过 headless 浏览器抓取动态网页（B站等，小红书需要登录态无法直接抓）
- 通过 Claude 的 Bash 工具调任意 shell 命令做群管理（发公告、@所有人、改群名等）

## 架构

```mermaid
flowchart LR
    WX[微信群] -->|消息| WK[wkteam 网关]
    WK -->|webhook| APP[FastAPI /sync]
    APP --> REC[写入缓冲<br/>+ 下载媒体]
    REC --> AT{"@bot 了?"}
    AT -->|否| END1[结束]
    AT -->|是| CTX[组装上下文]

    USR[(users/{wxid}.md<br/>用户档案)] --> CTX
    GRP[(groups/history.jsonl<br/>+ summary.md)] --> CTX
    BUF[(实时缓冲<br/>最近20条群消息)] --> CTX

    CTX --> CC[Claude Agent SDK]
    CC -->|工具| TOOLS["WebFetch / WebSearch<br/>Bash / Read / Write"]
    CC -->|回复| SEND[发送到微信]
    SEND --> SAVE[保存问答到 history]
    SAVE --> EXT[异步提取<br/>更新用户档案]
    SAVE --> COMP{history > 100?}
    COMP -->|是| COMP2[压缩成 summary]
```

每次 @bot 都会触发一次新的 Agent SDK 调用。Bot 跑在容器里，拥有 Read/Write/Bash/WebFetch/WebSearch 等工具，还能加载 `.agents/skills/` 下的自定义 skill。

## 记忆系统

两层持久化记忆：

**群级**（`/memory/groups/{group_id}/`）
- `history.jsonl` — 原始问答日志，每次追加
- `summary.md` — 长期摘要。超过 100 条时压缩，超过 5000 字时再压缩一轮

**用户级**（`/memory/users/{wxid}.md`）
- CC 自己维护的自由文本档案
- system prompt 要求 CC 学到用户关键信息（体重、路线、偏好等）时更新档案
- 对话结束后会再跑一次强制提取兜底

## 快速开始

### 准备

- 一个 wkteam 账号，拿到 API 凭证并登录一个微信实例
- 一个 wkteam 能访问到的公网 URL（本地开发用 [ngrok](https://ngrok.com)，生产用 Ingress）
- Anthropic Console 拿 `ANTHROPIC_API_KEY`
- Docker & Docker Compose

### 本地运行

```bash
git clone https://github.com/<your-org>/wechat-ai-bot.git
cd wechat-ai-bot
cp .env.example .env
# 填入 WKTEAM_*、BOT_WCID、ANTHROPIC_API_KEY、ALLOWED_GROUPS

docker compose up --build
```

把本地服务暴露出去：

```bash
ngrok http 8000
```

然后到 wkteam 后台把 callback 设为：

```
https://<ngrok-url>/deploy/sync-api/v1/sync
```

之后在 `ALLOWED_GROUPS` 里的群 @bot，看它有没有回复。

### 生产部署（K8s）

参考 `k8s/manifest.yaml`。关键点：

- 用 PVC 挂载 `/project/memory`
- 密钥用 Secret 注入
- Ingress 带 TLS，路径指向 `/deploy/sync-api/v1/sync`

## 配置

全部通过环境变量。见 `.env.example`：

| 变量 | 必填 | 说明 |
|---|---|---|
| `WKTEAM_API_URL` | 是 | wkteam 网关地址 |
| `WKTEAM_TOKEN` | 是 | wkteam 认证 token |
| `WKTEAM_WID` | 是 | wkteam 微信实例 ID |
| `BOT_WCID` | 是 | bot 的微信 wxid（用来识别 @mention） |
| `ANTHROPIC_API_KEY` | 是 | 传给 Claude SDK 子进程 |
| `ANTHROPIC_BASE_URL` | 否 | 自建或代理的 API endpoint |
| `ALLOWED_GROUPS` | 否 | 白名单群 ID，逗号分隔；空=所有群 |
| `WEBHOOK_SECRET` | 否 | webhook 路径的随机字符串 |

## 定制行为

### 改 system prompt

直接编辑 `prompts/system.md`，启动时从文件读，不用改代码。prompt 定义 bot 的人设、边界、工具用法。

### 装 skill

Skill 装到 `.agents/skills/` 下，通过 `setting_sources=["project"]` 自动加载。装一个：

```bash
npx skills add https://github.com/anthropics/skills --skill <name>
```

每个 skill 是独立目录，里面有 `SKILL.md` 描述什么时候用、怎么用。

### 动态网页抓取

`scripts/fetch_page.py` 用 Playwright 渲染 JS 密集型页面（B站、SPA 等），返回纯文本。CC 通过 Bash 调：

```bash
python /project/scripts/fetch_page.py <url>
```

**小红书注意**：列表页能抓，但详情页强制登录，无解。需要维护登录态 cookie 或接第三方服务。

## 项目结构

```
wechat-ai-bot/
├── README.md / README.zh-CN.md
├── .env.example
├── .gitignore
├── Dockerfile
├── docker-compose.yml
├── requirements.txt
├── app/
│   ├── main.py          # FastAPI webhook + 消息路由
│   ├── config.py        # 读环境变量
│   ├── wechat.py        # wkteam API 客户端
│   ├── llm.py           # Claude Agent SDK 封装
│   └── memory.py        # 两层记忆系统
├── prompts/
│   └── system.md        # bot 的 system prompt
├── scripts/
│   └── fetch_page.py    # headless 浏览器抓取
├── k8s/
│   └── manifest.yaml    # kubernetes 部署模板
└── docs/                # 设计文档
```

## 常见问题

**Q: 为啥要 wkteam？**  
A: 微信官方不对个人账号开放接口。wkteam 做的是协议逆向，把微信消息转成 HTTP webhook。这是目前唯一能让个人号变成 bot 的方案。

**Q: 会不会被封号？**  
A: 有风险。长期挂机、频繁发消息、行为机械化都会触发风控。建议用小号、控制发送频率、保持"像人"的作息。

**Q: 能同时服务多个群吗？**  
A: 能。`ALLOWED_GROUPS` 支持多个群 ID，每个群有独立的 memory。

**Q: 记忆会越来越大吗？**  
A: 不会。有两级压缩：对话 → 摘要 → 精华。群摘要上限 5000 字，用户画像上限 2000 字。

## License

MIT
