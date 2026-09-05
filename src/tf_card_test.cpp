#include "device_config.h"

#if DEVICE_ROLE_MASTER

#include "tf_card_test.h"

#include <SD.h>
#include <SPI.h>

namespace {
// TEST_FILE_PATH 是读写验证使用的临时文件路径。
constexpr char TEST_FILE_PATH[] = "/TF_TEST.TXT";
// TEST_FILE_CONTENT 是写入后必须原样读回的验证内容。
constexpr char TEST_FILE_CONTENT[] = "ESP8266_TF_CARD_OK";

// countRootEntries 列出根目录，并返回其中的文件和文件夹数量。
uint16_t countRootEntries() {
  // root 是 TF 卡根目录句柄。
  File root = SD.open("/");
  if (!root || !root.isDirectory()) return 0;
  // entryCount 记录成功读取到的根目录条目数量。
  uint16_t entryCount = 0;
  while (true) {
    // entry 是当前遍历到的文件或文件夹。
    File entry = root.openNextFile();
    if (!entry) break;
    Serial.print("[TF] Root entry: ");
    Serial.print(entry.name());
    Serial.print(entry.isDirectory() ? " <DIR>" : " size=");
    if (!entry.isDirectory()) Serial.print(entry.size());
    Serial.println();
    ++entryCount;
    entry.close();
    yield();
  }
  root.close();
  return entryCount;
}

// verifyReadWrite 写入固定文本、读回比对，并删除临时文件。
bool verifyReadWrite(bool& cleanupPassed) {
  cleanupPassed = false;
  // 先删除上次异常断电可能留下的同名测试文件。
  if (SD.exists(TEST_FILE_PATH) && !SD.remove(TEST_FILE_PATH)) return false;
  // outputFile 是以覆盖写入方式打开的临时文件。
  File outputFile = SD.open(TEST_FILE_PATH, "w");
  if (!outputFile) return false;
  // writtenBytes 是本次实际写入的字节数。
  const size_t writtenBytes = outputFile.print(TEST_FILE_CONTENT);
  outputFile.flush();
  outputFile.close();
  if (writtenBytes != strlen(TEST_FILE_CONTENT)) return false;

  // inputFile 是用于读回校验内容的临时文件句柄。
  File inputFile = SD.open(TEST_FILE_PATH, FILE_READ);
  if (!inputFile) return false;
  // readBack 保存从 TF 卡实际读出的内容。
  const String readBack = inputFile.readString();
  inputFile.close();
  // contentMatches 表示读回内容与写入内容完全相同。
  const bool contentMatches = readBack == TEST_FILE_CONTENT;
  cleanupPassed = SD.remove(TEST_FILE_PATH) && !SD.exists(TEST_FILE_PATH);
  return contentMatches && cleanupPassed;
}
}

// 完成 TF 卡挂载、容量查询、目录遍历和临时文件读写测试。
TfCardTestResult tfCardRunSelfTest() {
  // result 默认表示全部失败，只有每一步成功后才更新对应字段。
  TfCardTestResult result = {false, false, false, 0, 0};
  Serial.println("[TF] Self-test starting");
  Serial.println("[TF] Wiring: SS=D2, DI=D7, SCK=D5, DO=D6");

  // 共享 SPI 总线上先释放屏幕和 TF 卡片选，避免两个设备同时响应。
  pinMode(TFT_CS, OUTPUT);
  digitalWrite(TFT_CS, HIGH);
  pinMode(TF_CARD_CS_PIN, OUTPUT);
  digitalWrite(TF_CARD_CS_PIN, HIGH);
  SPI.begin();
  result.mounted = SD.begin(TF_CARD_CS_PIN, TF_CARD_SPI_FREQUENCY);
  if (!result.mounted) {
    Serial.println("[TF] FAIL: mount failed; check card format and four signal wires");
    return result;
  }

  // capacityBytes 是 SD 库按 FAT 参数计算出的总容量。
  const uint64_t capacityBytes = SD.size64();
  result.capacityMb = static_cast<uint32_t>(capacityBytes / (1024ULL * 1024ULL));
  result.rootEntryCount = countRootEntries();
  result.readWritePassed = verifyReadWrite(result.cleanupPassed);
  Serial.print("[TF] Capacity MiB: ");
  Serial.println(result.capacityMb);
  Serial.print("[TF] Root entries: ");
  Serial.println(result.rootEntryCount);
  Serial.print("[TF] Read/write: ");
  Serial.println(result.readWritePassed ? "PASS" : "FAIL");
  Serial.print("[TF] Cleanup: ");
  Serial.println(result.cleanupPassed ? "PASS" : "FAIL");
  Serial.println(result.readWritePassed ? "[TF] SELF-TEST PASS" : "[TF] SELF-TEST FAIL");
  return result;
}

#endif
