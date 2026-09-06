#include "device_config.h"

#if DEVICE_ROLE_MASTER

#include "tf_mode_store.h"

#include <SD.h>

namespace {
// MODE_FILE_PATH 是 TF 卡上永久保存网页模式的文件路径。
constexpr char MODE_FILE_PATH[] = "/MODES.TXT";
// TEMP_MODE_FILE_PATH 是新内容完全写好前使用的临时文件路径。
constexpr char TEMP_MODE_FILE_PATH[] = "/MODES.NEW";
// BACKUP_MODE_FILE_PATH 在替换期间暂存上一版可用模式文件。
constexpr char BACKUP_MODE_FILE_PATH[] = "/MODES.BAK";
// DEFAULT_MODE_FILE_CONTENT 是首次使用时写入的两个基础模式。
constexpr char DEFAULT_MODE_FILE_CONTENT[] =
    "mode_1|%E6%A8%A1%E5%BC%8F%201|0|0|1|1|1\n"
    "mode_2|%E6%A8%A1%E5%BC%8F%202|0|1|0|0|0\n";
// MAX_MODE_FILE_BYTES 限制模式文件大小，避免异常文件耗尽 ESP8266 内存。
constexpr size_t MAX_MODE_FILE_BYTES = 4096;
// encodedModes 保存去掉换行后的模式列表，模式之间使用分号分隔。
String encodedModes;
// storeReady 表示模式文件已经成功创建并读取。
bool storeReady = false;
// acknowledgedCommandId 保存最近处理过的服务端命令编号。
uint32_t acknowledgedCommandId = 0;
// lastCommandSucceeded 保存最近一次新增或删除操作的结果。
bool lastCommandSucceeded = true;

// isValidRecord 检查一行模式是否包含固定的七个字段且没有控制字符。
bool isValidRecord(const String& record) {
  if (record.isEmpty() || record.length() > 320 || record.indexOf('\n') >= 0 ||
      record.indexOf('\r') >= 0 || record.indexOf(';') >= 0) {
    return false;
  }
  // separatorCount 是当前记录中竖线分隔符的数量。
  uint8_t separatorCount = 0;
  for (size_t index = 0; index < record.length(); ++index) {
    if (record[index] == '|') ++separatorCount;
  }
  return separatorCount == 6;
}

// readModeFile 从 TF 卡读取完整文件，并生成适合通过 JSON 上报的单行文本。
bool readModeFile() {
  // inputFile 是当前打开的模式文件读取句柄。
  File inputFile = SD.open(MODE_FILE_PATH, FILE_READ);
  if (!inputFile || inputFile.size() > MAX_MODE_FILE_BYTES) {
    if (inputFile) inputFile.close();
    return false;
  }
  // nextModes 暂存本次从文件中读出的有效模式列表。
  String nextModes;
  nextModes.reserve(inputFile.size() + 8);
  while (inputFile.available()) {
    // record 是去掉首尾空白后的单条模式记录。
    String record = inputFile.readStringUntil('\n');
    record.trim();
    if (!isValidRecord(record)) continue;
    if (!nextModes.isEmpty()) nextModes += ';';
    nextModes += record;
    yield();
  }
  inputFile.close();
  if (nextModes.isEmpty()) return false;
  encodedModes = nextModes;
  return true;
}

// writeModeFile 把单行模式列表转换为逐行文件，并采用临时文件替换降低断电风险。
bool writeModeFile(const String& nextModes) {
  if (SD.exists(TEMP_MODE_FILE_PATH) && !SD.remove(TEMP_MODE_FILE_PATH)) return false;
  // outputFile 是模式临时文件的写入句柄。
  File outputFile = SD.open(TEMP_MODE_FILE_PATH, "w");
  if (!outputFile) return false;
  // lineStart 是当前模式记录在单行文本中的起始下标。
  size_t lineStart = 0;
  while (lineStart < nextModes.length()) {
    // separator 是当前模式后分号的位置；最后一条没有分号。
    const int separator = nextModes.indexOf(';', lineStart);
    // lineEnd 是当前模式记录的结束下标。
    const size_t lineEnd = separator < 0 ? nextModes.length() : static_cast<size_t>(separator);
    outputFile.println(nextModes.substring(lineStart, lineEnd));
    lineStart = lineEnd + 1;
  }
  outputFile.flush();
  outputFile.close();
  if (SD.exists(BACKUP_MODE_FILE_PATH) && !SD.remove(BACKUP_MODE_FILE_PATH)) {
    SD.remove(TEMP_MODE_FILE_PATH);
    return false;
  }
  // backupCreated 表示旧模式文件已经安全改名，可以开始替换。
  const bool backupCreated = !SD.exists(MODE_FILE_PATH) ||
                             SD.rename(MODE_FILE_PATH, BACKUP_MODE_FILE_PATH);
  if (!backupCreated) {
    SD.remove(TEMP_MODE_FILE_PATH);
    return false;
  }
  if (!SD.rename(TEMP_MODE_FILE_PATH, MODE_FILE_PATH)) {
    if (SD.exists(BACKUP_MODE_FILE_PATH)) {
      SD.rename(BACKUP_MODE_FILE_PATH, MODE_FILE_PATH);
    }
    return false;
  }
  if (SD.exists(BACKUP_MODE_FILE_PATH)) SD.remove(BACKUP_MODE_FILE_PATH);
  return readModeFile();
}

// recordId 返回一条紧凑模式记录最前面的模式编号。
String recordId(const String& record) {
  // separator 是模式编号后第一个竖线的位置。
  const int separator = record.indexOf('|');
  return separator < 0 ? String() : record.substring(0, separator);
}

// removeRecordById 删除指定编号，并返回删除后的完整模式文本。
String removeRecordById(const String& modeId, bool& found) {
  // nextModes 收集所有不需要删除的模式记录。
  String nextModes;
  // recordStart 是本轮记录的起始下标。
  size_t recordStart = 0;
  found = false;
  while (recordStart < encodedModes.length()) {
    // separator 是当前记录后分号的位置。
    const int separator = encodedModes.indexOf(';', recordStart);
    // recordEnd 是当前记录的结束下标。
    const size_t recordEnd = separator < 0 ? encodedModes.length() : static_cast<size_t>(separator);
    // record 是本轮解析出的完整模式记录。
    const String record = encodedModes.substring(recordStart, recordEnd);
    if (recordId(record) == modeId) {
      found = true;
    } else {
      if (!nextModes.isEmpty()) nextModes += ';';
      nextModes += record;
    }
    recordStart = recordEnd + 1;
  }
  return nextModes;
}
}

// 准备 TF 模式文件，并在空卡上建立两个基础模式。
bool tfModeStoreBegin(bool cardMounted) {
  storeReady = false;
  encodedModes = "";
  if (!cardMounted) return false;
  // 上次若在替换后半段断电，优先从备份恢复最后一版完整文件。
  if (!SD.exists(MODE_FILE_PATH) && SD.exists(BACKUP_MODE_FILE_PATH)) {
    SD.rename(BACKUP_MODE_FILE_PATH, MODE_FILE_PATH);
  }
  // 正式文件存在时，启动阶段留下的临时文件已经无用，可以清理。
  if (SD.exists(MODE_FILE_PATH) && SD.exists(TEMP_MODE_FILE_PATH)) {
    SD.remove(TEMP_MODE_FILE_PATH);
  }
  if (!SD.exists(MODE_FILE_PATH)) {
    // outputFile 是首次建立模式文件时使用的写入句柄。
    File outputFile = SD.open(MODE_FILE_PATH, "w");
    if (!outputFile) return false;
    outputFile.print(DEFAULT_MODE_FILE_CONTENT);
    outputFile.flush();
    outputFile.close();
  }
  storeReady = readModeFile();
  Serial.println(storeReady ? "[TF] Mode file ready" : "[TF] Mode file unavailable");
  return storeReady;
}

// 按命令编号幂等执行新增或删除，然后重新读取 TF 卡确认实际结果。
void tfModeStoreHandleCommand(uint32_t commandId, const String& operation,
                              const String& encodedRecord) {
  if (commandId == 0 || commandId == acknowledgedCommandId) return;
  acknowledgedCommandId = commandId;
  lastCommandSucceeded = false;
  if (!storeReady) return;

  if (operation == "add" && isValidRecord(encodedRecord)) {
    // existingId 是准备写入记录的唯一模式编号。
    const String existingId = recordId(encodedRecord);
    // ignoredFound 接收是否发现同名记录；新增操作只允许不存在的编号。
    bool ignoredFound = false;
    removeRecordById(existingId, ignoredFound);
    if (!ignoredFound) {
      // nextModes 是追加新模式后的完整文件内容。
      const String nextModes = encodedModes + ";" + encodedRecord;
      lastCommandSucceeded = nextModes.length() <= MAX_MODE_FILE_BYTES && writeModeFile(nextModes);
    }
  } else if (operation == "delete") {
    // found 表示卡内是否存在准备删除的模式编号。
    bool found = false;
    // nextModes 是移除目标后的完整模式列表。
    const String nextModes = removeRecordById(encodedRecord, found);
    lastCommandSucceeded = found && !nextModes.isEmpty() && writeModeFile(nextModes);
  }
  Serial.print("[TF] Mode command ");
  Serial.print(commandId);
  Serial.println(lastCommandSucceeded ? " PASS" : " FAIL");
}

// 返回当前从 TF 文件读出的紧凑模式列表；缓存异常时先从卡内重新恢复。
const String& tfModeStoreEncodedModes() {
  if (encodedModes.isEmpty()) storeReady = readModeFile();
  return encodedModes;
}

// 返回最近处理完成的命令编号，供 Flask 清除待执行命令。
uint32_t tfModeStoreAcknowledgedCommandId() { return acknowledgedCommandId; }

// 返回最近一次命令的文件写入和回读结果。
bool tfModeStoreLastCommandSucceeded() { return lastCommandSucceeded; }

// 返回模式文件是否已经正常建立并可读取；缓存丢失时重新读取真实文件确认。
bool tfModeStoreReady() {
  if (!storeReady || encodedModes.isEmpty()) storeReady = readModeFile();
  return storeReady;
}

#endif
