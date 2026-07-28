---
name: audit-dtc-store
description: 自动诊断 DTC、Shopify 或其他电商独立站是否达到基础合格标准，并生成中文优先级整改报告。用于接手旧站、投流前检查、网站体检、转化链路排查、广告落地页承接检查、SEO 基础审计、Core Web Vitals、移动端体验、支付、弃购机制与 Search Console 后台核验，或判断“独立站是否合格”。默认零 API、公开页面只读；需要后台证据时，让用户在真实浏览器中手动登录并执行授权只读检查。
---

# 独立站合格标准自动诊断

按“转化闭环 → 投流承接 → SEO 基础 → 移动端体验”的顺序诊断。先解决影响收入的硬伤，再处理流量积累和视觉优化。

## 安全边界

- 默认不要求 API Key，只读取公开页面，不登录后台、不提交表单、不创建账户、不生成弃购记录、不发送邮件或短信、不提交订单。
- 可以把商品加入本地浏览器购物车并打开 Checkout，但必须在填写联系方式、配送地址或付款信息之前停止。
- 后台验证必须使用用户控制的真实浏览器。打开登录页后暂停，让用户自行输入密码并完成 MFA；不要索取、读取、复述或保存凭证、Cookie、令牌或浏览器 Profile。
- 用户授权登录不等于授权修改。只读取广告后台、Shopify 和 Search Console；不得切换设置、启停自动化、修改广告或提交站点配置。
- 只有用户逐项确认并提供专用测试身份后，才提交测试联系方式、生成弃购记录或发送测试邮件/短信。此类行为属于 `authorized-side-effect`，不得标记为只读。
- 不支持创建账户或提交真实订单。即使已经登录后台，也不得越过 Checkout 安全停止点。
- 不把未验证项判为失败。标记为 `unknown`，同时报告覆盖率和需要补充的证据。
- 不把单次网络响应时间冒充 Core Web Vitals。区分静态响应、实验室数据和真实用户字段数据。

## 工作流

### 1. 明确输入

至少取得独立站 URL。尽量同时取得：

- 主要销售国家和移动端网络环境
- 广告落地页 URL
- 广告承诺或预期商品名称
- 是否允许把商品加入购物车并打开 Checkout
- 是否授权在真实浏览器中查看广告平台、Shopify 或 Search Console
- 是否提供专用测试邮箱或测试手机号，以及是否明确授权产生测试消息

缺少增强验证信息时，继续执行公开页面审计，不中断任务。

采用以下权限模式，并把实际模式写入证据：

- `public-readonly`：公开页面，不登录、不提交信息。
- `browser-authorized-readonly`：用户手动登录后，只读取后台。
- `authorized-side-effect`：经逐项确认后提交测试联系方式或触发测试消息。

### 2. 运行公开页面自动审计

执行：

```bash
python3 <SKILL_DIR>/scripts/audit_store.py \
  --url "https://example.com" \
  --out-dir "./outputs/example-audit"
```

有广告落地页和预期商品时增加：

```bash
python3 <SKILL_DIR>/scripts/audit_store.py \
  --url "https://example.com" \
  --landing-url "https://example.com/products/example" \
  --expected-product "Example Product" \
  --out-dir "./outputs/example-audit"
```

脚本只使用 Python 标准库，输出：

- `audit.json`：结构化证据与评分
- `report.md`：中文诊断报告

不要用静态 HTML 推断按钮是否“首屏明显”、移动端是否溢出或 Checkout 是否可用；这些属于增强检查。

### 3. 执行浏览器增强检查

需要完整诊断时：

1. 阅读 [references/enhanced-checks.md](references/enhanced-checks.md)，按手机视口检查公开页面与 Checkout 安全停止点。
2. 涉及 Core Web Vitals、广告后台、弃购或 Search Console 时，必须再阅读 [references/browser-authorized-checks.md](references/browser-authorized-checks.md)。
3. 优先复用用户已经登录的真实浏览器；否则打开官方登录页并暂停，等待用户手动完成登录和 MFA。
4. 登录后先确认账号、商店或 Search Console Property，再进行只读检查。
5. 后台启停状态只采信详情页、列表状态、明确开关/动作或平台设置；首页推荐卡、引导卡和任务卡只能用于发现入口，不能用于判定 `pass` 或 `fail`。

把结果保存为增强证据 JSON，再重新运行：

```bash
python3 <SKILL_DIR>/scripts/audit_store.py \
  --url "https://example.com" \
  --evidence-json "./enhanced-evidence.json" \
  --out-dir "./outputs/example-audit"
```

如果浏览器工具不可用，保留这些项目为 `unknown`，不要安装依赖或下载浏览器运行时，除非用户明确同意。

不要要求 API 配置。若公开 PageSpeed 页面返回 429，按以下顺序降级：

1. 读取浏览器中已有的 PageSpeed 结果或缓存结果。
2. 经授权读取 Search Console 的 Core Web Vitals 后台报告。
3. 运行本地移动端 Lighthouse，并标记为 `lab_only`；实验室结果不能独立证明真实 Core Web Vitals 合格。

### 4. 按评分规则做结论

始终阅读 [references/qualification-rubric.md](references/qualification-rubric.md)：

- 转化闭环：35 分
- 投流承接：30 分
- SEO 基础：20 分
- 移动端与基础体验：15 分

同时报告：

- 已验证评分
- 检测覆盖率
- 严格下限与潜在上限
- P0/P1/P2 问题
- `unknown` 项及补证方法

覆盖率低于 70% 时，只能给出“部分诊断”，不能下最终合格结论。任一 P0 项失败时，不得判为合格。

### 5. 交付整改顺序

按以下顺序排列行动：

1. P0：无法购买、Checkout 报错、支付缺失、移动端关键流程不可用
2. P1：落地页不匹配、加载慢、缺少信任元素或重要政策页、核心 SEO 缺失
3. P2：图片命名、次要元数据、非关键体验和视觉优化

每条问题必须包含证据 URL、观测结果、业务影响、修复建议与复测方法。禁止只输出泛泛的最佳实践。

报告必须如实显示是否登录后台、是否提交测试联系方式、是否触发消息。不得在执行过副作用测试后仍声称“全程只读”。

## 资源

- [references/qualification-rubric.md](references/qualification-rubric.md)：检查项、权重、合格判定和证据边界
- [references/enhanced-checks.md](references/enhanced-checks.md)：浏览器与授权增强检查
- [references/browser-authorized-checks.md](references/browser-authorized-checks.md)：Core Web Vitals、广告后台、弃购与 Search Console 的真实浏览器流程
- [assets/report-template.md](assets/report-template.md)：人工补充报告时使用的中文模板
- `scripts/audit_store.py`：公开页面只读审计与报告生成器
