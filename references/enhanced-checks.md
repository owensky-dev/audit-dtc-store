# 浏览器与授权增强检查

## 目录

1. 默认公开浏览器检查
2. Checkout 安全停止点
3. 性能数据边界
4. 后台授权入口
5. 增强证据 JSON

## 1. 默认公开浏览器检查

使用 390×844 或接近的手机视口，依次检查首页、广告落地页、一个核心产品页、购物车和 Checkout。

记录截图或明确的 DOM/URL 证据：

1. 首屏是否直接显示预期商品、价格和主 CTA。
2. CTA 是否可见、可点击且没有被弹窗遮挡。
3. 页面是否出现横向滚动、文本重叠、图片裁切、空白区或无法关闭的弹窗。
4. 加购后是否出现购物车反馈。
5. 从加购到 Checkout 的主要操作次数。
6. Checkout 是否强制注册，是否出现空白页、404 或脚本错误。
7. 到达安全停止点前可见的支付方式。

默认不接受营销订阅或通知权限。Cookie 弹窗阻挡关键流程时，只接受网站运行必需 Cookie。

## 2. Checkout 安全停止点

允许：

- 点击 Add to Cart、Buy Now、Cart 和 Checkout。
- 读取公开展示的支付徽标、快捷支付按钮和表单字段。
- 在本地浏览器中产生临时购物车 Cookie。

停止：

- 在提交邮箱、手机号、配送地址或支付信息之前停止。
- 不点击 Pay、Place Order、Complete Order 或具有同等含义的按钮。
- 不使用真实个人信息试填。
- 不为验证 Guest Checkout 而创建账户。

如果网站只有提交联系方式后才能显示支付方式，把 C5、C6 标为 `unknown`。只有用户逐项确认并提供专用测试身份后，才能进入 `authorized-side-effect`。

## 3. 性能数据边界

公开版本不要求 API Key。按优先级取证：

1. 浏览器中的 PageSpeed Insights Mobile 字段数据
2. 经授权读取的 Search Console Core Web Vitals 后台报告
3. Chrome DevTools 或 Lighthouse 移动端实验室数据
4. 自动审计脚本的请求中位数，仅作基础网络初筛

字段数据合格阈值：

- LCP ≤2.5 秒
- INP ≤200 毫秒
- CLS ≤0.1
- 以第 75 百分位判断

若 PageSpeed 返回 429，不连续刷新或绕过限制。改读已有结果、经授权的 Search Console 后台，或降级为本地 Lighthouse。

若只有实验室数据，明确标记 `lab`。Lighthouse 无真实交互时不能测量 INP，可以记录 TBT，但不得作为真实 INP。

## 4. 后台授权入口

需要验证 Core Web Vitals 字段状态、广告素材、弃购自动化或 Search Console 时，阅读 [browser-authorized-checks.md](browser-authorized-checks.md)。

关键原则：

- 不要求 API 配置。
- 用户在真实浏览器中手动登录并完成 MFA。
- 登录授权默认只读，不包含修改或消息发送权限。
- 用户提供脱敏截图、CSV 或 JSON 时，可使用 `user-export` 作为替代证据。

## 5. 增强证据 JSON

保存为 UTF-8 JSON。推荐使用 1.1 格式：

```json
{
  "audit_version": "1.1",
  "session": {
    "authorization": "browser-authorized-readonly",
    "captured_at": "2026-07-28T15:30:00+08:00",
    "safety": {
      "submitted_forms": false,
      "created_account": false,
      "generated_abandoned_checkout": false,
      "triggered_messages": false,
      "submitted_order": false
    }
  },
  "checks": {
    "T2": {
      "status": "pass",
      "evidence": "Search Console Mobile Core Web Vitals 显示核心 URL 组通过",
      "source_type": "authorized-browser",
      "authorization": "browser-authorized-readonly",
      "captured_at": "2026-07-28T15:24:00+08:00",
      "source_url": "https://search.google.com/search-console/",
      "value": {
        "data_type": "field",
        "form_factor": "PHONE",
        "scope": "gsc-url-group",
        "lcp_status": "good",
        "inp_status": "good",
        "cls_status": "good"
      }
    },
    "T3": {
      "status": "pass",
      "evidence": "当前启用广告的商品、优惠、币种和最终落地页一致",
      "source_type": "authorized-browser",
      "authorization": "browser-authorized-readonly",
      "captured_at": "2026-07-28T15:27:00+08:00",
      "source_url": "https://example.com/products/example",
      "value": {
        "ad_platform": "google-ads",
        "fatal_mismatches": [],
        "product_match": true,
        "offer_match": true,
        "market_match": true,
        "cta_available": true
      }
    },
    "S7": {
      "status": "pass",
      "evidence": "目标 Property 可访问，Sitemap 与效果数据可读",
      "source_type": "authorized-browser",
      "authorization": "browser-authorized-readonly",
      "captured_at": "2026-07-28T15:30:00+08:00",
      "source_url": "https://search.google.com/search-console/",
      "value": {
        "property_accessible": true,
        "sitemap_readable": true,
        "performance_readable": true
      }
    }
  }
}
```

允许状态：`pass`、`warn`、`fail`、`unknown`。异步等待使用 `status = "unknown"` 和 `value.execution_state = "pending"`。

脚本使用增强证据覆盖对应检查项并保留证据来源、授权模式和安全记录。1.0 格式仍可读取，但缺少来源元数据时报告会标记为普通 `enhanced`。
