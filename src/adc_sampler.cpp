#include "adc_sampler.h"

#include "device_config.h"

namespace {
// 缓冲区可保存约 0.5 秒的 1000 Hz 数据。
constexpr size_t BUFFER_SIZE = 512;
// 环形缓冲区保存尚未上报的 A0 原始值。
uint16_t samples[BUFFER_SIZE] = {};
// writeIndex 指向下一次写入的位置。
size_t writeIndex = 0;
// sampleCount 表示缓冲区中有效数据的数量。
size_t sampleCount = 0;
// lastSampleUs 记录上一次采样的系统微秒数。
uint32_t lastSampleUs = 0;
}

// 让采样周期从设备启动后的当前时刻开始。
void adcBegin(uint32_t nowUs) { lastSampleUs = nowUs; }

// 每到 1000 us 读取 A0，并写入环形缓冲区。
void adcUpdate(uint32_t nowUs) {
  if (nowUs - lastSampleUs < ADC_SAMPLE_INTERVAL_US) return;
  // 直接使用本次实际采样时刻，网络阻塞后不会伪造“补采样”点。
  lastSampleUs = nowUs;
  samples[writeIndex] = analogRead(A0);
  writeIndex = (writeIndex + 1) % BUFFER_SIZE;
  if (sampleCount < BUFFER_SIZE) ++sampleCount;
}

// 提供有效采样数量，供 JSON 上报循环使用。
size_t adcCount() { return sampleCount; }

// 把环形缓冲区转换成从旧到新的读取顺序。
uint16_t adcAt(size_t index) {
  // oldestIndex 是当前最早一条有效数据的位置。
  const size_t oldestIndex = (writeIndex + BUFFER_SIZE - sampleCount) % BUFFER_SIZE;
  return samples[(oldestIndex + index) % BUFFER_SIZE];
}

// 没有数据时返回 0，否则返回最后写入的值。
uint16_t adcLatest() {
  return sampleCount == 0 ? 0 : samples[(writeIndex + BUFFER_SIZE - 1) % BUFFER_SIZE];
}

// 服务端确认接收后，从下一批数据重新计数。
void adcClear() { sampleCount = 0; }
