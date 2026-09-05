#pragma once

#include <Arduino.h>

// 使用已经挂载的 TF 卡初始化模式文件；文件不存在时写入两个内置模式。
bool tfModeStoreBegin(bool cardMounted);
// 执行 Flask 下发的新增或删除命令，相同命令编号不会重复写卡。
void tfModeStoreHandleCommand(uint32_t commandId, const String& operation,
                              const String& encodedRecord);
// 返回 TF 卡中全部模式的紧凑文本，供主机随状态上报给 Flask。
const String& tfModeStoreEncodedModes();
// 返回最近一次已经执行的 TF 命令编号。
uint32_t tfModeStoreAcknowledgedCommandId();
// 返回最近一次 TF 命令是否执行成功。
bool tfModeStoreLastCommandSucceeded();
// 返回模式文件当前是否可以正常读写。
bool tfModeStoreReady();
