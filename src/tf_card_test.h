#pragma once

#include <Arduino.h>

// TfCardTestResult 保存开机 TF 卡自检的各项结果。
struct TfCardTestResult {
  // mounted 表示 FAT 文件系统是否成功挂载。
  bool mounted;
  // readWritePassed 表示临时文件是否成功写入、读回并删除。
  bool readWritePassed;
  // cleanupPassed 表示测试临时文件是否已从卡中清除。
  bool cleanupPassed;
  // capacityMb 是文件系统报告的近似容量，单位为 MiB。
  uint32_t capacityMb;
  // rootEntryCount 是根目录中检测到的文件与文件夹总数。
  uint16_t rootEntryCount;
};

// 挂载 TF 卡，列出根目录，并执行不会保留文件的读写自检。
TfCardTestResult tfCardRunSelfTest();
