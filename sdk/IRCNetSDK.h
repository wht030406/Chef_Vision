#ifndef IRCNETSDK_H
#define IRCNETSDK_H

#include "IRCNetSDKDef.h"

#ifdef __cplusplus
extern "C" {
#endif

/**
 * @brief 初始化
 * 
 * @return 错误码 
 */
IRC_NET_API int IRC_NET_CALL IRC_NET_Init();

/**
 * @brief 反初始化
 * 
 * @return
 */
IRC_NET_API void IRC_NET_CALL IRC_NET_Deinit();

/**
 * @brief 设置日志参数
 *
 * @param[in] level 日志等级，参考IRC_NET_LOG_LEVEL
 * @param[in] logDir 日志文件路径，必须是绝对路径，且以"\\"结尾，建议用户先手动创建
 * @param[in] upperLimit 日志文件上限个数，0-没有上限
 * @return
 */
IRC_NET_API int IRC_NET_CALL IRC_NET_SetLogParam(int level, const char* logDir, int upperLimit);

/**
 * @brief 搜索局域网设备
 *
 * @param[in] searchCallback 搜索回调
 * @param[in] userData 用户自定义数据
 * @param[in] timeout 查询超时时间，单位ms
 * @return 错误码
 */
IRC_NET_API int IRC_NET_CALL IRC_NET_SearchDev(IRC_NET_DEV_SEARCH_CALLBACK searchCallback, void* userData, int timeout);

/**
 * @brief 登录
 * 
 * @param[in] loginInfo 登录信息
 * @param[out] handle 操作句柄
 * @return 错误码
 */
IRC_NET_API int IRC_NET_CALL IRC_NET_Login(const IRC_NET_LOGIN_INFO* loginInfo, IRC_NET_HANDLE* handle);

/**
 * @brief 注销
 * 
 * @param[in] handle 操作句柄
 * @return 错误码
 */
IRC_NET_API int IRC_NET_CALL IRC_NET_Logout(IRC_NET_HANDLE handle);

/**
 * @brief 获取设备信息
 *
 * @param[in] handle 操作句柄
 * @param[out] devInfo 设备信息
 * @return 错误码
 */
IRC_NET_API int IRC_NET_CALL IRC_NET_GetDevInfo(IRC_NET_HANDLE handle, IRC_NET_DEV_INFO* devInfo);

/**
 * @brief 查询设备能力
 *
 * @param[in] handle 操作句柄
 * @param[in] channel 通道
 * @param[in] type 能力类型，参考IRC_NET_DEV_ABILITY_TYPE
 * @param[out] ability 能力信息，根据类型解析
 * @return 错误码
 */
IRC_NET_API int IRC_NET_CALL IRC_NET_GetDevAbility(IRC_NET_HANDLE handle, int channel, int type, void* ability);

/**
 * @brief 异常回调
 * 
 * @param[in] handle 操作句柄
 * @param[in] exceptionCb 异常回调函数
 * @param[in] userData 用户自定义数据
 * @return 错误码 
 */
IRC_NET_API int IRC_NET_CALL IRC_NET_SetExceptionCallback(IRC_NET_HANDLE handle, IRC_NET_EXCEPTION_CALLBACK exceptionCb, void* userData);

/**
 * @brief 订阅报警
 *
 * @param[in] handle 操作句柄
 * @param[in] alarmCb 报警回调函数
 * @param[in] userData 用户自定义数据
 * @return 错误码
 */
IRC_NET_API int IRC_NET_CALL IRC_NET_SubscribeAlarm(IRC_NET_HANDLE handle, IRC_NET_ALARM_CALLBACK alarmCb, void* userData);

/**
 * @brief 订阅报警V2
 *
 * @param[in] handle 操作句柄
 * @param[in] snapEnable 是否开启报警抓图，false-关闭 true-开启
 * @param[in] alarmCb 报警回调函数
 * @param[in] userData 用户自定义数据
 * @return 错误码
 */
IRC_NET_API int IRC_NET_CALL IRC_NET_SubscribeAlarm_V2(IRC_NET_HANDLE handle, bool snapEnable, IRC_NET_ALARM_CALLBACK alarmCb, void* userData);

/**
 * @brief 订阅报警V3
 *
 * @param[in] handle 操作句柄
 * @param[in] subscribeParam 报警订阅参数
 * @param[in] alarmCb 报警回调函数
 * @param[in] userData 用户自定义数据
 * @return 错误码
 */
IRC_NET_API int IRC_NET_CALL IRC_NET_SubscribeAlarm_V3(IRC_NET_HANDLE handle, const IRC_NET_ALARM_SUBSCRIBE_PARAM* subscribeParam, IRC_NET_ALARM_CALLBACK alarmCb, void* userData);

/**
 * @brief 取消订阅报警
 *
 * @param[in] handle 操作句柄
 * @return 错误码
 */
IRC_NET_API int IRC_NET_CALL IRC_NET_UnsubscribeAlarm(IRC_NET_HANDLE handle);

/**
 * @brief 设置拉取温度执行参数
 *
 * @param[in] handle 操作句柄
 * @param[in] envCorrectionEnable 环参修正使能开关，0：关闭 1：开启
 * @return 错误码
 */
IRC_NET_API int IRC_NET_CALL IRC_NET_SetPullTempExecParam(IRC_NET_HANDLE handle, int envCorrectionEnable);

/**
 * @brief 开始拉取温度
 *
 * @param[in] handle 操作句柄
 * @param[in] tempCb 温度回调函数
 * @param[in] userData 用户自定义数据
 * @return 错误码
 */
IRC_NET_API int IRC_NET_CALL IRC_NET_StartPullTemp(IRC_NET_HANDLE handle, IRC_NET_TEMP_CALLBACK tempCb, void* userData);

/**
 * @brief 开始拉取温度
 *
 * @param[in] handle 操作句柄
 * @param[in] tempCb 温度回调函数
 * @param[in] userData 用户自定义数据
 * @return 错误码
 */
IRC_NET_API int IRC_NET_CALL IRC_NET_StartPullTemp_V2(IRC_NET_HANDLE handle, IRC_NET_TEMP_CALLBACK_V2 tempCb, void* userData);

/**
 * @brief 停止拉取温度
 *
 * @param[in] handle 操作句柄
 * @return 错误码
 */
IRC_NET_API int IRC_NET_CALL IRC_NET_StopPullTemp(IRC_NET_HANDLE handle);

/**
 * @brief 开始拉取NUC数据
 *
 * @param[in] handle 操作句柄
 * @param[in] dataCb NUC数据回调函数
 * @param[in] userData 用户自定义数据
 * @return 错误码
 */
IRC_NET_API int IRC_NET_CALL IRC_NET_StartPullNucData(IRC_NET_HANDLE handle, IRC_NET_NUC_DATA_CALLBACK dataCb, void* userData);

/**
 * @brief 停止拉取NUC数据
 *
 * @param[in] handle 操作句柄
 * @return 错误码
 */
IRC_NET_API int IRC_NET_CALL IRC_NET_StopPullNucData(IRC_NET_HANDLE handle);

/**
 * @brief 开启视频预览
 * 
 * @param[in] handle 操作句柄
 * @param[in] previewInfo 预览信息
 * @param[in] videoCb 视频回调函数
 * @param[in] userData 用户自定义数据,会通过videoCb原样抛出
 * @return 错误码
 */
IRC_NET_API int IRC_NET_CALL IRC_NET_StartPreview(IRC_NET_HANDLE handle, const IRC_NET_PREVIEW_INFO* previewInfo, IRC_NET_VIDEO_CALLBACK videoCb, void* userData);

/**
 * @brief 开启视频预览
 *
 * @param[in] handle 操作句柄
 * @param[in] previewInfo 预览信息
 * @param[in] videoCb 视频回调函数
 * @param[in] userData 用户自定义数据,会通过videoCb原样抛出
 * @return 错误码
 */
IRC_NET_API int IRC_NET_CALL IRC_NET_StartPreview_V2(IRC_NET_HANDLE handle, const IRC_NET_PREVIEW_INFO* previewInfo, IRC_NET_VIDEO_CALLBACK_V2 videoCb, void* userData);

/**
 * @brief 关闭视频预览
 * 
 * @param[in] handle 操作句柄
 * @return 错误码
 */
IRC_NET_API int IRC_NET_CALL IRC_NET_StopPreview(IRC_NET_HANDLE handle);

/**
 * @brief 预览抓拍
 * 
 * @param[in] handle 操作句柄
 * @param[in] filePath 文件存储路径 保存文件路径+文件名+.jpg
 * @return 错误码
 */
IRC_NET_API int IRC_NET_CALL IRC_NET_PreviewSnapshot(IRC_NET_HANDLE handle, const char* filePath);

/**
 * @brief 开始预览录像
 * 
 * @param[in] handle 操作句柄
 * @param[in] filePath 文件存储路径 保存文件路径+文件名+.mp4
 * @return 错误码
 */
IRC_NET_API int IRC_NET_CALL IRC_NET_StartPreviewRecord(IRC_NET_HANDLE handle, const char* filePath);

/**
 * @brief 停止预览录像
 * 
 * @param[in] handle 操作句柄
 * @return 错误码
 */
IRC_NET_API int IRC_NET_CALL IRC_NET_StopPreviewRecord(IRC_NET_HANDLE handle);

/**
 * @brief 获取实时流RTSP URl地址
 *
 * @param[in] handle 操作句柄
 * @param[in] channel 通道
 * @param[in] streamType 码流类型，参考IRC_NET_STREAM_TYPE
 * @param[out] rtspUrl RTSP流url信息
 * @param[in] inSize rtspUrl输入大小，参考IRC_NET_RTSP_LEN_MAX
 * @return 错误码
 */
IRC_NET_API int IRC_NET_CALL IRC_NET_GetRtspUrl(IRC_NET_HANDLE handle, int channel, int streamType, char* rtspUrl, int inSize);

/**
 * @brief 查询测温规则数量
 *
 * @param[in] handle 操作句柄
 * @param[in] tempRuleIndex 规则索引，其中presetId必须大于等于0，其他参数若为-1时则全部查询
 * @param[out] size 查询数量
 * @return 错误码
 */
IRC_NET_API int IRC_NET_CALL IRC_NET_QueryTempRuleSize(IRC_NET_HANDLE handle, const IRC_NET_TEMP_RULE_INDEX* tempRuleIndex, int* size);


/**
 * @brief 查询测温规则
 *
 * @param[in] handle 操作句柄
 * @param[in] tempRuleIndex 测温规则索引，其中presetId必须大于等于0，其他参数若为-1时则全部查询
 * @param[out] tempRuleInfos[] 测温规则信息
 * @param[in] inSize 测温规则输入大小
 * @param[out] outSize 测温规则输出大小
 * @return 错误码
 */
IRC_NET_API int IRC_NET_CALL IRC_NET_QueryTempRule(IRC_NET_HANDLE handle, const IRC_NET_TEMP_RULE_INDEX* tempRuleIndex, IRC_NET_TEMP_RULE_INFO tempRuleInfos[], int inSize, int* outSize);

/**
 * @brief 查询测温规则（G1设备）
 *
 * @param[in] handle 操作句柄
 * @param[in] tempRuleIndex 测温规则索引，其中presetId必须大于等于0，其他参数若为-1时则全部查询
 * @param[out] tempRuleInfos[] 测温规则信息
 * @param[in] inSize 测温规则输入大小
 * @param[out] outSize 测温规则输出大小
 * @return 错误码
 */
IRC_NET_API int IRC_NET_CALL IRC_NET_QueryTempRule_G1(IRC_NET_HANDLE handle, const IRC_NET_TEMP_RULE_INDEX* tempRuleIndex, IRC_NET_TEMP_RULE_INFO_G1 tempRuleInfos[], int inSize, int* outSize);

/**
 * @brief 添加测温规则
 *
 * @param[in] handle 操作句柄
 * @param[in] tempRegionRuleInfo 测温规则信息
 * @return 错误码
 */
IRC_NET_API int IRC_NET_CALL IRC_NET_AddTempRule(IRC_NET_HANDLE handle, const IRC_NET_TEMP_RULE_INFO* tempRegionRuleInfo);

/**
 * @brief 添加测温规则（G1设备）
 *
 * @param[in] handle 操作句柄
 * @param[in] tempRegionRuleInfo 测温规则信息
 * @return 错误码
 */
IRC_NET_API int IRC_NET_CALL IRC_NET_AddTempRule_G1(IRC_NET_HANDLE handle, const IRC_NET_TEMP_RULE_INFO_G1* tempRegionRuleInfo);

/**
 * @brief 修改测温规则
 *
 * @param[in] handle 操作句柄
 * @param[in] tempRegionRuleInfo 测温规则信息
 * @return 错误码
 */
IRC_NET_API int IRC_NET_CALL IRC_NET_UpdateTempRule(IRC_NET_HANDLE handle, const IRC_NET_TEMP_RULE_INFO* tempRegionRuleInfo);

/**
 * @brief 修改测温规则（G1设备）
 *
 * @param[in] handle 操作句柄
 * @param[in] tempRegionRuleInfo 测温规则信息
 * @return 错误码
 */
IRC_NET_API int IRC_NET_CALL IRC_NET_UpdateTempRule_G1(IRC_NET_HANDLE handle, const IRC_NET_TEMP_RULE_INFO_G1* tempRegionRuleInfo);
/**
 * @brief 删除单个测温规则
 *
 * @param[in] handle 操作句柄
 * @param[in] tempRuleIndex 测温规则索引
 * @return 错误码
 */
IRC_NET_API int IRC_NET_CALL IRC_NET_DeleteTempRule(IRC_NET_HANDLE handle, const IRC_NET_TEMP_RULE_INDEX* tempRuleIndex);

/**
 * @brief 删除全部测温区域
 *
 * @param[in] handle 操作句柄
 * @param[in] presetId 预置点ID
 * @return 错误码
 */
IRC_NET_API int IRC_NET_CALL IRC_NET_DeleteAllTempRule(IRC_NET_HANDLE handle, int presetId);

/**
 * @brief 查询规则温度数量
 *
 * @param[in] handle 操作句柄
 * @param[in] tempRuleIndex 规则索引，其中presetId必须大于等于0，其他参数若为-1时则全部查询
 * @param[out] size 查询数量
 * @return 错误码
 */
IRC_NET_API int IRC_NET_CALL IRC_NET_QueryRuleTempSize(IRC_NET_HANDLE handle, const IRC_NET_TEMP_RULE_INDEX* tempRuleIndex, int* size);

/**
 * @brief 查询规则温度
 *
 * @param[in] handle 操作句柄
 * @param[in] tempRuleIndex 测温规则索引，其中presetId必须大于等于0，其他参数若为-1时则全部查询
 * @param[out] ruleTempInfos[] 规则温度信息
 * @param[in] inSize 规则温度输入大小
 * @param[out] outSize 规则温度输出大小
 * @return 错误码
 */
IRC_NET_API int IRC_NET_CALL IRC_NET_QueryRuleTemp(IRC_NET_HANDLE handle, const IRC_NET_TEMP_RULE_INDEX* tempRuleIndex, IRC_NET_RULE_TEMP_INFO ruleTempInfos[], int inSize, int* outSize);

/**
 * @brief 查询整帧温度
 *
 * @param[in] handle 操作句柄
 * @param[out] ruleTempInfos[] 规则温度信息
 * @return 错误码
 */
IRC_NET_API int IRC_NET_CALL IRC_NET_QueryFrameTemp(IRC_NET_HANDLE handle, IRC_NET_TEMP_INFO* tempInfo);

/**
 * @brief 查询任意点温度
 *
 * @param[in] handle 操作句柄
 * @param[in] point 查询点，采用8192坐标系
 * @param[out] temp 温度值
 * @return 错误码
 */
IRC_NET_API int IRC_NET_CALL IRC_NET_QueryRandomTemp(IRC_NET_HANDLE handle, const IRC_NET_POINT* point, float* temp);

/**
 * @brief 查询整帧测温报警配置
 *
 * @param[in] handle 操作句柄
 * @param[out] alarmConfig 整帧测温报警配置
 * @return 错误码
 */
IRC_NET_API int IRC_NET_CALL IRC_NET_QueryFrameTempAlarmConfig(IRC_NET_HANDLE handle, IRC_NET_FRAME_TEMP_ALARM_CONFIG* alarmConfig);

/**
 * @brief 修改整帧测温报警配置
 *
 * @param[in] handle 操作句柄
 * @param[in] alarmConfig 整帧测温报警配置
 * @return 错误码
 */
IRC_NET_API int IRC_NET_CALL IRC_NET_UpdateFrameTempAlarmConfig(IRC_NET_HANDLE handle, const IRC_NET_FRAME_TEMP_ALARM_CONFIG* alarmConfig);

/**
 * @brief 查询整帧测温报警配置（G1设备）
 *
 * @param[in] handle 操作句柄
 * @param[out] alarmConfig 整帧测温报警配置
 * @return 错误码
 */
IRC_NET_API int IRC_NET_CALL IRC_NET_QueryFrameTempAlarmConfig_G1(IRC_NET_HANDLE handle, IRC_NET_FRAME_TEMP_ALARM_CONFIG_G1* alarmConfig);

/**
 * @brief 修改整帧测温报警配置（G1设备）
 *
 * @param[in] handle 操作句柄
 * @param[in] alarmConfig 整帧测温报警配置
 * @return 错误码
 */
IRC_NET_API int IRC_NET_CALL IRC_NET_UpdateFrameTempAlarmConfig_G1(IRC_NET_HANDLE handle, const IRC_NET_FRAME_TEMP_ALARM_CONFIG_G1* alarmConfig);
/**
 * @brief 查询测温屏蔽区域数量
 *
 * @param[in] handle 操作句柄
 * @param[in] tempMaskIndex 屏蔽区域索引，其中presetId必须大于等于0，其他参数若为-1时则全部查询
 * @param[out] size 查询数量
 * @return 错误码
 */
IRC_NET_API int IRC_NET_CALL IRC_NET_QueryTempMaskSize(IRC_NET_HANDLE handle, const IRC_NET_TEMP_MASK_INDEX* tempMaskIndex, int* size);

/**
 * @brief 查询测温屏蔽区域
 *
 * @param[in] handle 操作句柄
 * @param[in] tempMaskIndex 屏蔽区域索引，presetId必须大于等于0
 * @param[out] tempMaskInfos[] 测温屏蔽区域信息
 * @param[in] inSize 测温屏蔽区域输入大小
 * @param[out] outSize 测温屏蔽区域输出大小
 * @return 错误码
 */
IRC_NET_API int IRC_NET_CALL IRC_NET_QueryTempMask(IRC_NET_HANDLE handle, const IRC_NET_TEMP_MASK_INDEX* tempMaskIndex, IRC_NET_TEMP_MASK_INFO tempMaskInfos[], int inSize, int* outSize);

/**
 * @brief 添加测温屏蔽区域
 *
 * @param[in] handle 操作句柄
 * @param[in] tempMaskInfo 测温屏蔽区域信息
 * @return 错误码
 */
IRC_NET_API int IRC_NET_CALL IRC_NET_AddTempMask(IRC_NET_HANDLE handle, const IRC_NET_TEMP_MASK_INFO* tempMaskInfo);

/**
 * @brief 删除测温屏蔽区域
 *
 * @param[in] handle 操作句柄
 * @param[in] tempMaskIndex 屏蔽区域索引
 * @return 错误码
 */
IRC_NET_API int IRC_NET_CALL IRC_NET_DeleteTempMask(IRC_NET_HANDLE handle, const IRC_NET_TEMP_MASK_INDEX* tempMaskIndex);

/**
 * @brief 删除全部测温屏蔽区域
 *
 * @param[in] handle 操作句柄
 * @param[in] presetId 预置点ID
 * @return 错误码
 */
IRC_NET_API int IRC_NET_CALL IRC_NET_DeleteAllTempMask(IRC_NET_HANDLE handle, int presetId);

/**
 * @brief 可见光到红外坐标温度转换
 *
 * @param[in] handle 操作句柄
 * @param[in] points[] 可见光点坐标数组
 * @param[out] irTempPointInfos[]
 * @param[in] inSize 可见光点坐标数组大小
 * @return 错误码
 */
IRC_NET_API int IRC_NET_CALL IRC_NET_TransformArrTemp(IRC_NET_HANDLE handle, IRC_NET_POINT points[], IRC_NET_IR_TEMP_POINT_INFO irTempPointInfos[], int inSize);

/**
 * @brief 获取测温点模板温度值
 *
 * @param[in] handle 操作句柄
 * @param[out] tempTemplateValue[] 测温点模板温度值数组
 * @param[in] inSize 测温点模板温度值数组大小
 * @return 错误码
 */
IRC_NET_API int IRC_NET_CALL IRC_NET_GetTempTemplateValue(IRC_NET_HANDLE handle, int tempTemplateValue[], int inSize);

/**
 * @brief 获取测温点模板数组大小
 *
 * @param[in] handle 操作句柄
 * @param[out] outSize 测温点模板数组大小
 * @return 错误码
 */
IRC_NET_API int IRC_NET_CALL IRC_NET_GetTempTemplateSize(IRC_NET_HANDLE handle, int* outSize);

/**
 * @brief 获取测温点模板
 *
 * @param[in] handle 操作句柄
 * @param[out] tempTemplate[] 测温点模板数组
 * @param[in] inSize 测温点模板输入数组大小
 * @param[out] outSize 测温点模板输出数组大小
 * @return 错误码
 */
IRC_NET_API int IRC_NET_CALL IRC_NET_GetTempTemplate(IRC_NET_HANDLE handle, int tempTemplate[], int inSize,int* outSize);

/**
 * @brief 设置测温点模板
 *
 * @param[in] handle 操作句柄
 * @param[in] tempTemplate[] 测温点模板数组
 * @param[in] inSize 测温点模板数组大小
 * @return 错误码
 */
IRC_NET_API int IRC_NET_CALL IRC_NET_SetTempTemplate(IRC_NET_HANDLE handle, const int tempTemplate[], int inSize);

/**
 * @brief 获取IRG格式图片
 * 
 * @param[in] handle 操作句柄
 * @param[in] irgFilePath 保存文件路径+文件名+.irg
 * @param[in] jpgFilePath 保存文件路径+文件名+.jpg
 * @return 错误码
 */
IRC_NET_API int IRC_NET_CALL IRC_NET_GetIRGImage(IRC_NET_HANDLE handle, const char* irgFilePath, const char* jpgFilePath);

/**
 * @brief 获取国网664格式图片
 * 
 * @param[in] handle 操作句柄
 * @param[in] filePath 保存文件路径+文件名+.jpg
 * @return 错误码
 */
IRC_NET_API int IRC_NET_CALL IRC_NET_GetDLT664Image(IRC_NET_HANDLE handle, const char* filePath);

/**
 * @brief 同步系统时间
 * 
 * @param[in] handle 操作句柄
 * @param[in] datetime 同步时间，格式为“2020-05-21 12:22:33”
 * @return 错误码
 */
IRC_NET_API int IRC_NET_CALL IRC_NET_SyncSystemTime(IRC_NET_HANDLE handle, const char* datetime);

/**
 * @brief 快门校正
 * 
 * @param[in] handle 操作句柄
 * @return 错误码
 */
IRC_NET_API int IRC_NET_CALL IRC_NET_CorrectShutter(IRC_NET_HANDLE handle);

/**
 * @brief 获取温度条状态
 * 
 * @param[in] handle 操作句柄
 * @param[out] state 温度条状态，0：关闭 1：打开
 * @return 错误码
 */
IRC_NET_API int IRC_NET_CALL IRC_NET_GetTempBarState(IRC_NET_HANDLE handle, int* state);

/**
 * @brief 设置温度条状态
 * 
 * @param[in] handle 操作句柄
 * @param[in] state 温度条状态，0：关闭 1：打开
 * @return 错误码
 */
IRC_NET_API int IRC_NET_CALL IRC_NET_SetTempBarState(IRC_NET_HANDLE handle, int state);

/**
 * @brief 获取图像色板序号
 * 
 * @param[in] handle 操作句柄
 * @param[out] palleteType 色板类型，参考IRC_NET_PALETTE_TYPE
 * @return 错误码
 */
IRC_NET_API int IRC_NET_CALL IRC_NET_GetPalleteType(IRC_NET_HANDLE handle, int* palleteType);

/**
 * @brief 设置图像色板序号
 * 
 * @param[in] handle 操作句柄
 * @param[in] palleteType 色板类型，参考IRC_NET_PALETTE_TYPE
 * @return 错误码
 */
IRC_NET_API int IRC_NET_CALL IRC_NET_SetPalleteType(IRC_NET_HANDLE handle, int palleteType);

/**
 * @brief 获取测温档位
 * 
 * @param[in] handle 操作句柄
 * @param[out] level 测温档位，参考IRC_NET_TEMP_LEVEL_TYPE
 * @return 错误码
 */
IRC_NET_API int IRC_NET_CALL IRC_NET_GetTempLevel(IRC_NET_HANDLE handle, int* level);

/**
 * @brief 设置测温档位
 * 
 * @param[in] handle 操作句柄
 * @param[in] level 测温档位，参考IRC_NET_TEMP_LEVEL_TYPE
 * @return 错误码
 */
IRC_NET_API int IRC_NET_CALL IRC_NET_SetTempLevel(IRC_NET_HANDLE handle, int level);

/**
 * @brief 获取OSD总状态
 *
 * @param[in] handle 操作句柄
 * @param[out] osdMode 测温信息叠加方式，参考IRC_NET_OSD_MODE
 * @return 错误码
 */
IRC_NET_API int IRC_NET_CALL IRC_NET_GetOSDState(IRC_NET_HANDLE handle, int* osdMode);

/**
 * @brief 设置OSD总状态
 *
 * @param[in] handle 操作句柄
 * @param[in] osdMode 测温信息叠加方式，参考IRC_NET_OSD_MODE
 * @return 错误码
 */
IRC_NET_API int IRC_NET_CALL IRC_NET_SetOSDState(IRC_NET_HANDLE handle, int osdMode);

/**
 * @brief 获取时间标题信息
 * 
 * @param[in] handle 操作句柄
 * @param[in] channel 通道
 * @param[out] timeTitleInfo 时间标题信息
 * @return 错误码
 */
IRC_NET_API int IRC_NET_CALL IRC_NET_GetOSDTimeTitleInfo(IRC_NET_HANDLE handle, int channel, IRC_NET_OSD_TIME_TITLE_INFO* timeTitleInfo);

/**
 * @brief 设置时间标题信息
 * 
 * @param[in] handle 操作句柄
 * @param[in] channel 通道
 * @param[in] timeTitleInfo 时间标题信息
 * @return 错误码
 */
IRC_NET_API int IRC_NET_CALL IRC_NET_SetOSDTimeTitleInfo(IRC_NET_HANDLE handle, int channel, const IRC_NET_OSD_TIME_TITLE_INFO* timeTitleInfo);

/**
 * @brief 获取通道标题信息
 *
 * @param[in] handle 操作句柄
 * @param[in] channel 通道
 * @param[out] channelTitleInfo 通道标题信息
 * @return 错误码
 */
IRC_NET_API int IRC_NET_CALL IRC_NET_GetOSDChannelTitleInfo(IRC_NET_HANDLE handle, int channel, IRC_NET_OSD_CHANNEL_TITLE_INFO* channelTitleInfo);

/**
 * @brief 设置通道标题信息
 *
 * @param[in] handle 操作句柄
 * @param[in] channel 通道
 * @param[in] channelTitleInfo 通道标题信息
 * @return 错误码
 */
IRC_NET_API int IRC_NET_CALL IRC_NET_SetOSDChannelTitleInfo(IRC_NET_HANDLE handle, int channel, const IRC_NET_OSD_CHANNEL_TITLE_INFO* channelTitleInfo);

/**
 * @brief 获取环境参数
 *
 * @param[in] handle 操作句柄
 * @param[out] envParam 环境参数
 * @return 错误码
 */
IRC_NET_API int IRC_NET_CALL IRC_NET_GetEnvParam(IRC_NET_HANDLE handle, IRC_NET_ENV_PARAM* envParam);

/**
 * @brief 设置环境参数
 *
 * @param[in] handle 操作句柄
 * @param[in] envParam 环境参数
 * @return 错误码
 */
IRC_NET_API int IRC_NET_CALL IRC_NET_SetEnvParam(IRC_NET_HANDLE handle, const IRC_NET_ENV_PARAM* envParam);

/**
 * @brief 获取测温帧率
 *
 * @param[in] handle 操作句柄
 * @param[out] rate 测温帧率，范围[0，采集帧率]，默认12，最高支持12帧
 * @return 错误码
 */
IRC_NET_API int IRC_NET_CALL IRC_NET_GetFrameRate(IRC_NET_HANDLE handle, int* rate);

/**
 * @brief 设置测温帧率
 *
 * @param[in] handle 操作句柄
 * @param[in] rate 测温帧率，范围[0，采集帧率]，默认12，最高支持12帧
 * @return 错误码
 */
IRC_NET_API int IRC_NET_CALL IRC_NET_SetFrameRate(IRC_NET_HANDLE handle, int rate);

/**
 * @brief 获取测温使能开关
 *
 * @param[in] handle 操作句柄
 * @param[out] enable 测温使能开关，0-关，1-开
 * @return 错误码
 */
IRC_NET_API int IRC_NET_CALL IRC_NET_GetTempEnable(IRC_NET_HANDLE handle, int* enable);

/**
 * @brief 设置测温使能开关
 *
 * @param[in] handle 操作句柄
 * @param[in] enable 测温使能开关，0-关，1-开
 * @return 错误码
 */
IRC_NET_API int IRC_NET_CALL IRC_NET_SetTempEnable(IRC_NET_HANDLE handle, int enable);

/**
 * @brief 获取温宽信息
 * 
 * @param[in] handle 操作句柄
 * @param[out] tempSpanInfo 温宽信息
 * @return 错误码
 */
IRC_NET_API int IRC_NET_CALL IRC_NET_GetTempSpanInfo(IRC_NET_HANDLE handle, IRC_NET_TEMP_SPAN_INFO* tempSpanInfo);

/**
 * @brief 设置温宽信息
 * 
 * @param[in] handle 操作句柄
 * @param[in] tempSpanInfo 温宽信息
 * @return 错误码
 */
IRC_NET_API int IRC_NET_CALL IRC_NET_SetTempSpanInfo(IRC_NET_HANDLE handle, const IRC_NET_TEMP_SPAN_INFO* tempSpanInfo);

/**
 * @brief 获取IP配置
 *
 * @param[in] handle 操作句柄
 * @param[out] ipConfig ip配置
 * @return 错误码
 */
IRC_NET_API int IRC_NET_CALL IRC_NET_GetIpConfig(IRC_NET_HANDLE handle, IRC_NET_IP_CONFIG* ipConfig);

/**
 * @brief 设置IP配置
 *
 * @param[in] handle 操作句柄
 * @param[in] ipConfig ip配置
 * @return 错误码
 */
IRC_NET_API int IRC_NET_CALL IRC_NET_SetIpConfig(IRC_NET_HANDLE handle, const IRC_NET_IP_CONFIG* ipConfig);

/**
 * @brief 获取通道目标识别配置
 *
 * @param[in] handle 操作句柄
 * @param[in] channel 通道号
 * @param[out] targetRecognitionConfig 通道目标识别配置
 * @return 错误码
 */
IRC_NET_API int IRC_NET_CALL IRC_NET_GetTargetRecognitionConfig(IRC_NET_HANDLE handle, int channel, IRC_NET_TARGET_RECOGNITION_CONFIG* targetRecognitionConfig);

/**
 * @brief 设置通道目标识别配置
 *
 * @param[in] handle 操作句柄
 * @param[in] channel 通道号
 * @param[in] targetRecognitionConfig 通道目标识别配置
 * @return 错误码
 */
IRC_NET_API int IRC_NET_CALL IRC_NET_SetTargetRecognitionConfig(IRC_NET_HANDLE handle, int channel, const IRC_NET_TARGET_RECOGNITION_CONFIG* targetRecognitionConfig);

/**
 * @brief 导出配置文件
 *
 * @param[in] handle 操作句柄
 * @param[in] filePath 文件路径
 * @return 错误码
 */
IRC_NET_API int IRC_NET_CALL IRC_NET_ExportConfigFile(IRC_NET_HANDLE handle, const char* filePath);

/**
 * @brief 导入配置文件
 *
 * @param[in] handle 操作句柄
 * @param[in] filePath 文件路径
 * @return 错误码
 */
IRC_NET_API int IRC_NET_CALL IRC_NET_ImportConfigFile(IRC_NET_HANDLE handle, const char* filePath);

/**
 * @brief 设备重启
 * @param[in] handle 操作句柄
 * @return 错误码
 */
IRC_NET_API int IRC_NET_CALL IRC_NET_SystemReboot(IRC_NET_HANDLE handle);

/**
 * @brief 设备断电重启
 * @param[in] handle 操作句柄
 * @return 错误码
 */
IRC_NET_API int IRC_NET_CALL IRC_NET_SystemRestart(IRC_NET_HANDLE handle);

/**
 * @brief 云台控制操作
 *
 * @param[in] handle 操作句柄
 * @param[in] ptzControlInfo 云台控制信息
 * @return 错误码
 */
IRC_NET_API int IRC_NET_CALL IRC_NET_PtzControl(IRC_NET_HANDLE handle, const IRC_NET_PTZ_CONTROL_INFO* ptzControlInfo);

/**
 * @brief 获取云台辅助命令状态
 *
 * @param[in] handle 操作句柄
 * @param[out] ptzAuxState 云台辅助功能状态
 * @return 错误码
 */
IRC_NET_API int IRC_NET_CALL IRC_NET_GetPtzAuxState(IRC_NET_HANDLE handle, IRC_NET_PTZ_AUX_STATE* ptzAuxState);

/**
 * @brief 查询预置点数量
 * 
 * @param[in] handle 操作句柄
 * @param[out] size 查询数量
 * @return 错误码
 */
IRC_NET_API int IRC_NET_CALL IRC_NET_QueryPtzPresetSize(IRC_NET_HANDLE handle, int* size);

/**
 * @brief 查询预置点
 *
 * @param[in] handle 操作句柄
 * @param[out] ptzPresetInfos[] 预置点信息
 * @param[in] inSize 预置点输入大小
 * @param[out] outSize 预置点输出大小
 * @return 错误码
 */
IRC_NET_API int IRC_NET_CALL IRC_NET_QueryPtzPreset(IRC_NET_HANDLE handle, IRC_NET_PTZ_PRESET_INFO ptzPresetInfos[], int inSize, int* outSize);

/**
 * @brief 预置点控制
 *
 * @param[in] handle 操作句柄
 * @param[in] ptzPresetCmd 预置点控制命令，参考IRC_NET_PTZ_PRESET_CMD_TYPE
 * @param[in] ptzPresetInfo 预置点信息
 * @return 错误码
 */
IRC_NET_API int IRC_NET_CALL IRC_NET_PtzPresetControl(IRC_NET_HANDLE handle, int ptzPresetCmd, const IRC_NET_PTZ_PRESET_INFO* ptzPresetInfo);

/**
 * @brief 查询当前预置点ID
 *
 * @param[in] handle 操作句柄
 * @param[out] ptzPresetId 当前预置点ID
 * @return 错误码
 */
IRC_NET_API int IRC_NET_CALL IRC_NET_QueryPtzPresetId(IRC_NET_HANDLE handle, int* ptzPresetId);

/**
 * @brief 查询巡航组配置数量
 *
 * @param[in] handle 操作句柄
 * @param[out] size 查询数量
 * @return 错误码
 */
IRC_NET_API int IRC_NET_CALL IRC_NET_QueryPtzTourSize(IRC_NET_HANDLE handle, int* size);

/**
 * @brief 查询巡航组配置
 *
 * @param[in] handle 操作句柄
 * @param[in] id 巡航组id，范围[1，255]，值为-1时查询全部
 * @param[out] ptzTourInfos[] 巡航组信息
 * @param[in] inSize 巡航组输入大小
 * @param[out] outSize 巡航组输出大小
 * @return 错误码
 */
IRC_NET_API int IRC_NET_CALL IRC_NET_QueryPtzTour(IRC_NET_HANDLE handle, int id, IRC_NET_PTZ_TOUR_INFO ptzTourInfos[], int inSize, int* outSize);

/**
 * @brief 巡航组控制
 *
 * @param[in] handle 操作句柄
 * @param[in] ptzTourCmd 巡航组控制命令，参考IRC_NET_PTZ_TOUR_CMD_TYPE
 * @param[in] ptzTourInfo 巡航组信息
 * @return 错误码
 */
IRC_NET_API int IRC_NET_CALL IRC_NET_PtzTourControl(IRC_NET_HANDLE handle, int ptzTourCmd, const IRC_NET_PTZ_TOUR_INFO* ptzTourInfo);

/**
 * @brief 查询巡迹配置数量
 *
 * @param[in] handle 操作句柄
 * @param[out] size 查询数量
 * @return 错误码
 */
IRC_NET_API int IRC_NET_CALL IRC_NET_QueryPtzPatternSize(IRC_NET_HANDLE handle, int* size);

/**
 * @brief 查询巡迹配置
 *
 * @param[in] handle 操作句柄
 * @param[out] ptzPatternInfos[] 巡迹信息，最多IRC_NET_PATTERN_NUM_MAX
 * @param[in] inSize 巡迹输入大小
 * @param[out] outSize 巡迹输出大小
 * @return 错误码
 */
IRC_NET_API int IRC_NET_CALL IRC_NET_QueryPtzPattern(IRC_NET_HANDLE handle, IRC_NET_PTZ_PATTERN_INFO ptzPatternInfos[], int inSize, int* outSize);

/**
 * @brief 巡迹控制
 *
 * @param[in] handle 操作句柄
 * @param[in] ptzPatternCmd 巡迹控制命令，参考IRC_NET_PTZ_PATTERN_CMD_TYPE
 * @param[in] ptzPatternId 巡迹ID
 * @return 错误码
 */
IRC_NET_API int IRC_NET_CALL IRC_NET_PtzPatternControl(IRC_NET_HANDLE handle, int ptzPatternCmd, int ptzPatternId);

/**
 * @brief 云台恢复默认配置
 *
 * @param[in] handle 操作句柄
 * @return 错误码
 */
IRC_NET_API int IRC_NET_CALL IRC_NET_ResetPtzConfig(IRC_NET_HANDLE handle);

/**
 * @brief 云台精确定位
 *
 * @param[in] handle 操作句柄
 * @param[in] positionParam 精确定位参数
 * @return 错误码
 */
IRC_NET_API int IRC_NET_CALL IRC_NET_PtzPosition(IRC_NET_HANDLE handle, const IRC_NET_PTZ_POSITION_PARAM* positionParam);

/**
 * @brief 云台精确定位V1
 *
 * @param[in] handle 操作句柄
 * @param[in] channel 通道号
 * @param[in] positionParam 精确定位参数
 * @return 错误码
 */
IRC_NET_API int IRC_NET_CALL IRC_NET_PtzPosition_V1(IRC_NET_HANDLE handle, int channel,const IRC_NET_PTZ_POSITION_PARAM* positionParam);

/**
 * @brief 获取云台位置
 * @param[in] handle 操作句柄
 * @param[out] positionParam 云台位置参数
 * @return 错误码
 */
IRC_NET_API int IRC_NET_CALL IRC_NET_GetCurrentPtz(IRC_NET_HANDLE handle, IRC_NET_PTZ_POSITION_PARAM* positionParam);

/**
 * @brief 获取云台位置V1
 * @param[in] handle 操作句柄
 * @param[out] positionParam 云台位置参数
 * @return 错误码
 */
IRC_NET_API int IRC_NET_CALL IRC_NET_GetCurrentPtz_V1(IRC_NET_HANDLE handle, IRC_NET_PTZ_POSITION_PARAM_V1* positionParam);

/**
 * @brief 3D定位
 *
 * @param[in] handle 操作句柄
 * @param[in] positionParam 3D定位参数
 * @return 错误码
 */
IRC_NET_API int IRC_NET_CALL IRC_NET_Ptz3DPosition(IRC_NET_HANDLE handle, const IRC_NET_PTZ_3D_POSITION_PARAM* positionParam);

/**
 * @brief 区域聚焦
 *
 * @param[in] handle 操作句柄
 * @param[in] focusParam 区域聚焦参数
 * @return 错误码
 */
IRC_NET_API int IRC_NET_CALL IRC_NET_PtzRegionFocus(IRC_NET_HANDLE handle, const IRC_NET_PTZ_REGION_FOCUS_PARAM* focusParam);

/**
 * @brief 手动跟踪
 *
 * @param[in] handle 操作句柄
 * @param[in] trackParam 手动跟踪参数
 * @return 错误码
 */
IRC_NET_API int IRC_NET_CALL IRC_NET_PtzManualTrack(IRC_NET_HANDLE handle, const IRC_NET_PTZ_MANUAL_TRACK_PARAM* trackParam);

/**
 * @brief 镜头初始化
 *
 * @param[in] handle 操作句柄
 * @param[in] channel 通道号
 * @return 错误码
 */
IRC_NET_API int IRC_NET_CALL IRC_NET_PtzLensInit(IRC_NET_HANDLE handle, int channel);

/**
 * @brief 查询区域扫描信息数量
 *
 * @param[in] handle 操作句柄
 * @param[out] size 区域数量
 * @return 错误码
 */
IRC_NET_API int IRC_NET_CALL IRC_NET_QueryPtzRegionScanInfoSize(IRC_NET_HANDLE handle, int* size);

/**
 * @brief 查询区域扫描信息
 *
 * @param[in] handle 操作句柄
 * @param[out] regionScanInfos[] 区域扫描信息
 * @param[in] inSize 区域扫描输入大小
 * @param[out] outSize 区域扫描输出大小
 * @return 错误码
 */
IRC_NET_API int IRC_NET_CALL IRC_NET_QueryPtzRegionScanInfo(IRC_NET_HANDLE handle, IRC_NET_REGION_SCAN_INFO regionScanInfos[], int inSize, int* outSize);

/**
 * @brief 设置区域扫描信息
 *
 * @param[in] handle 操作句柄
 * @param[in] regionScanInfo 区域扫描设置信息
 * @return 错误码
 */
IRC_NET_API int IRC_NET_CALL IRC_NET_SetPtzRegionScanInfo(IRC_NET_HANDLE handle, const IRC_NET_REGION_SCAN_INFO* regionScanInfo);

/**
 * @brief 删除区域扫描信息
 *
 * @param[in] handle 操作句柄
 * @param[in] id 区域扫描id，id大于等于1，id 等于-1则删除全部
 * @return 错误码
 */
IRC_NET_API int IRC_NET_CALL IRC_NET_DeletePtzRegionScanInfo(IRC_NET_HANDLE handle, int id);

/**
 * @brief 区域扫描控制
 * 
 * @param[in] handle 操作句柄
 * @param[in] id 区域扫描id
 * @param[in] state 区域扫描状态，true-开始，false-停止
 * @return 错误码
 */
IRC_NET_API int IRC_NET_CALL IRC_NET_PtzRegionScanControl(IRC_NET_HANDLE handle, int id,bool state);

/**
 * @brief 查询开机动作信息
 *
 * @param[in] handle 操作句柄
 * @param[out] bootActionInfo 开机动作信息
 * @return 错误码
 */
IRC_NET_API int IRC_NET_CALL IRC_NET_QueryPtzBootActionInfo(IRC_NET_HANDLE handle, IRC_NET_BOOT_ACTION_INFO* bootActionInfo);

/**
 * @brief 设置开机动作信息
 *
 * @param[in] handle 操作句柄
 * @param[in] bootActionInfo 开机动作信息
 * @return 错误码
 */
IRC_NET_API int IRC_NET_CALL IRC_NET_SetPtzBootActionInfo(IRC_NET_HANDLE handle, const IRC_NET_BOOT_ACTION_INFO* bootActionInfo);

/**
 * @brief 查询空闲动作信息
 *
 * @param[in] handle 操作句柄
 * @param[out] parkActionInfo 空闲动作信息
 * @return 错误码
 */
IRC_NET_API int IRC_NET_CALL IRC_NET_QueryPtzParkActionInfo(IRC_NET_HANDLE handle, IRC_NET_PARK_ACTION_INFO* parkActionInfo);

/**
 * @brief 设置空闲动作信息
 *
 * @param[in] handle 操作句柄
 * @param[in] parkActionInfo 空闲动作信息
 * @return 错误码
 */
IRC_NET_API int IRC_NET_CALL IRC_NET_SetPtzParkActionInfo(IRC_NET_HANDLE handle, const IRC_NET_PARK_ACTION_INFO* parkActionInfo);

/**
 * @brief 云台精确跟踪定位
 *
 * @param[in] handle 操作句柄
 * @param[in] positionParam 精确跟踪定位参数
 * @return 错误码
 */
IRC_NET_API int IRC_NET_CALL IRC_NET_PtzTrackingPosition(IRC_NET_HANDLE handle, const IRC_NET_PTZ_TRACKING_POSITION_PARAM* positionParam);

/**
 * @brief 获取倍率
 *
 * @param[in] handle 操作句柄
 * @param[in] channel 通道号
 * @param[out] zoomMultipler 倍率值
 * @return 错误码
 */
IRC_NET_API int IRC_NET_CALL IRC_NET_GetPtzZoomMultiplier(IRC_NET_HANDLE handle,int channel, float* zoomMultipler);

/**
 * @brief 设置倍率
 *
 * @param[in] handle 操作句柄
 * @param[in] channel 通道号
 * @param[in] zoomMultipler 倍率值
 * @return 错误码
 */
IRC_NET_API int IRC_NET_CALL IRC_NET_SetPtzZoomMultiplier(IRC_NET_HANDLE handle, int channel, float zoomMultipler);

/**
 * @brief 获取断电记忆配置
 *
 * @param[in] handle 操作句柄
 * @param[out] powerOffConfig 断电记忆配置
 * @return 错误码
 */
IRC_NET_API int IRC_NET_CALL IRC_NET_GetPtzPowerOffConfig(IRC_NET_HANDLE handle, IRC_NET_PTZ_POWEROFF_CONFIG* powerOffConfig);

/**
 * @brief 设置断电记忆配置
 *
 * @param[in] handle 操作句柄
 * @param[in] powerOffConfig 断电记忆配置
 * @return 错误码
 */
IRC_NET_API int IRC_NET_CALL IRC_NET_SetPtzPowerOffConfig(IRC_NET_HANDLE handle, const IRC_NET_PTZ_POWEROFF_CONFIG* powerOffConfig);

/**
 * @brief 获取云台运行状态
 *
 * @param[in] handle 操作句柄
 * @param[out] statusParam 云台运行状态参数
 * @return 错误码
 */
IRC_NET_API int IRC_NET_CALL IRC_NET_GetPtzRunningStatus(IRC_NET_HANDLE handle, IRC_NET_PTZ_RUNNING_STATUS_PARAM* statusParam);

/**
* @brief 电子云台控制
* @param[in] handle 操作句柄
* @param[in] controlInfo 电子云台转动信息
* @return 错误码
*/
IRC_NET_API int IRC_NET_CALL IRC_NET_ElectronicPtzControl(IRC_NET_HANDLE handle, const IRC_NET_ELECTRONIC_PTZ_CONTROL_INFO* controlInfo);

/**
 * @brief 获取目标跟踪配置
 *
 * @param[in] handle 操作句柄
 * @param[in] channel 通道号
 * @param[out] targetTrackData 目标跟踪配置信息
 * @return 错误码
 */
IRC_NET_API int IRC_NET_CALL IRC_NET_GetTargetTrackConfig(IRC_NET_HANDLE handle, int channel, IRC_NET_TARGET_TRACK_DATA* targetTrackData);

/**
 * @brief 设置目标跟踪配置
 *
 * @param[in] handle 操作句柄
 * @param[in] channel 通道号
 * @param[in] targetTrackData 目标跟踪配置信息
 * @return 错误码
 */
IRC_NET_API int IRC_NET_CALL IRC_NET_SetTargetTrackConfig(IRC_NET_HANDLE handle, int channel, const IRC_NET_TARGET_TRACK_DATA* targetTrackData);

/**
 * @brief 获取雨刷配置信息
 *
 * @param[in] handle 操作句柄
 * @param[out] wiperMode 雨刷模式 0-自动，1-手动
 * @return 错误码
 */
IRC_NET_API int IRC_NET_CALL IRC_NET_GetWiperConfigInfo(IRC_NET_HANDLE handle, int* wiperMode);

/**
 * @brief 设置雨刷配置信息
 *
 * @param[in] handle 操作句柄
 * @param[in] wiperMode 雨刷模式 0-自动，1-手动
 * @return 错误码
 */
IRC_NET_API int IRC_NET_CALL IRC_NET_SetWiperConfigInfo(IRC_NET_HANDLE handle, int wiperMode);

/**
 * @brief 获取补光灯配置信息
 *
 * @param[in] handle 操作句柄
 * @param[out] fillLightConfigInfo 补光灯配置信息
 * @return 错误码
 */
IRC_NET_API int IRC_NET_CALL IRC_NET_GetFillLightConfigInfo(IRC_NET_HANDLE handle, IRC_NET_FILL_LIGHT_CONFIG_INFO* fillLightConfigInfo);

/**
 * @brief 设置补光灯配置信息
 *
 * @param[in] handle 操作句柄
 * @param[in] fillLightConfigInfo 补光灯配置信息
 * @return 错误码
 */
IRC_NET_API int IRC_NET_CALL IRC_NET_SetFillLightConfigInfo(IRC_NET_HANDLE handle, const IRC_NET_FILL_LIGHT_CONFIG_INFO* fillLightConfigInfo);

/**
 * @brief 激光测距
 *
 * @param[in] handle 操作句柄
 * @param[out] distance 激光测距距离
 * @return 错误码
 */
IRC_NET_API int IRC_NET_CALL IRC_NET_GetLaserDistance(IRC_NET_HANDLE handle, int* distance);

/**
 * @brief 获取激光测距OSD参数
 *
 * @param[in] handle 操作句柄
 * @param[in] channel 通道
 * @param[out] laserDistanceOsdParam 激光测距OSD参数
 * @return 错误码
 */
IRC_NET_API int IRC_NET_CALL IRC_NET_GetLaserDistanceOsdParam(IRC_NET_HANDLE handle, int channel, IRC_NET_LASER_DISTANCE_OSD_PARAM* laserDistanceOsdParam);

/**
 * @brief 设置激光测距OSD参数
 *
 * @param[in] handle 操作句柄
 * @param[in] channel 通道
 * @param[in] laserDistanceOsdParam 激光测距OSD参数
 * @return 错误码
 */
IRC_NET_API int IRC_NET_CALL IRC_NET_SetLaserDistanceOsdParam(IRC_NET_HANDLE handle, int channel, const IRC_NET_LASER_DISTANCE_OSD_PARAM* laserDistanceOsdParam);

/**
 * @brief 查询文件数量
 *
 * @param[in] handle 操作句柄
 * @param[in] queryParam 查询参数
 * @param[out] size 查询数量
 * @return 错误码
 */
IRC_NET_API int IRC_NET_CALL IRC_NET_QueryFileSize(IRC_NET_HANDLE handle, const IRC_NET_FILE_QUERY_PARAM* queryParam, int* size);

/**
 * @brief 查询文件
 *
 * @param[in] handle 操作句柄
 * @param[in] condition 查询条件
 * @param[out] fileInfos[] 文件信息
 * @param[in] inSize 文件信息输入大小
 * @param[out] outSize 文件信息输出大小
 * @return 错误码
 */
IRC_NET_API int IRC_NET_CALL IRC_NET_QueryFile(IRC_NET_HANDLE handle, const IRC_NET_FILE_QUERY_PARAM* queryParam, IRC_NET_FILE_INFO fileInfos[], int inSize, int* outSize);

/**
 * @brief 下载文件
 *
 * @param[in] handle 操作句柄
 * @param[in] downloadInfo 下载信息
 * @return 错误码，成功返回下载句柄
 */
IRC_NET_API int IRC_NET_CALL IRC_NET_StartDownloadFile(IRC_NET_HANDLE handle, const IRC_NET_FILE_DOWNLOAD_INFO* downloadInfo);

/**
 * @brief 查询下载进度
 *
 * @param[in] handle 操作句柄
 * @param[in] fileHandle 下载句柄，IRC_NET_StartDownloadFile返回值
 * @param[out] downloadProgress 下载进度
 * @return 错误码
 */
IRC_NET_API int IRC_NET_CALL IRC_NET_GetDownloadProgress(IRC_NET_HANDLE handle, int fileHandle, IRC_NET_FILE_DOWNLOAD_PROGRESS* downloadProgress);

/**
 * @brief 停止下载
 *
 * @param[in] handle 操作句柄
 * @param[in] fileHandle 下载句柄，IRC_NET_StartDownloadFile返回值
 * @return 错误码
 */
IRC_NET_API int IRC_NET_CALL IRC_NET_StopDownloadFile(IRC_NET_HANDLE handle, int fileHandle);

/**
 * @brief 转台控制
 *
 * @param[in] handle 操作句柄
 * @param[in] swivelCmd 转台控制命令，参考IRC_NET_SWIVEL_CMD_TYPE
 * @return 错误码
 */
IRC_NET_API int IRC_NET_CALL IRC_NET_SwivelControl(IRC_NET_HANDLE handle, int swivelCmd);

/**
 * @brief 透传设置
 *
 * @param[in] handle 操作句柄
 * @param[in] state 透传状态，0：关闭 1：打开
 * @return 错误码
 */
IRC_NET_API int IRC_NET_CALL IRC_NET_SetTransparentState(IRC_NET_HANDLE handle, int state);

/**
 * @brief 数据透传
 *
 * @param[in] handle 操作句柄
 * @param[in] sendBuf 发送数据缓冲区
 * @param[in] sendBufSize 发送数据缓冲区大小
 * @param[out] recvBuf 接收数据缓冲区
 * @param[in] recvBufInSize 接收数据缓冲区大小，最多1024字节
 * @param[out] recvBufOutSize 实际接收数据长度
 * @param[in] timeout 超时时间，单位毫秒
 * @return 错误码
 */
IRC_NET_API int IRC_NET_CALL IRC_NET_TransparentData(IRC_NET_HANDLE handle, const char* sendBuf, int sendBufSize, char* recvBuf, int recvBufInSize,int* recvBufOutSize, int timeout);

/**
 * @brief 色板文件上传
 * @param[in] handle 操作句柄
 * @param[in] fileName 色板文件路径
 * @return 错误码
 */
IRC_NET_API int IRC_NET_CALL IRC_NET_UploadSwatchFile(IRC_NET_HANDLE handle, const char* fileName);

/**
 * @brief 获取加速度相关数据
 * @param[in] handle 操作句柄
 * @param[out] accelerationData 加速度相关数据
 * @return 错误码
 */
IRC_NET_API int IRC_NET_CALL IRC_NET_GetAccelerationData(IRC_NET_HANDLE handle, IRC_NET_ACCELERATION_DATA* accelerationData);

/**
 * @brief 获取可见光日夜模式参数
 * @param[in] handle 操作句柄
 * @param[out] dayNightModeParam 可见光日夜模式参数
 * @return 错误码
 */
IRC_NET_API int IRC_NET_CALL IRC_NET_GetDayNightModeParam(IRC_NET_HANDLE handle, IRC_NET_DAY_NIGHT_MODE_PARAM* dayNightModeParam);

/**
 * @brief 设置可见光日夜模式参数
 * @param[in] handle 操作句柄
 * @param[in] dayNightModeParam 可见光日夜模式参数
 * @return 错误码
 */
IRC_NET_API int IRC_NET_CALL IRC_NET_SetDayNightModeParam(IRC_NET_HANDLE handle, const IRC_NET_DAY_NIGHT_MODE_PARAM* dayNightModeParam);

/**
 * @brief 获取Logo图片
 *
 * @param[in] handle 操作句柄
 * @param[in] id 0-登录界面logo,1-主界面logo
 * @param[in] filePath 文件路径
 * @return 错误码
 */
IRC_NET_API int IRC_NET_CALL IRC_NET_GetLogoPicture(IRC_NET_HANDLE handle, int id,const char* filePath);

/**
 * @brief 设置Logo图片
 *
 * @param[in] handle 操作句柄
 * @param[in] id 0-登录界面logo,1-主界面logo
 * @param[in] filePath 文件路径
 * @return 错误码
 */
IRC_NET_API int IRC_NET_CALL IRC_NET_SetLogoPicture(IRC_NET_HANDLE handle,int id, const char* filePath);

/**
 * @brief 获取测温单位
 * @param[in] handle 操作句柄
 * @param[out] unit 温度单位
 * @return 错误码
 */
IRC_NET_API int IRC_NET_CALL IRC_NET_GetTempUnit(IRC_NET_HANDLE handle, int* unit);

/**
 * @brief 设置测温单位
 * @param[in] handle 操作句柄
 * @param[in] unit 温度单位
 * @return 错误码
 */
IRC_NET_API int IRC_NET_CALL IRC_NET_SetTempUnit(IRC_NET_HANDLE handle, int unit);

 /**
 * @brief 获取热成像图像亮度参数
 * @param[in] handle 操作句柄
 * @param[out] luminance 亮度
 * @return 错误码
 */
IRC_NET_API int IRC_NET_CALL IRC_NET_GetThermalImageLuminance(IRC_NET_HANDLE handle, int* luminance);

 /**
 * @brief 设置热成像图像亮度参数
 * @param[in] handle 操作句柄
 * @param[in] luminance 亮度
 * @return 错误码
 */
IRC_NET_API int IRC_NET_CALL IRC_NET_SetThermalImageLuminance(IRC_NET_HANDLE handle, int luminance);

 /**
 * @brief 获取热成像图像对比度参数
 * @param[in] handle 操作句柄
 * @param[out] contrast 对比度
 * @return 错误码
 */
IRC_NET_API int IRC_NET_CALL IRC_NET_GetThermalImageContrast(IRC_NET_HANDLE handle, int* contrast);

 /**
 * @brief 设置热成像图像对比度参数
 * @param[in] handle 操作句柄
 * @param[in] contrast 对比度
 * @return 错误码
 */
IRC_NET_API int IRC_NET_CALL IRC_NET_SetThermalImageContrast(IRC_NET_HANDLE handle, int contrast);

 /**
 * @brief 获取热成像图像翻转状态
 * @param[in] handle 操作句柄
 * @param[out] flipMode 翻转状态
 * @return 错误码
 */
IRC_NET_API int IRC_NET_CALL IRC_NET_GetThermalImageFlipMode(IRC_NET_HANDLE handle, int* flipMode);

 /**
 * @brief 设置热成像图像翻转状态
 * @param[in] handle 操作句柄
 * @param[in] flipMode 翻转状态
 * @return 错误码
 */
IRC_NET_API int IRC_NET_CALL IRC_NET_SetThermalImageFlipMode(IRC_NET_HANDLE handle, int flipMode);

 /**
 * @brief 获取热成像图像增强信息
 * @param[in] handle 操作句柄
 * @param[out] thermalImageEnhanceInfo 热成像图像增强信息
 * @return 错误码
 */
IRC_NET_API int IRC_NET_CALL IRC_NET_GetThermalImageEnhanceInfo(IRC_NET_HANDLE handle, IRC_NET_THERMAL_IMAGE_MODE_ENHANCE_INFO* thermalImageEnhanceInfo);

 /**
 * @brief 设置热成像图像增强信息
 * @param[in] handle 操作句柄
 * @param[in] thermalImageEnhanceInfo 热成像图像增强信息
 * @return 错误码
 */
IRC_NET_API int IRC_NET_CALL IRC_NET_SetThermalImageEnhanceInfo(IRC_NET_HANDLE handle, IRC_NET_THERMAL_IMAGE_MODE_ENHANCE_INFO* thermalImageEnhanceInfo);

/**
* @brief 恢复出厂默认
* @param[in] handle 操作句柄
* @return 错误码
*/
IRC_NET_API int IRC_NET_CALL IRC_NET_RestoreFactoryDefaults(IRC_NET_HANDLE handle);

/**
* @brief 开始联动引导
* @param[in] handle 操作句柄
* @param[in] linkageTrackParam 联动引导参数
* @return 错误码
*/
IRC_NET_API int IRC_NET_CALL IRC_NET_StartLinkageTrack(IRC_NET_HANDLE handle, const IRC_NET_LINKAGE_TRACK_PARAM* linkageTrackParam);

/**
* @brief 结束联动引导
* @param[in] handle 操作句柄
* @param[in] linkageId 雷达/周扫引导的联动目标 id
* @return 错误码
*/
IRC_NET_API int IRC_NET_CALL IRC_NET_StopLinkageTrack(IRC_NET_HANDLE handle,int linkageId);

/**
* @brief 更新联动跟踪参数
* @param[in] handle 操作句柄
* @param[in] linkageId 雷达/周扫引导的联动目标 id
* @return 错误码
*/
IRC_NET_API int IRC_NET_CALL IRC_NET_UpdateLinkageTrackParam(IRC_NET_HANDLE handle, int linkageId);

/**
* @brief 获取枪球联动追踪器配置信息
* @param[in] handle 操作句柄
* @param[out] trackConfigInfo 枪球联动追踪器配置信息
* @return 错误码
*/
IRC_NET_API int IRC_NET_CALL IRC_NET_GetGunBallTrackConfigInfo(IRC_NET_HANDLE handle, IRC_NET_GUN_BALL_TRACK_CONFIG_INFO* trackConfigInfo);

/**
* @brief 设置枪球联动追踪器配置信息
* @param[in] handle 操作句柄
* @param[in] trackConfigInfo 枪球联动追踪器配置信息
* @return 错误码
*/
IRC_NET_API int IRC_NET_CALL IRC_NET_SetGunBallTrackConfigInfo(IRC_NET_HANDLE handle, const IRC_NET_GUN_BALL_TRACK_CONFIG_INFO* trackConfigInfo);

/**
* @brief 获取热成像变倍聚焦参数
* @param[in] handle 操作句柄
* @param[in] channel 通道
* @param[out] focusZoomParam 热成像变倍聚焦参数
* @return 错误码
*/
IRC_NET_API int IRC_NET_CALL IRC_NET_GetThermalFocusZoomParam(IRC_NET_HANDLE handle, int channel, IRC_NET_THERMAL_FOCUS_ZOOM_PARAM* focusZoomParam);

/**
* @brief 设置热成像变倍聚焦参数
* @param[in] handle 操作句柄
* @param[in] channel 通道
* @param[in] focusZoomParam 热成像变倍聚焦参数
* @return 错误码
*/
IRC_NET_API int IRC_NET_CALL IRC_NET_SetThermalFocusZoomParam(IRC_NET_HANDLE handle, int channel, const IRC_NET_THERMAL_FOCUS_ZOOM_PARAM* focusZoomParam);

/**
 * @brief 开启Http传输
 *
 * @param[in] handle 操作句柄
 * @param[in] httpCb HTTP返回数据回调函数
 * @param[in] userData 用户自定义数据,会通过httpCb原样抛出
 * @return 错误码
 */
IRC_NET_API int IRC_NET_CALL IRC_NET_StartHttpTransmission(IRC_NET_HANDLE handle, IRC_NET_HTTP_CALLBACK httpCb, void* userData);


/**
* @brief HTTP请求接口
* @param[in] handle 操作句柄
* @param[in] requestParam 请求参数
* @return 错误码
*/
IRC_NET_API int IRC_NET_CALL IRC_NET_SendHttpRequest(IRC_NET_HANDLE handle, const IRC_NET_HTTP_REQUEST_PARAM* requestParam);

/**
* @brief 停止Http传输
* @param[in] handle 操作句柄
* @return 错误码
*/
IRC_NET_API int IRC_NET_CALL IRC_NET_StopHttpTransmission(IRC_NET_HANDLE handle);

/**
* @brief 抓拍图像、温度、测温区域数据信息
* @param[in] handle 操作句柄
* @param[in] pictureDataType 图片数据类型，决定回调中 picture 返回 base64 字符串还是 jpg 二进制数据
* @param[in] imageTempCb 图像温度信息回调函数
* @param[in] userData 用户自定义数据
* @return 错误码
*/
IRC_NET_API int IRC_NET_CALL IRC_NET_GetImageTempInfo(IRC_NET_HANDLE handle, IRC_NET_IMAGE_TEMP_PICTURE_DATA_TYPE pictureDataType, IRC_NET_SNAP_IMAGE_TEMP_CALLBACK imageTempCb, void* userData);

#ifdef __cplusplus
}
#endif

#endif // IRCNETSDK_H
