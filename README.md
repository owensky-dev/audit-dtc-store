# 独立站合格标准自动诊断 Skill

`audit-dtc-store` 用于诊断 DTC、Shopify 或其他电商独立站是否达到基础合格标准，并生成中文优先级整改报告。

它按照“转化闭环 → 投流承接 → SEO 基础 → 移动端体验”的顺序检查，优先发现影响购买、广告承接和自然流量积累的硬伤。

## 主要能力

- 检查首页、商品页、购物车和 Checkout 是否可访问。
- 验证 Guest Checkout、支付方式和三步付款链路。
- 检查移动端首屏商品、CTA、错位、溢出和遮挡。
- 检查广告商品、优惠、市场、最终 URL 与落地页是否一致。
- 检查 Core Web Vitals，并区分字段数据、实验室数据和普通网络响应。
- 检查 Title、Meta Description、Canonical、Sitemap、图片 Alt 和 Product 结构化数据。
- 检查 Shipping Policy、Refund Policy 和联系入口。
- 经客户授权后，在真实浏览器中只读核验 Google Ads、Shopify 和 Search Console。
- 输出已验证评分、覆盖率、严格下限、潜在上限以及 P0/P1/P2 问题。

## 安全边界

- 默认只读取公开页面，不要求 API Key。
- 后台登录由客户自行输入密码并完成 MFA。
- 登录授权默认只读，不代表允许修改广告、网站或自动化设置。
- 不读取或保存密码、验证码、Cookie、访问令牌或浏览器 Profile。
- 不创建账户、不提交订单、不填写真实付款资料。
- 未经逐项授权，不提交测试联系方式、不生成弃购记录、不发送测试邮件或短信。
- 无法验证的项目标记为 `unknown`，不会直接判为失败。

## 安装

```bash
git clone https://github.com/owensky-dev/audit-dtc-store.git
cp -R audit-dtc-store ~/.codex/skills/audit-dtc-store
```

重启或重新加载 Codex 后即可使用。

## 使用示例

在 Codex 中输入：

```text
使用 $audit-dtc-store 对 https://example.com 进行只读独立站合格标准诊断
```

需要后台证据时，可以补充：

```text
允许在我已登录的真实浏览器中，只读查看 Google Ads、Shopify 和 Search Console。
```

客户应自行完成登录和 MFA，不要把密码或验证码发给 Agent。

## 直接运行公开审计

```bash
python3 scripts/audit_store.py \
  --url "https://example.com" \
  --out-dir "./outputs/example-audit"
```

如需初步检查指定广告落地页：

```bash
python3 scripts/audit_store.py \
  --url "https://example.com" \
  --landing-url "https://example.com/products/example" \
  --expected-product "Example Product" \
  --out-dir "./outputs/example-audit"
```

脚本只使用 Python 标准库，不依赖 PyYAML。

## 输出文件

- `audit.json`：结构化证据、检查状态和评分。
- `report.md`：中文诊断报告和整改优先级。

增强检查可通过 `--evidence-json` 导入真实浏览器、后台授权、用户导出或本地实验室证据。

## 评分结构

| 模块 | 权重 |
|---|---:|
| 转化闭环 | 35 |
| 投流承接 | 30 |
| SEO 基础 | 20 |
| 移动端与基础体验 | 15 |

任一 P0 项失败时不得判为合格；检测覆盖率低于 70% 时只输出部分诊断。

## 项目结构

```text
audit-dtc-store/
├── SKILL.md
├── agents/openai.yaml
├── scripts/audit_store.py
├── references/
│   ├── browser-authorized-checks.md
│   ├── enhanced-checks.md
│   └── qualification-rubric.md
└── assets/
    ├── report-template.md
    └── wechat-qr.png
```

## 说明

本项目用于运营诊断和整改排序，不替代支付、法律、税务、安全或无障碍合规审计。后台界面和平台规则会变化，关键结论应保留取证时间与证据来源。

## 关注公众号

微信搜索：**虎皮叔叔聊跨境独立站**

<img src="assets/wechat-qr.png" alt="虎皮叔叔聊跨境独立站公众号二维码" width="900">

