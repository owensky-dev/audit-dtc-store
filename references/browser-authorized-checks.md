# 真实浏览器后台授权检查

## 目录

1. 通用登录与取证规则
2. Core Web Vitals
3. 广告落地页匹配
4. 弃购挽回
5. Search Console
6. 状态映射

## 1. 通用登录与取证规则

后台检查使用用户控制的真实浏览器，不要求 API Key。

1. 取得用户对目标平台的明确只读授权。
2. 打开平台官方登录页后暂停，让用户自行输入密码并完成 MFA。
3. 不读取、索取、复述或保存密码、验证码、Cookie、Local Storage、访问令牌或浏览器 Profile。
4. 用户完成登录后，确认当前账号、广告账户、商店或 Search Console Property 是否属于本次审计范围。
5. 只访问查看页，不点击 Edit、Save、Publish、Turn on、Turn off、Submit、Send 或同等含义的控件。
6. 只保存必要的状态、数值、时间、页面 URL 和脱敏截图。遮盖邮箱、客户姓名、订单信息、账号 ID 和付款资料。
7. 无法登录、浏览器工具不可用或页面状态不确定时，使用用户提供的脱敏截图、CSV 或 JSON；仍不能验证则标记 `unknown`。

后台 UI 会变化。优先根据页面语义和可见标签定位，不依赖脆弱的固定 CSS 选择器。

## 2. Core Web Vitals

按以下顺序取证：

1. 在真实浏览器中打开 PageSpeed Insights 网页，分别检查核心广告落地页与站点 Origin 的 Mobile 字段数据。
2. 若 PageSpeed 返回 429、无字段数据或无法读取，经授权进入 Search Console 的 Core Web Vitals 报告，记录 Mobile 状态、问题分组、受影响 URL 数和报告时间。
3. 若仍无字段证据，运行本地移动端 Lighthouse，记录 LCP、CLS、TBT 和测试环境，并设置 `value.data_type = "lab"`。

字段证据要求：

- `value.data_type = "field"`
- `value.form_factor = "PHONE"`
- `value.scope` 为 `url`、`origin` 或 `gsc-url-group`
- 记录 LCP、INP、CLS 的第 75 百分位或 Search Console 对应状态
- 记录采集时间和来源

判定：

- `pass`：移动端字段数据能够覆盖 LCP、INP、CLS，且全部处于良好范围。
- `warn`：字段数据不完整、存在需改进指标，或只有实验室数据。
- `fail`：字段数据存在明确不合格指标。
- `unknown`：没有可用字段或实验室证据。

Lighthouse 的 TBT 只作实验室交互阻塞诊断，不能写成 INP。

## 3. 广告落地页匹配

优先读取当前启用广告或当前投放单元。支持 Google Ads、Meta Ads、TikTok Ads 及其他广告平台。

从后台或用户导出证据中记录：

- 平台、广告账户范围、Campaign/Ad group/Ad 或 Asset group 标识
- 广告状态与取证时间
- 广告标题、正文、CTA、商品或 SKU
- 最终 URL、移动最终 URL和跟踪参数
- 承诺价格、折扣、赠品、配送、保修、国家与币种

使用同一真实浏览器打开最终 URL，按手机视口检查：

1. 最终跳转是否成功，是否落到同一品牌和预期商品。
2. 商品 ID、SKU、结构化数据、Title/H1 与主要视觉是否一致。
3. 价格、折扣码、赠品、配送、退换或保修承诺是否一致。
4. 国家、语言、币种及库存是否适合广告受众。
5. 首屏是否出现对应商品、核心承诺和可用 CTA。
6. 跟踪参数是否被合理保留；不要因平台正常重写而泄露完整点击标识。

硬失败包括：404/错误页、错误商品或品牌、关键优惠无法兑现、错误市场或币种、商品不可购买。仅文案措辞差异可标记 `warn`。

不要仅凭商品名字符串出现就判 `pass`。确定性证据优先于语义推断。

## 4. 弃购挽回

### 4.1 授权只读配置核查

登录电商或营销后台后，分别检查 Browse abandonment、Cart abandonment 和 Checkout abandonment：

- 是否启用
- 触发条件、等待时间和发送对象
- 渠道、发件人、主题、折扣和恢复按钮
- 最近运行时间、Run ID、成功或失败状态
- 未发送或失败原因

只查看配置，不启停、不编辑、不保存。

按以下证据强度判断启停状态：

1. 优先采信自动化详情页、自动化列表、明确的状态标签、开关或动作按钮。例如详情页出现“关闭自动化/Turn off”通常证明当前已启用，但仍应同时记录状态标签。
2. 平台设置页或用户提供的脱敏后台导出可作为次级权威证据。
3. 首页推荐卡、引导卡、任务卡和“准备就绪”文案只能用于发现自动化入口，不能证明流程已启用或未启用。
4. 弃购记录的 `sent`、`not_sent`、`scheduled` 或 `suppressed` 只表示单次投递结果，不能单独反推自动化开关状态。
5. 用户指出证据冲突时，返回自动化详情页或列表复核；用新权威证据覆盖旧推断，并在报告中说明更正。

判定：

- `pass`：自动化已启用，并存在近期成功运行或已验证消息证据。
- `warn`：已启用但没有近期成功运行证据，或受众、延迟、内容存在明显风险。
- `fail`：后台明确显示未启用、持续失败或恢复链接失效。
- `unknown`：没有后台或测试证据。

增强证据中：

- `pass` 或因配置关闭而判 `fail` 时，写入 `value.config_state_source`。推荐值为 `automation_detail`、`automation_list`、`platform_settings` 或 `user_export`。
- 因持续失败或恢复链接失效判 `fail` 时，写入 `value.failure_basis`，值为 `persistent_failures` 或 `broken_recovery_link`，并保留对应权威证据。
- 不得把 `onboarding_card`、`home_recommendation` 或同类入口提示写成 `config_state_source`。

### 4.2 授权副作用测试

只有用户逐项确认后才执行：

1. 确认测试商品、测试邮箱或手机号、测试国家及允许触发的消息渠道。
2. 使用唯一测试标识，把商品加入购物车并按约定进入 Checkout。
3. 只提交已授权的测试联系方式；不创建账户、不输入付款资料、不提交订单。
4. 记录触发时间、配置等待时间和最晚验证时间。
5. 等待期间保持 `unknown`，并在证据中写明 `pending`；不能提前判失败。
6. 到期后验证消息是否到达、商品和金额是否正确、恢复链接是否有效、退订入口是否存在。

使用 `authorization = "authorized-side-effect"`，并在顶层 `safety` 中把 `submitted_forms`、`generated_abandoned_checkout`、`triggered_messages` 按实际情况设为 `true`。

## 5. Search Console

经授权登录 Search Console，确认目标是 Domain Property 还是 URL-prefix Property。至少检查：

1. Property 可访问且属于本次审计域名。
2. Sitemap 是否已经提交、最近读取是否成功、是否存在错误。
3. 效果报告在最近完整周期内是否可读取；零数据不等于未验证。
4. 网页索引报告是否存在站点级严重异常。
5. 抽样首页、集合页和核心商品页，记录索引状态、抓取、robots/noindex 与 Google canonical。
6. Core Web Vitals 报告只作为字段体验证据，不把公开验证标签当作当前访问证据。

判定：

- `pass`：Property 可访问，至少一类后台数据可读，且没有阻止核心页面发现的严重问题。
- `warn`：Property 可访问但数据为空、Sitemap 有警告或部分抽样 URL 异常。
- `fail`：已完成授权但目标 Property 不存在/无权访问，或核心页面明确被阻止索引。
- `unknown`：用户未授权、未完成登录或证据不足。

## 6. 状态映射

浏览器取证写入增强证据 JSON。推荐来源：

- `public-browser`
- `authorized-browser`
- `user-export`
- `local-lab`

推荐授权值：

- `public-readonly`
- `browser-authorized-readonly`
- `authorized-side-effect`
- `user-provided`

对正在等待的异步消息不要新增评分状态。保持检查项 `status = "unknown"`，并使用 `value.execution_state = "pending"`。
