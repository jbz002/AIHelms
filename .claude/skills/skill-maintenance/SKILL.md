---
name: skill-maintenance
description: 维护 AIHelms 平台上的 Skill 全生命周期：搜索、下载 zip、上传贡献、更新版本、提交发布审核与使用申请。只需一枚平台 API Key（ak-）即可完成全部操作，下载无需第二把 key。凡要在 AIHelms 上查 skill、拿 skill 包、贡献或迭代自己的 skill、提交资源申请，都必须用本 skill。
---

# 技能维护（AIHelms Skill 全生命周期操作）

## 依赖声明：只需平台 API Key

| Key | 前缀 | 用途 | 获取处 |
|-----|------|------|--------|
| 平台 API Key | `ak-` | **本文档全部操作**：搜索/详情/下载/上传/版本/提审/申请 | 管理端「平台 API Key」自建 |

**不需要个人 AI 资源 Key（sk-）**：下载端点 `/skills/{id}/zip` 直接接受平台 Key，带 `Authorization: Bearer $AK` 即可（2026-09-28 prod 实测）。`sk-` 通道仅作历史兼容保留。

## 基础约定

```bash
export AK="<平台API Key>"       # ak- 开头
export BASE="http://131.131.2.10:30700"   # 平台入口，API 前缀 /api/v1
```

- 认证：`Authorization: Bearer $AK`
- 查询类返回 `{"code":200,"message":"ok","data":{...}}`；写操作 `message` 为业务语义（前端 toast 文案，也用于判断结果，见上传章节）
- 贡献类接口为 `multipart/form-data`，其余为 JSON
- **平台 Key 的权限 = 创建者的角色权限**（实测：某 key 创建者仅有 `skill:contribute` 时，`/skills/{id}/download` 返回 403「权限不足」）。它不等于「最大权限」，遇到 403 先查创建者角色

## 1. 搜索 skill

```bash
curl -s -H "Authorization: Bearer $AK" \
  "$BASE/api/v1/skills/published?page=1&page_size=20"
```

- 仅返回已发布且对你有可见性的 skill；`category` 可选过滤
- 可见性两选（2026-09-28 起）：`all` 公开 / `department` 按部门——按部门的 skill 只对本部门成员出现在列表与直链
- 详情：`GET /api/v1/skills/{id}/market-detail`
- 安装信息：`GET /api/v1/skills/{id}/install-info` → 返回 `agent_prompt`（一句话安装指令）与 `download_url`（已内嵌你的主 Key token，可直接 curl）

## 2. 下载 skill zip

**推荐路径（ak- 直连，无需 sk-）**：

```bash
curl -s -o my-skill.zip -H "Authorization: Bearer $AK" "$BASE/api/v1/skills/{skill_id}/zip"
# 也支持把 key 放在 query 上
curl -s -o my-skill.zip "$BASE/api/v1/skills/{skill_id}/zip?token=$AK"
```

**备选路径**（默认不建议）：

```bash
# install-info 返回 data.download_url，形如 .../zip?token=sk-...
curl -s -H "Authorization: Bearer $AK" "$BASE/api/v1/skills/{skill_id}/install-info"
curl -s -o my-skill.zip "<data.download_url>"
```

三条路径的差异：

| | `/zip` + ak- | `/zip?token=sk-`（install-info） | `/download` |
|---|---|---|---|
| 凭证 | 平台 Key（请求头或 `?token=`） | URL 内嵌个人主 Key 明文 | 平台 Key |
| 已发布要求 | 要求 | 要求 | 不要求 |
| 审批绑定 | 校验 `requires_approval` + 创建者个人主 Key 的 skills 列表，未授权 403「请先申请使用该 Skill」；admin 创建的 ak- 直接放行 | 同左，按该 Key 自身的 skills 列表判 | 不校验 |
| 所需权限 | 无额外权限码（市场接口） | 无（凭 token） | `skill:read` |
| 计量口径 | 落到用户（`agent_download`），AI Key 列为空 | 落到具体 AI Key | 落到用户 |

⚠️ `install-info` 的 `download_url` 里 `token=` 是个人主 Key 明文，等同密钥，只适合贴给人手动用；自己有 ak- 时不要走这条，更不要写进公开文件、日志或仓库。

## 3. 上传 skill（贡献）

```bash
curl -s -X POST -H "Authorization: Bearer $AK" \
  -F "name=我的技能" \
  -F "description=一句话说明" \
  -F "category=通用" \
  -F "version=1.0.0" \
  -F "author=作者名" \
  -F "usage_instructions=使用说明" \
  -F "visibility_type=all" \
  -F "zip_file=@my-skill.zip" \
  "$BASE/api/v1/contributor/skills"
```

- 权限码 `skill:contribute`（全员开放；走跨应用兼容鉴权，AI Hub 凭证亦可）
- **发布态由平台发布门控自决**，看返回 message 判断：
  - 「Skill 已上传并发布」→ 门控关，已直接上架
  - 「Skill 已上传并提交发布审核」→ 门控开，处于待审
- 上传即自动激活 v1；`requires_approval` 为 false（不再强制走使用审批）
- `visibility_type` 只接受 `all` / `department`；不传则按创建者部门默认（无部门即 `all`）
- 名称重复 → 409「Skill 名称 'xxx' 已存在」（上传前先 `GET $BASE/api/v1/contributor/skills` 查已有贡献防撞名）
- 必须有 zip 或 `source_url`（Git 仓库地址，平台代拉）
- zip 结构：顶层目录 `<frontmatter.name>/SKILL.md`，frontmatter 必含 `name`、`description`（建议 ≤200 字，超长仅 warning）；物理校验失败整包 400 不落盘

**打 zip（本地目录 → 上传包）**：

```bash
# 用 python 打包最稳：条目名正斜杠、结构可控
# （PowerShell Compress-Archive 的 zip 条目名是反斜杠，协议校验可能不过）
python -c "
import zipfile
with zipfile.ZipFile('my-skill-1.0.0.zip', 'w', zipfile.ZIP_DEFLATED) as z:
    z.write('skill-xxx/SKILL.md')     # 相对路径，顶层目录 = frontmatter.name
"
```

**上传后回验（下载回包再开箱）**：

```bash
curl -s -o verify.zip -H "Authorization: Bearer $AK" "$BASE/api/v1/skills/{skill_id}/zip"
python -c "
import zipfile
print(zipfile.ZipFile('verify.zip').namelist())   # 期望 ['<frontmatter.name>/SKILL.md']
"
```

- 上传响应里 `headline_version.is_active:false` / `active_version:null` 可能与实际发布态不符（实测已发布、可正常下载）；是否上架以 message + `/zip` 下载 200 为准
- Git Bash 里 Windows python 打不开 `/tmp/...` 虚拟路径——回验文件放当前目录，或路径写 `$(cygpath -w verify.zip)`

## 4. 更新 / 版本管理

查自己的贡献与版本：

```bash
curl -s -H "Authorization: Bearer $AK" "$BASE/api/v1/contributor/skills"
curl -s -H "Authorization: Bearer $AK" "$BASE/api/v1/contributor/skills/{skill_id}/versions"
```

改元数据（已发布则 409「已发布的 Skill 不可编辑，如需修改请新建版本」）：

```bash
curl -s -X PUT -H "Authorization: Bearer $AK" \
  -F "description=新描述" "$BASE/api/v1/contributor/skills/{skill_id}"
```

上传新版本，**自动激活**（激活版本即市场可见与可下载的唯一版本）：

```bash
curl -s -X POST -H "Authorization: Bearer $AK" \
  -F "version=1.0.4" \
  -F "version_label=简要标签" \
  -F "change_log=变更内容" \
  -F "zip_file=@my-skill.zip" \
  "$BASE/api/v1/contributor/skills/{skill_id}/versions"
# → message「Skill 版本已上传并激活」
```

多版本共存时可手动切换激活版本（owner 权限，无需 admin）：

```bash
curl -s -X POST -H "Authorization: Bearer $AK" \
  "$BASE/api/v1/contributor/skills/{skill_id}/versions/{version_id}/activate"
```

- 已发布的 skill 不能删（409），元数据也不能改——迭代只能靠新版本

## 5. 提交发布审核

```bash
curl -s -X POST -H "Authorization: Bearer $AK" \
  "$BASE/api/v1/contributor/skills/{skill_id}/submit-review"
```

- 门控关时上传已直接发布，无需此步；重复提 → 409「Skill 已发布，无需重复提交审核」
- 门控开时上传会**自动**提审，也不必手动再提（会撞 409「该资源已有待审核的发布申请」）
- 审核通过/驳回归 admin（`publish_review:approve`）

## 6. 提交使用申请

```bash
curl -s -X POST -H "Authorization: Bearer $AK" \
  -H "Content-Type: application/json" \
  --data-binary @body.json "$BASE/api/v1/resource-applications"
# body.json: {"resource_type":"skill","resource_id":7,"reason":"用途","request_config":{}}
```

- `resource_type` ∈ `model` / `mcp` / `skill` / `agent`
- 同一资源已有 pending 申请 → 409「已存在未处理的申请」
- 审批通过后资源授权到**个人主 Key**，该 Key 才能下载需审批的 skill
- 查进度：`GET /api/v1/resource-applications/my`

## 实测坑汇总

1. **未发布的 skill 下载不了**：`/zip` 只认已发布版本（草稿 404，任何 key 都一样）——贡献后自测要等发布/激活
2. **Windows curl 中文乱码（高发）**：Git Bash / Windows 下 `curl -F "name=中文"` 的表单值按本地 GBK 编码发出，服务端按 UTF-8 解析成 mojibake 落库；`-d` JSON 同理
   - 修法：字段值先写 UTF-8 文件，用 `-F "name=<C:/path/f.txt"`（`<` 让 curl 读文件原始字节）；JSON 用 `--data-binary @C:/path/body.json`
   - `category=通用` 这类看着像枚举常量的中文值同样中招——**所有含中文的表单字段一律文件化**
   - zip 内文件不受影响（二进制传输）
3. 元数据（name/description 等）用 PUT 改；zip 内容只能走「新版本」接口换包
4. zip 顶层目录名与 frontmatter `name` 保持一致，避免协议校验报错
5. `/skills/published`、`/market-detail` 走跨应用兼容鉴权（自有 JWT / 平台 Key / AI Hub 凭证均可）
6. 平台 Key 权限继承创建者角色，别假设它是 superuser；只有 `skill:contribute` 的角色照样能搜市场、能用 `/zip` 下载（下载不校验权限码）
7. 下载报「AI Key 无效」类错误，先确认服务端版本：2026-09-28 起 `/zip` 才接受 ak-
8. **`AK=xxx curl -H "Authorization: Bearer $AK"` 前缀赋值坑**：`VAR=x cmd` 的赋值不参与本行参数展开，`$AK` 展开为空 → 401「未提供认证 token」。必须先 `export AK=...` 再用（key 内联亦行）
