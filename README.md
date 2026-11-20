# skill-scout

给 AI 编码代理（DSH / Claude Code / Codex CLI 等）**找、审、装** GitHub 上的 agent skill 的三个小脚本。

装技能这件事真正花时间的不是下载，是三件事：这个仓库到底有没有 SKILL.md、里面的代码危不危险、license 能不能搬。这三个脚本把机械部分包掉，判断留给你。

## 为什么需要它

在 GitHub 上找 skill 有三个坑：

1. **`topic:agent-skills` 里大量空壳**——挂了 topic，仓库里却没有 SKILL.md。
2. **集合仓库**——根目录没有 SKILL.md，十几个技能各占一个子目录，按仓库为单位装就抓瞎。
3. **危险调用没人看**——`curl | bash`、`Invoke-Expression`、`eval(远程输入)` 就躺在 `scripts/` 里。

`search.py` 治第 1 个，`install.py` 治第 2、3 个，并且在你看完扫描结果之前**什么都不装**。

## 安装

不需要 pip 安装。把三个脚本复制到任何地方即可，只依赖 Python 3.8+ 标准库。

```bash
git clone https://github.com/<you>/skill-scout.git
cd skill-scout
python search.py --help
```

作为 agent skill 使用时，把整个目录放进技能库（例如 `~/.agents/skills/skill-scout`），`SKILL.md` 里的 frontmatter 让代理在"找个技能装一下"时自动加载。

## 用法

### 1. 找

```bash
python search.py --topic agent-skills --limit 8 --check-skill
python search.py --code 'path:SKILL.md pdf'          # 最准，需要 GH_TOKEN
python search.py --skill-of owner/repo               # 单仓体检
python search.py --repo-query '"pdf" "skill" in:name,description'
```

| 参数 | 说明 |
| --- | --- |
| `--topic T` | 按 GitHub topic 搜仓库 |
| `--repo-query Q` | 原样传 GitHub 仓库搜索语法 |
| `--code Q` | 代码搜索，GitHub 要求登录（`GH_TOKEN`） |
| `--skill-of O/R` | 单仓体检：SKILL.md 路径、license、默认分支、tar 地址 |
| `--check-skill` | 逐个问 trees API 真的有几个 SKILL.md（1 请求/仓库） |
| `--min-stars N` | 过滤低星 |
| `--json` | 机器可读输出 |

`--check-skill` 值得常开：不加它，`topic:agent-skills` 前十里会混进好几个没有 SKILL.md 的仓库。

### 2. 审（默认行为）

```bash
python install.py owner/repo                  # 下载 + 解包 + 扫描 + 报告，然后停
python install.py owner/repo --skill deep-read  # 集合仓库里挑一个
```

输出四段：文件树（含每个文件大小）、SKILL.md 的 description 字数、危险调用扫描（HIGH/MED/LOW，带 `文件:行号`）、白名单会拷哪些。报告同时落到 `reports/<repo>__<skill>-<时间>.json`。

### 3. 装

```bash
python install.py owner/repo --apply
python install.py owner/repo --skill deep-read --apply --name my-name --dest ~/.agents/skills
```

### 4. 探本机

```bash
bash probe.sh     # 平台、解释器、依赖、venv、密钥变量名（只打印名字）
```

装完一个需要依赖的技能，把 `probe.sh` 的输出和真实冒烟测试结果写进该技能 SKILL.md 末尾的 `## On this machine`。

## 设计约定

- **默认只审不装。** 不带 `--apply` 绝不写技能库。
- **白名单拷贝，不是镜像。** 只拿 `SKILL.md` / `LICENSE*` / `README*` / `pyproject.toml` / `requirements.txt` 和 `scripts/ references/ assets/ templates/ bin/`；`tests/ docs/ evals/ .github/ node_modules/` 全跳过。
- **从不执行仓库代码。** 只做文件操作，不 import 被装的脚本，不跑安装脚本。
- **不 `git clone`。** 下 tar 包，避免 `.git`、hooks、submodule 一起进来。
- **解包做路径穿越校验**，并拒绝符号链接/硬链接/设备文件（Python 3.12+ 走 `filter="data"`）。
- 有 HIGH 命中且没 `--force`，拒绝拷贝。目标目录已存在也拒绝覆盖。
- 只用标准库；TLS 失败时自动降级重试一次（Windows `curl.exe` 的 Schannel 证书链问题绕开）。

## 已知平台差异

- **Windows**：`python3` 可能是 Microsoft Store 占位程序，执行它会拉起商店。用 `python`；`probe.sh` 会识别并**不执行**它。
- 传给 Python 的路径用 `C:/Users/...`；MSYS 的 `/c/Users/...` Python 不认。
- pip 默认源在某些网络下会挂，装依赖用镜像：`-i https://pypi.tuna.tsinghua.edu.cn/simple`。
- 集合仓库的默认分支可能是 `master`，脚本会自动问 API，不用手填。

## License

MIT