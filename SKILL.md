---
name: skill-scout
description: 从 GitHub 找、审、装 agent 技能：按 topic 或代码搜索定位仓库、下载前扫描危险调用、白名单拷贝进技能库。用于用户说"找个技能装一下""这个 GitHub 技能能不能用""从仓库装 skill""有没有现成的技能做 X"，或要批量评估技能仓库时。
---

# skill-scout

从 GitHub 拿技能进来。**机械步骤交给脚本，判断留给自己。**

装技能这件事真正花 token 的不是下载，是"这个能不能用、跟已装的有没有重叠、license 能不能搬"。所以脚本只做四件机械活：查、下、扫、拷。剩下三件事必须自己判断。

## 什么时候用

- 用户说"找个技能""装个 skill""这个 GitHub 能不能用""有没有现成技能做 X"。
- 已经有一个仓库地址，要评估它值不值得装。
- 要盘点某个仓库里有哪几个技能（集合仓库）。

**不用**的时候：只是读一份文档（那是 markitdown / mineru / docling 的事），或者在写自己的技能（照本技能末尾"安装纪律"做就行，不用跑脚本）。

## 三件套

脚本都在本技能目录里，只用 Python 标准库，不需要装依赖：

```bash
SC="$HOME/.agents/skills/skill-scout"     # Windows: C:/Users/<你>/.agents/skills/skill-scout
python "$SC/search.py"  ...               # 查
python "$SC/install.py" ...               # 审 + 装
bash   "$SC/probe.sh"                     # 探本机
```

## 流程

### 1. 查

```bash
python "$SC/search.py" --topic agent-skills --limit 8 --check-skill
python "$SC/search.py" --code 'path:SKILL.md pdf'        # 最准，要 GH_TOKEN
python "$SC/search.py" --skill-of owner/repo             # 单仓体检
python "$SC/search.py" --repo-query '"pdf" "skill" in:name,description'
```

`--check-skill` 会真去翻仓库树，过滤掉"挂了 topic 但其实没有 SKILL.md"的仓库——`topic:agent-skills` 里这类占了相当比例，不加它容易拿到一堆空壳。

看得懂的字段：`stars`、`license`（`-` 表示无 SPDX 声明，只能参考不能搬）、`pushed`（多久没动）、`skill.md`（有几个）。

### 2. 审

```bash
python "$SC/install.py" owner/repo                 # 默认只审不装
python "$SC/install.py" owner/repo --skill NAME    # 集合仓库里挑一个
```

它会：下 tar 包 → 安全解包（拒绝路径穿越、符号链接）→ 列文件树和 SKILL.md 的 description 字数 → 按 HIGH/MED/LOW 报危险调用 → 打印白名单会拷哪些 → **停下**。

要读的东西只有三样：
1. **扫描命中**：HIGH 必须逐条看懂（`curl|bash`、`Invoke-Expression`、`eval(远程输入)`、`rm -rf /`）。有 HIGH 且讲不通，就别装。
2. **description 字数**：超过 400 字符就是在每轮对话里持续收费，能砍就砍。
3. **文件树**：`SKILL.md` 之外还有什么。`scripts/` 里的东西会被执行，`references/` 只是被读。

### 3. 装

```bash
python "$SC/install.py" owner/repo --apply
python "$SC/install.py" owner/repo --skill deep-read --apply --name 自定义名
```

拷的是**白名单**，不是镜像：`SKILL.md` / `LICENSE*` / `README*` / `pyproject.toml` / `requirements.txt` 加 `scripts/ references/ assets/ templates/ bin/`。`tests/ docs/ evals/ .github/ node_modules/` 全跳过。目标已存在会拒绝，要覆盖加 `--force`。

报告落在技能目录 `reports/<repo>__<skill>-<时间>.json`，里面是完整扫描结果和拷贝清单。

### 4. 冒烟 + 写本机备注

装完**必须用真实文件跑一遍**它自己的命令，确认能出结果，再往 SKILL.md 末尾追加 `## On this machine`：解释器绝对路径、依赖装在哪个 venv、已知坑。没跑通就说没跑通。

```bash
bash "$SC/probe.sh"      # 采平台/解释器/依赖/密钥变量名，直接贴进备注
```

## 判断清单（这部分脚本替不了）

- **license**：有 SPDX（MIT / Apache-2.0 / BSD）才考虑拷进技能库；`-` 或自定义协议只能读思路。
- **重叠**：跟已装的技能是不是同一件事？两个做同一件事比没有更糟——模型会犹豫该用哪个。要装就先合并或归档旧的。
- **依赖**：要 venv 就建在技能目录内（`<skill>/.venv`），不要装进系统解释器。
- **体量**：description 是每轮的固定成本，正文是触发时的一次性成本。前者砍到 400 字符内，后者无所谓。
- **默认分支**：有的仓库默认分支是 `master`，`install.py` 会自动问 API，不用手填。

## 红线

- **不 `git clone`** 进技能库（会带 `.git`、hooks、submodule）。
- **不 `curl ... | bash`**，不跑仓库里的安装脚本。
- **不执行仓库代码**：`install.py` 只做文件操作，从不 import 或运行被装的脚本。
- 装之前不审就 `--apply`，等于把陌生人的代码放进每轮上下文。
- 别把技能装进系统解释器；别在没有 license 的仓库上花时间做适配。

## 平台注意（Windows / MSYS）

- `python3` 可能是 Microsoft Store 占位程序，执行它会弹商店。用 `python`。`probe.sh` 会把它标出来并跳过执行。
- 传给 Python 的路径用 `C:/Users/...` 或 `C:\\Users\\...`；MSYS 的 `/c/Users/...` Python 不认。
- `rm -rf` 越界会被安全网拦；删目录用 `python -c "import shutil; shutil.rmtree(r'C:/...')"`。
- pip 默认源可能挂，用 `-i https://pypi.tuna.tsinghua.edu.cn/simple`。
- Windows 自带 `curl.exe` 的 Schannel 证书链偶发失败，所以脚本统一走 Python urllib。**证书校验失败时直接报错退出，不降级为不校验**——请求里带 `GH_TOKEN`，裸连等于把 token 交给中间人。遇到这种错就换网络，或 `pip install certifi` 后把 `SSL_CERT_FILE` 指向它的 `cacert.pem`。

## On this machine

- 技能目录：`C:\Users\yangq\.agents\skills\skill-scout`（脚本就在本目录）。
- 解释器：`C:\Users\yangq\AppData\Local\Programs\Python\Python313\python.exe`（3.13.15）；`python3` 是 Store 占位程序，别用。
- 本机**没有** `gh`，也没有任何 git 凭据（无 `~/.git-credentials`、无 credential.helper）——要发布仓库只能走浏览器已登录的会话。
- `pdftotext` 缺席（无 poppler）；`ffmpeg 9.0.2`、`node 26.13.1`、`pnpm 11.28.5` 在。
- 已验证：`search.py --topic` / `--skill-of` / `--code 无 token 提示`、`install.py` 只审 / `--skill` 选择 / `--apply` 真拷 / 重复跑拒绝覆盖、`probe.sh` 全通过。