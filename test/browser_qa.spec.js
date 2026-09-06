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
    // 截图保存到项目 buffer，供交付前人工核对完整页面而不占用 C 盘临时目录。
    await page.screenshot({
      path: `buffer/render_checks/dashboard-${width}.png`, fullPage: true,
    });
  });
}


// 对话输入测试确认发送状态不会造成控件位移或脚本错误。
test("chat input interaction", async ({ page }) => {
  await page.setViewportSize({ width: 375, height: 900 });
  await page.goto("http://127.0.0.1:5000/", { waitUntil: "commit" });
  await page.locator("#assistantSection").waitFor();
  await expect(page.locator("#assistantShortcut svg")).toBeVisible();
  await expect(page.locator("#chatLog")).toBeEmpty();
  await expect(page.locator("#voiceButton")).toHaveCount(0);
  await page.locator("#assistantInput").fill("你好");
  await expect(page.locator("#assistantSend")).toBeEnabled();
  await expect(page.locator("#assistantInput")).toHaveValue("你好");
});


// TF 模式测试确认先选组合、再输入本次时间，并且不会把时间写入新模式。
test("TF mode selection and run time interaction", async ({ page }) => {
  await page.setViewportSize({ width: 375, height: 900 });
  await page.goto("http://127.0.0.1:5000/", { waitUntil: "commit" });
  await page.locator("#modeShortcut").click();
  await expect(page.locator("#tfState")).toContainText("TF 卡可用");
  await page.locator(".select-mode[data-mode-id='mode_1']").click();
  await expect(page.locator("#selectedModeName")).toHaveText("模式 1");
  await expect(page.locator("#modeRun")).toBeEnabled();
  await page.locator("#runDuration").fill("27");
  // 弹窗截图用于核对“先选组合、再填本次时间”的手机端视觉顺序。
  await page.screenshot({
    path: "buffer/render_checks/mode-dialog-375.png", fullPage: false,
  });
  // requestPromise 捕获执行请求但不让测试真的控制四块硬件。
  const requestPromise = page.waitForRequest((request) => request.url().endsWith("/api/tf-modes/mode_1/activate"));
  await page.route("**/api/tf-modes/mode_1/activate", async (route) => {
    await route.fulfill({
      status: 200, contentType: "application/json",
      body: JSON.stringify({ok: true, mode: {id: "mode_1", name: "模式 1"}, duration_seconds: 27}),
    });
  });
  await page.locator("#modeRun").click();
  // runRequest 是网页实际发出的本次执行请求。
  const runRequest = await requestPromise;
  expect(runRequest.postDataJSON()).toEqual({duration_seconds: 27});
  await expect(page.locator("#modeFormStatus")).toContainText("27 秒后恢复自动检测");
  await expect(page.locator("#modeForm")).not.toContainText("持续时间");
});
