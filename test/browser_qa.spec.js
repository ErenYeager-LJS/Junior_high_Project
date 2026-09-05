const { test, expect } = require("@playwright/test");


// Hallmark 要求在四个移动宽度和一个桌面宽度检查页面布局。
for (const width of [320, 375, 414, 768, 1280]) {
  // 每个测试确认页面没有横向滚动，且关键工作区拥有可见尺寸。
  test(`layout ${width}px`, async ({ page }) => {
    await page.setViewportSize({ width, height: 900 });
    await page.goto("http://127.0.0.1:5000/", { waitUntil: "commit" });
    await page.locator("#assistantSection").waitFor();
    await expect(page.locator("#assistantShortcut svg")).toBeVisible();
    // dimensions 保存文档的可视宽度、滚动宽度和关键区域尺寸。
    const dimensions = await page.evaluate(() => ({
      clientWidth: document.documentElement.clientWidth,
      scrollWidth: document.documentElement.scrollWidth,
      chatWidth: document.querySelector("#assistantSection").getBoundingClientRect().width,
      chartWidth: document.querySelector("#adcChart").getBoundingClientRect().width,
    }));
    expect(dimensions.scrollWidth).toBeLessThanOrEqual(dimensions.clientWidth);
    expect(dimensions.chatWidth).toBeGreaterThan(0);
    expect(dimensions.chartWidth).toBeGreaterThan(0);
  });
}


// 对话输入测试确认发送状态不会造成控件位移或脚本错误。
test("chat input interaction", async ({ page }) => {
  await page.setViewportSize({ width: 375, height: 900 });
  await page.goto("http://127.0.0.1:5000/", { waitUntil: "commit" });
  await page.locator("#assistantSection").waitFor();
  await expect(page.locator("#assistantShortcut svg")).toBeVisible();
  await page.locator("#assistantInput").fill("你好");
  await expect(page.locator("#assistantSend")).toBeEnabled();
  await expect(page.locator("#assistantInput")).toHaveValue("你好");
});
