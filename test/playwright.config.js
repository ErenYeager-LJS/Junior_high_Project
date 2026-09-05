const { defineConfig } = require("@playwright/test");


// 浏览器 QA 只运行 test 目录中的 Playwright 用例，并使用本机 Edge。
module.exports = defineConfig({
  testDir: ".",
  testMatch: "browser_qa.spec.js",
  timeout: 10000,
  outputDir: "../buffer/render_checks/playwright-results",
  use: {
    browserName: "chromium",
    channel: "msedge",
    locale: "zh-CN",
  },
});
